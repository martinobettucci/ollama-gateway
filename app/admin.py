"""Panel d'admin LAN-only : login + gestion des clés (CRUD, origines, quotas) + dashboard d'usage.

Rendu serveur (Jinja2), formulaires HTML classiques (POST → redirect) : aucun build front, aucun
CDN, entièrement pilotable en E2E. Bind sur l'IP LAN uniquement, jamais forwardé à l'extérieur.
"""
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import (apis, auth, bans, charts, config, db, i18n, keys, reqlog, servers,
               targets, usage, whois)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MANUAL_PATH = Path(__file__).parent.parent / "docs" / "manual.md"


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    """Rend un template en injectant l'i18n de la requête (`t`, `lang`, `languages`, `native_name`)."""
    lang = i18n.negotiate(request)
    c = dict(ctx or {})
    c["t"] = lambda key, **kw: i18n.translate(key, lang, **kw)
    c["lang"] = lang
    c["languages"] = i18n.languages()
    c["native_name"] = i18n.native_name
    return TEMPLATES.TemplateResponse(request, name, c, status_code=status_code)


def _t(request: Request, key: str, **kw) -> str:
    """Traduit une chaîne (flash/erreur) dans la langue de la requête."""
    return i18n.translate(key, i18n.negotiate(request), **kw)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.check_runtime_secrets()  # fail-closed prod (secrets par défaut publics refusés)
    db.init_db()
    servers.ensure_default()  # serveur local par défaut + réassignation des clés orphelines
    targets.ensure_default()  # cible publique par défaut + rattachement des clés orphelines
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.ADMIN_SESSION_SECRET,
                   session_cookie="ollama_gw_admin", same_site="lax",
                   https_only=config.ADMIN_COOKIE_SECURE)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """En-têtes de sécurité sur toutes les réponses de l'admin (LAN-only, hors Caddy).

    CSP avec `'unsafe-inline'` : le panel assume des styles/scripts inline (rendu serveur sans
    build front, cf. DESIGN_SYSTEM §6). La CSP bloque tout de même les origines externes, le
    mixed-content et le cadrage ; défense en profondeur (l'admin n'a pas de faille XSS connue)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; "
        "object-src 'none'")
    return response


@app.middleware("http")
async def csrf_same_origin(request: Request, call_next):
    """Protection CSRF par **same-origin strict** (complète le cookie `SameSite=Lax`).

    Sur toute requête MUTANTE vers `/admin/*`, si le navigateur fournit un `Origin`/`Referer`, son
    hôte doit correspondre au `Host` de la requête : un POST cross-site (page attaquante) porte un
    `Origin` étranger → refusé (403). Les clients non-navigateur (sans `Origin`/`Referer`, ex.
    tests, curl) ne sont pas concernés (pas de session de navigateur = pas de vecteur CSRF)."""
    if request.method not in _SAFE_METHODS and request.url.path.startswith("/admin"):
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            src_host = urlsplit(source).netloc.split("@")[-1]
            host = request.headers.get("host", "")
            if src_host and host and src_host != host:
                return JSONResponse(
                    {"error": "requête cross-origin refusée (CSRF)"}, status_code=403)
    return await call_next(request)


# --- Limitation des tentatives de login (anti-brute-force) ------------------------------------
# Fenêtre glissante d'échecs par IP source (admin mono-process par rôle → état mémoire suffisant).
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_MAX_FAILS = 5          # au-delà, verrouillage temporaire
_LOGIN_WINDOW_S = 300         # fenêtre d'observation des échecs (5 min)


def _login_client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _login_locked(ip: str, now: float | None = None) -> bool:
    now = now if now is not None else time.monotonic()
    fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW_S]
    _LOGIN_FAILS[ip] = fails
    return len(fails) >= _LOGIN_MAX_FAILS


def _login_record_fail(ip: str, now: float | None = None) -> None:
    now = now if now is not None else time.monotonic()
    _LOGIN_FAILS.setdefault(ip, []).append(now)


def _login_clear(ip: str) -> None:
    _LOGIN_FAILS.pop(ip, None)


def _guard(request: Request) -> RedirectResponse | None:
    """Renvoie une redirection si non authentifié / non initialisé, sinon None."""
    if keys.get_admin_hash() is None:
        return RedirectResponse("/admin/setup", status_code=303)
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _parse_int(v: str | None) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except ValueError:
        return None


def _parse_retention(v: str | None) -> int | None:
    """Rétention de logs (jours) : entier ≥ 0, ou None (vide/invalide → défaut global)."""
    v = (v or "").strip()
    if not v:
        return None
    try:
        n = int(v)
        return n if n >= 0 else None
    except ValueError:
        return None


def _parse_dt_local(v: str | None) -> str | None:
    """Champ `datetime-local` ('YYYY-MM-DDTHH:MM') → 'YYYY-MM-DD HH:MM:SS' pour SQLite, ou None."""
    v = (v or "").strip()
    if not v:
        return None
    v = v.replace("T", " ")
    return v if len(v) > 16 else v + ":00"


def _parse_origins(raw: str) -> list[str]:
    """Découpe une saisie multi-lignes/virgules en liste de CIDR/IP nettoyés."""
    out: list[str] = []
    for chunk in (raw or "").replace(",", "\n").splitlines():
        c = chunk.strip()
        if c:
            out.append(c)
    return out


def _parse_lines(raw: str) -> list[str]:
    """Découpe une saisie multi-lignes en liste nettoyée, sans doublons (noms de modèles)."""
    out: list[str] = []
    for chunk in (raw or "").replace(",", "\n").splitlines():
        c = chunk.strip()
        if c and c not in out:
            out.append(c)
    return out


def _collect_models(form) -> list[str]:
    """Combine les modèles cochés (cases) et la saisie libre (textarea), dédupliqués."""
    checked = [m.strip() for m in form.getlist("model_check") if m.strip()]
    free = _parse_lines(form.get("models", ""))
    out: list[str] = []
    for m in checked + free:
        if m not in out:
            out.append(m)
    return out


def _collect_apis(form) -> list[str]:
    """Familles d'API cochées (allowlist, image comprise). Vide = toutes les API autorisées."""
    return [a for a in form.getlist("api_check") if a in apis.FAMILIES]


def _collect_image_models(form) -> list[str]:
    """Modèles d'IMAGE cochés (cases `x/…`) + saisie libre, dédupliqués (allowlist séparée)."""
    checked = [m.strip() for m in form.getlist("image_model_check") if m.strip()]
    free = _parse_lines(form.get("image_models", ""))
    out: list[str] = []
    for m in checked + free:
        if m not in out:
            out.append(m)
    return out


# --- Initialisation / login -------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    if keys.get_admin_hash() is not None:
        return RedirectResponse("/admin/login", status_code=303)
    return render(request, "setup.html", {"error": None})


@app.post("/admin/setup")
async def setup_submit(request: Request, password: str = Form(...), confirm: str = Form(...)):
    if keys.get_admin_hash() is not None:
        return RedirectResponse("/admin/login", status_code=303)
    if len(password) < 8 or password != confirm:
        return render(request, "setup.html",
                      {"error": _t(request, "setup.error_pw")}, status_code=400)
    keys.set_admin_password(password)
    request.session["admin"] = True
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if keys.get_admin_hash() is None:
        return RedirectResponse("/admin/setup", status_code=303)
    return render(request, "login.html", {"error": None})


@app.post("/admin/login")
async def login_submit(request: Request, password: str = Form(...)):
    ip = _login_client_ip(request)
    if _login_locked(ip):
        return render(request, "login.html",
                      {"error": _t(request, "login.throttled")}, status_code=429)
    stored = keys.get_admin_hash()
    if stored and auth.verify_password(password, stored):
        _login_clear(ip)
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    _login_record_fail(ip)
    return render(request, "login.html",
                  {"error": _t(request, "login.wrong")}, status_code=401)


@app.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@app.post("/admin/lang")
async def set_lang(request: Request, lang: str = Form(...), next: str = Form("/admin")):
    """Change la langue du panel (stockée en session). Disponible même déconnecté."""
    if lang in i18n.ENABLED:
        request.session["lang"] = lang
    dest = next if next.startswith("/admin") else "/admin"
    return RedirectResponse(dest, status_code=303)


# --- Manuel utilisateur -----------------------------------------------------------------------

@app.get("/admin/manual", response_class=HTMLResponse)
async def manual(request: Request):
    """Fragment HTML du manuel (docs/manual.md) pour la modale du panel.

    Les chemins d'images GitHub (`../app/static/manual/`) sont remappés vers `/static/manual/`
    et les blocs Mermaid sont retirés (les captures d'écran illustrent déjà chaque écran).
    """
    if (r := _guard(request)):
        return r
    text = MANUAL_PATH.read_text(encoding="utf-8")
    text = re.sub(r"```mermaid.*?```\n?", "", text, flags=re.DOTALL)
    text = text.replace("../app/static/manual/", "/static/manual/")
    html = markdown.markdown(text, extensions=["tables", "fenced_code"])
    return HTMLResponse(html)


# --- Dashboard / clés -------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request):
    if (r := _guard(request)):
        return r
    return render(request, "dashboard.html", {
        "keys": keys.list_keys(),
        "totals": usage.global_summary(),
        "servers": servers.list_servers(),
        "targets": targets.list_targets(),
        "created": request.session.pop("created_key", None),
        "public_base_url": config.PUBLIC_BASE_URL,
    })


@app.post("/admin/keys")
async def create_key(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    server_id = _parse_int(form.get("server_id", "")) or servers.default_id(db.connect())
    target_id = _parse_int(form.get("target_id", ""))
    rec, secret = keys.create_key(
        label=(form.get("label", "").strip() or "sans-nom"),
        origins=_parse_origins(form.get("origins", "")),
        monthly_token_cap=_parse_int(form.get("monthly_token_cap", "")),
        rpm_limit=_parse_int(form.get("rpm_limit", "")),
        note=form.get("note", "").strip(),
        server_id=server_id, models=_collect_models(form), key_apis=_collect_apis(form),
        image_models=_collect_image_models(form),
        target_id=target_id, fallback_server_id=_parse_int(form.get("fallback_server_id", "")),
        total_token_cap=_parse_int(form.get("total_token_cap", "")),
        total_request_cap=_parse_int(form.get("total_request_cap", "")),
        expires_at=_parse_dt_local(form.get("expires_at", "")),
        idle_expiry_days=_parse_int(form.get("idle_expiry_days", "")),
        log_retention_days=_parse_retention(form.get("log_retention_days", "")))
    # Le secret n'est montré qu'ici, une seule fois (via un flash de session). L'URL de la cible
    # rattachée sert à générer les variables d'environnement ; si la cible est restée sur le
    # placeholder, on préfère l'URL publique configurée (robuste quel que soit l'ordre de démarrage).
    turl = rec.target_base_url
    if not turl or turl == targets.PLACEHOLDER_URL:
        turl = config.PUBLIC_BASE_URL or turl
    request.session["created_key"] = {
        "label": rec.label, "secret": secret, "target_url": turl}
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/keys/{key_id}", response_class=HTMLResponse)
async def key_detail(request: Request, key_id: int):
    if (r := _guard(request)):
        return r
    rec = keys.get_key(key_id)
    if rec is None:
        return RedirectResponse("/admin", status_code=303)
    return render(request, "key_detail.html", {
        "key": rec, "summary": usage.key_summary(key_id),
        "servers": servers.list_servers(),
        "targets": targets.list_targets(),
        "origins_seen": usage.origins_seen(key_id),
        "retention_default": config.REQUEST_LOG_RETENTION_DAYS,
    })


@app.post("/admin/keys/{key_id}")
async def key_update(request: Request, key_id: int):
    if (r := _guard(request)):
        return r
    form = await request.form()
    keys.update_key(
        key_id, label=(form.get("label", "").strip() or "sans-nom"),
        origins=_parse_origins(form.get("origins", "")),
        monthly_token_cap=_parse_int(form.get("monthly_token_cap", "")),
        rpm_limit=_parse_int(form.get("rpm_limit", "")),
        note=form.get("note", "").strip(),
        server_id=_parse_int(form.get("server_id", "")), models=_collect_models(form),
        key_apis=_collect_apis(form), image_models=_collect_image_models(form),
        target_id=_parse_int(form.get("target_id", "")),
        fallback_server_id=_parse_int(form.get("fallback_server_id", "")),
        clear_fallback=("fallback_server_id" in form
                        and not (form.get("fallback_server_id") or "").strip()),
        total_token_cap=_parse_int(form.get("total_token_cap", "")),
        total_request_cap=_parse_int(form.get("total_request_cap", "")),
        expires_at=_parse_dt_local(form.get("expires_at", "")),
        idle_expiry_days=_parse_int(form.get("idle_expiry_days", "")),
        log_retention_days=_parse_retention(form.get("log_retention_days", "")))
    return RedirectResponse(f"/admin/keys/{key_id}", status_code=303)


@app.post("/admin/keys/{key_id}/try-chat")
async def key_try_chat(request: Request, key_id: int):
    """Chat de test (« Essayer maintenant ») : relais LAN-only vers le serveur rattaché à la clé.
    Respecte l'allowlist de modèles de la clé (fidèle au proxy). Jamais routé par Caddy."""
    if (r := _guard(request)):
        return r
    rec = keys.get_key(key_id)
    if rec is None:
        return JSONResponse({"error": "clé introuvable"}, status_code=404)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message vide"}, status_code=400)
    api = (body.get("api") or "ollama").strip()
    if api not in servers.TRY_APIS:
        return JSONResponse({"error": f"API inconnue: {api}"}, status_code=400)
    server_id = rec.server_id or servers.default_id(db.connect())
    model = (body.get("model") or "").strip()
    if model:
        if rec.models and model not in set(rec.models):
            return JSONResponse(
                {"error": f"modèle « {model} » hors allowlist de la clé"}, status_code=403)
    elif rec.models:
        model = rec.models[0]
    else:
        online, avail, _ = await servers.test_server(server_id)
        if not online or not avail:
            return JSONResponse(
                {"error": "serveur injoignable ou sans modèle disponible"}, status_code=502)
        model = avail[0]
    reply, err = await servers.try_call(server_id, api, model, message)
    if err:
        return JSONResponse({"error": err, "model": model, "api": api}, status_code=502)
    return JSONResponse({"reply": reply, "model": model, "api": api})


@app.post("/admin/keys/{key_id}/try-image")
async def key_try_image(request: Request, key_id: int):
    """Génération d'IMAGE de test (onglet « Image ») : relais LAN-only. Respecte l'allowlist de
    modèles d'image de la clé ; accepte une image d'entrée jointe (image-to-image). Jamais Caddy."""
    if (r := _guard(request)):
        return r
    rec = keys.get_key(key_id)
    if rec is None:
        return JSONResponse({"error": "clé introuvable"}, status_code=404)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        body = {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt vide"}, status_code=400)
    api = (body.get("api") or "ollama-image").strip()
    if api not in servers.IMAGE_TRY_APIS:
        return JSONResponse({"error": f"API image inconnue: {api}"}, status_code=400)
    model = (body.get("model") or "").strip()
    if model:
        if rec.image_models and model not in set(rec.image_models):
            return JSONResponse(
                {"error": f"modèle d'image « {model} » hors allowlist de la clé"}, status_code=403)
    elif rec.image_models:
        model = rec.image_models[0]
    else:
        return JSONResponse({"error": "aucun modèle d'image sélectionné"}, status_code=400)
    # Image d'entrée optionnelle : accepte une data URL ou une base64 brute → on retire le préfixe.
    image_b64 = (body.get("image") or "").strip()
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[-1]
    server_id = rec.server_id or servers.default_id(db.connect())
    b64, err = await servers.try_image(server_id, api, model, prompt, image_b64)
    if err:
        return JSONResponse({"error": err, "model": model, "api": api}, status_code=502)
    return JSONResponse({"image": f"data:image/png;base64,{b64}", "model": model, "api": api})


@app.post("/admin/keys/{key_id}/toggle")
async def key_toggle(request: Request, key_id: int):
    if (r := _guard(request)):
        return r
    rec = keys.get_key(key_id)
    if rec:
        keys.set_enabled(key_id, not rec.enabled)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/keys/{key_id}/delete")
async def key_delete(request: Request, key_id: int):
    if (r := _guard(request)):
        return r
    keys.delete_key(key_id)
    return RedirectResponse("/admin", status_code=303)


# --- Console de logs + bannissement d'origines ------------------------------------------------

@app.get("/admin/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Console de logs : journal COMPLET des requêtes (conservé append-only) + liste de
    bannissement d'origines. Chaque ligne permet de bannir l'IP en un clic."""
    if (r := _guard(request)):
        return r
    events = usage.recent_events(500)
    return render(request, "logs.html", {
        "events": events,
        "total": usage.total_events(),
        "banned_ips": bans.banned_among(e["client_ip"] for e in events),
        "bans": bans.list_bans(),
        "flash": request.session.pop("logs_flash", None),
    })


@app.post("/admin/logs/ban")
async def logs_ban(request: Request):
    """Bannit une IP/CIDR (bouton « Bannir » d'une ligne, ou saisie manuelle)."""
    if (r := _guard(request)):
        return r
    form = await request.form()
    norm = bans.add_ban(form.get("cidr", ""), form.get("reason", ""))
    request.session["logs_flash"] = (
        {"ok": True, "text": f"Origine bannie : {norm}"} if norm
        else {"ok": False, "text": "IP/CIDR invalide — rien banni."})
    return RedirectResponse("/admin/logs", status_code=303)


@app.get("/admin/logs/content", response_class=HTMLResponse)
async def logs_content(request: Request):
    """Visionneuse du CONTENU complet des requêtes (fichiers hors base) : choix clé/heure +
    filtre grep, rendu des lignes correspondantes. Contenu déjà sanitisé (secrets masqués)."""
    if (r := _guard(request)):
        return r
    keys_with_logs = reqlog.list_keys_with_logs()
    valid_dirs = {k["dir"] for k in keys_with_logs}
    sel_key = request.query_params.get("key", "")
    if sel_key not in valid_dirs:
        sel_key = keys_with_logs[0]["dir"] if keys_with_logs else ""
    files = reqlog.list_files(sel_key) if sel_key else []
    valid_files = {f["name"] for f in files}
    sel_file = request.query_params.get("file", "")
    if sel_file not in valid_files:
        sel_file = files[0]["name"] if files else ""
    q = request.query_params.get("q", "")
    result = reqlog.read_content(sel_key, sel_file, grep=q) if sel_file else None
    return render(request, "logs_content.html", {
        "enabled": bool(config.REQUEST_LOG_DIR),
        "keys_with_logs": keys_with_logs, "files": files,
        "sel_key": sel_key, "sel_file": sel_file, "q": q, "result": result, "limit": 2000,
    })


@app.get("/admin/logs/content/raw")
async def logs_content_raw(request: Request):
    """Télécharge le fichier de log sélectionné en texte brut (gzip décompressé). LAN-only."""
    if (r := _guard(request)):
        return r
    p = reqlog.resolve(request.query_params.get("key", ""),
                       request.query_params.get("file", ""))
    if p is None:
        return JSONResponse({"error": "fichier introuvable"}, status_code=404)
    with reqlog.open_text(p) as f:
        content = f.read()
    return PlainTextResponse(content)


@app.get("/admin/whois")
async def whois_lookup(request: Request):
    """Résolution WHOIS/RDAP d'une IP (bouton « WHOIS » des origines d'une clé). LAN-only."""
    if (r := _guard(request)):
        return r
    ip = request.query_params.get("ip", "")
    return JSONResponse(await whois.lookup(ip))


@app.post("/admin/bans/{ban_id}/delete")
async def ban_delete(request: Request, ban_id: int):
    if (r := _guard(request)):
        return r
    bans.remove_ban(ban_id)
    request.session["logs_flash"] = {"ok": True, "text": "Bannissement levé."}
    return RedirectResponse("/admin/logs", status_code=303)


# --- Serveurs d'exécution ---------------------------------------------------------------------

@app.get("/admin/servers", response_class=HTMLResponse)
async def servers_page(request: Request):
    if (r := _guard(request)):
        return r
    return render(request, "servers.html", {
        "servers": servers.list_servers(),
        "flash": request.session.pop("server_flash", None),
    })


@app.post("/admin/servers")
async def server_create(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    base = form.get("base_url", "").strip()
    if base:
        try:
            servers.validate_base_url(base)
            servers.create_server(
                name=form.get("name", "").strip() or "serveur",
                base_url=base, auth_token=form.get("auth_token", "").strip())
        except ValueError as exc:
            request.session["server_flash"] = {"ok": False, "text": f"URL amont invalide : {exc}"}
    return RedirectResponse("/admin/servers", status_code=303)


@app.post("/admin/servers/{server_id}")
async def server_update(request: Request, server_id: int):
    if (r := _guard(request)):
        return r
    form = await request.form()
    base = form.get("base_url", "").strip()
    if base:
        try:
            servers.validate_base_url(base)
        except ValueError as exc:
            request.session["server_flash"] = {"ok": False, "text": f"URL amont invalide : {exc}"}
            return RedirectResponse("/admin/servers", status_code=303)
    servers.update_server(
        server_id, name=form.get("name", "").strip() or "serveur",
        base_url=base,
        enabled=form.get("enabled") is not None,
        auth_token=form.get("auth_token", ""),
        clear_auth=form.get("clear_auth") is not None)
    return RedirectResponse("/admin/servers", status_code=303)


@app.get("/admin/servers/{server_id}/models")
async def server_models(request: Request, server_id: int):
    """Sonde LIVE du serveur (spec « rattachement ») : appelée au rendu des formulaires de clé et
    à chaque changement de serveur, pour peupler les cases à cocher des modèles réellement
    disponibles. Persiste aussi le résultat (en ligne/hors ligne + modèles)."""
    if (r := _guard(request)):
        return r
    online, models, err = await servers.test_server(server_id)
    return JSONResponse({"online": online, "models": models, "error": err})


@app.post("/admin/servers/{server_id}/test")
async def server_test(request: Request, server_id: int):
    if (r := _guard(request)):
        return r
    online, models, err = await servers.test_server(server_id)
    if online:
        request.session["server_flash"] = {
            "ok": True, "text": f"Serveur en ligne — {len(models)} modèle(s) détecté(s)."}
    else:
        request.session["server_flash"] = {
            "ok": False, "text": f"Serveur injoignable ({err})."}
    return RedirectResponse("/admin/servers", status_code=303)


@app.post("/admin/servers/{server_id}/compat")
async def server_compat(request: Request, server_id: int):
    """Rejoue le test de compatibilité d'API (accessibilité des chemins) et stocke la matrice."""
    if (r := _guard(request)):
        return r
    matrix = await servers.run_compat(server_id)
    served = sum(1 for eps in matrix.values() for e in eps if e.get("served"))
    total = sum(len(eps) for eps in matrix.values())
    request.session["server_flash"] = {
        "ok": bool(total), "text": f"Compatibilité testée — {served}/{total} chemin(s) servi(s)."}
    return RedirectResponse("/admin/servers", status_code=303)


@app.get("/admin/servers/{server_id}/monitor", response_class=HTMLResponse)
async def server_monitor(request: Request, server_id: int):
    """Monitoring d'un serveur : consommation/erreurs PAR CLÉ + graphiques (barres, camembert,
    séries temporelles). Attribution réelle via `usage_events.server_id` (repli inclus)."""
    if (r := _guard(request)):
        return r
    srv = servers.get_server(server_id)
    if srv is None:
        return RedirectResponse("/admin/servers", status_code=303)
    conn = db.connect()
    try:
        summary = usage.server_summary(server_id, conn)
        per_key = usage.server_per_key(server_id, conn)
        status = usage.server_status_breakdown(server_id, conn)
        daily = usage.server_daily(server_id, 30, conn)
    finally:
        conn.close()
    svg = {
        "tokens_bar": charts.hbar([(r["label"], r["tokens"]) for r in per_key[:10]],
                                  "Tokens par clé", unit=" tok"),
        "reqs_bar": charts.hbar([(r["label"], r["reqs"]) for r in per_key[:10]],
                                "Requêtes par clé", color=charts.SUCCESS),
        "status_donut": charts.donut(
            [(k, v, charts.STATUS_COLORS[k]) for k, v in status.items()], "Statuts"),
        "reqs_line": charts.line([(d["day"][5:], d["reqs"]) for d in daily], "Requêtes / jour"),
        "tokens_line": charts.line([(d["day"][5:], d["tokens"]) for d in daily],
                                   "Tokens / jour", color=charts.ACCENT),
    }
    return render(request, "monitor.html", {
        "server": srv, "summary": summary, "per_key": per_key,
        "status": status, "svg": svg,
    })


@app.post("/admin/servers/{server_id}/toggle")
async def server_toggle(request: Request, server_id: int):
    if (r := _guard(request)):
        return r
    srv = servers.get_server(server_id)
    if srv:
        servers.set_enabled(server_id, not srv.enabled)
    return RedirectResponse("/admin/servers", status_code=303)


@app.post("/admin/servers/{server_id}/delete")
async def server_delete(request: Request, server_id: int):
    if (r := _guard(request)):
        return r
    err = servers.delete_server(server_id)
    if err:
        request.session["server_flash"] = {"ok": False, "text": err}
    return RedirectResponse("/admin/servers", status_code=303)


# --- Cibles publiques (ingress) ---------------------------------------------------------------

@app.get("/admin/targets", response_class=HTMLResponse)
async def targets_page(request: Request):
    if (r := _guard(request)):
        return r
    return render(request, "targets.html", {
        "targets": targets.list_targets(),
        "keys_by_target": {t.id: targets.keys_count(t.id) for t in targets.list_targets()},
        "flash": request.session.pop("target_flash", None),
        "public_base_url": config.PUBLIC_BASE_URL,
    })


@app.post("/admin/targets")
async def target_create(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    base = form.get("base_url", "").strip()
    if base:
        targets.create_target(name=form.get("name", "").strip() or "cible", base_url=base)
    return RedirectResponse("/admin/targets", status_code=303)


@app.post("/admin/targets/{target_id}")
async def target_update(request: Request, target_id: int):
    if (r := _guard(request)):
        return r
    form = await request.form()
    targets.update_target(target_id, name=form.get("name", "").strip() or "cible",
                          base_url=form.get("base_url", "").strip())
    return RedirectResponse("/admin/targets", status_code=303)


@app.post("/admin/targets/{target_id}/delete")
async def target_delete(request: Request, target_id: int):
    if (r := _guard(request)):
        return r
    err = targets.delete_target(target_id)
    if err:
        request.session["target_flash"] = {"ok": False, "text": err}
    return RedirectResponse("/admin/targets", status_code=303)
