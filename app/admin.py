"""Panel d'admin LAN-only : login + gestion des clés (CRUD, origines, quotas) + dashboard d'usage.

Rendu serveur (Jinja2), formulaires HTML classiques (POST → redirect) : aucun build front, aucun
CDN, entièrement pilotable en E2E. Bind sur l'IP LAN uniquement, jamais forwardé à l'extérieur.
"""
import re
from contextlib import asynccontextmanager
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import apis, auth, bans, config, db, keys, servers, usage, whois

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MANUAL_PATH = Path(__file__).parent.parent / "docs" / "manual.md"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    servers.ensure_default()  # serveur local par défaut + réassignation des clés orphelines
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.ADMIN_SESSION_SECRET,
                   session_cookie="ollama_gw_admin", same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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
    """Familles d'API cochées (allowlist). Vide = toutes les API autorisées."""
    return [a for a in form.getlist("api_check") if a in apis.FAMILIES]


# --- Initialisation / login -------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    if keys.get_admin_hash() is not None:
        return RedirectResponse("/admin/login", status_code=303)
    return TEMPLATES.TemplateResponse(request, "setup.html", {"error": None})


@app.post("/admin/setup")
async def setup_submit(request: Request, password: str = Form(...), confirm: str = Form(...)):
    if keys.get_admin_hash() is not None:
        return RedirectResponse("/admin/login", status_code=303)
    if len(password) < 8 or password != confirm:
        return TEMPLATES.TemplateResponse(
            request, "setup.html",
            {"error": "Mot de passe trop court (min 8) ou non identique."}, status_code=400)
    keys.set_admin_password(password)
    request.session["admin"] = True
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if keys.get_admin_hash() is None:
        return RedirectResponse("/admin/setup", status_code=303)
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})


@app.post("/admin/login")
async def login_submit(request: Request, password: str = Form(...)):
    stored = keys.get_admin_hash()
    if stored and auth.verify_password(password, stored):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return TEMPLATES.TemplateResponse(
        request, "login.html", {"error": "Mot de passe incorrect."}, status_code=401)


@app.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


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
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "keys": keys.list_keys(),
        "totals": usage.global_summary(),
        "servers": servers.list_servers(),
        "created": request.session.pop("created_key", None),
        "public_base_url": config.PUBLIC_BASE_URL,
    })


@app.post("/admin/keys")
async def create_key(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    server_id = _parse_int(form.get("server_id", "")) or servers.default_id(db.connect())
    rec, secret = keys.create_key(
        label=(form.get("label", "").strip() or "sans-nom"),
        origins=_parse_origins(form.get("origins", "")),
        monthly_token_cap=_parse_int(form.get("monthly_token_cap", "")),
        rpm_limit=_parse_int(form.get("rpm_limit", "")),
        note=form.get("note", "").strip(),
        server_id=server_id, models=_collect_models(form), key_apis=_collect_apis(form),
        log_retention_days=_parse_retention(form.get("log_retention_days", "")))
    # Le secret n'est montré qu'ici, une seule fois (via un flash de session).
    request.session["created_key"] = {"label": rec.label, "secret": secret}
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/keys/{key_id}", response_class=HTMLResponse)
async def key_detail(request: Request, key_id: int):
    if (r := _guard(request)):
        return r
    rec = keys.get_key(key_id)
    if rec is None:
        return RedirectResponse("/admin", status_code=303)
    return TEMPLATES.TemplateResponse(request, "key_detail.html", {
        "key": rec, "summary": usage.key_summary(key_id),
        "servers": servers.list_servers(),
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
        key_apis=_collect_apis(form),
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
    return TEMPLATES.TemplateResponse(request, "logs.html", {
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
    return TEMPLATES.TemplateResponse(request, "servers.html", {
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
        servers.create_server(
            name=form.get("name", "").strip() or "serveur",
            base_url=base, auth_token=form.get("auth_token", "").strip())
    return RedirectResponse("/admin/servers", status_code=303)


@app.post("/admin/servers/{server_id}")
async def server_update(request: Request, server_id: int):
    if (r := _guard(request)):
        return r
    form = await request.form()
    servers.update_server(
        server_id, name=form.get("name", "").strip() or "serveur",
        base_url=form.get("base_url", "").strip(),
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
