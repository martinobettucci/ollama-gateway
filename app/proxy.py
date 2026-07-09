"""Proxy d'inférence : valide la clé, l'origine et le quota, puis relaie vers Ollama en streaming.

Exposé (via Caddy) sur les chemins /api/* et /v1/*. Reproduit et étend le proxy nginx historique :
- strip de l'en-tête `Authorization` avant l'amont (Ollama local n'a pas d'auth) ;
- streaming intégral (NDJSON Ollama natif ou SSE OpenAI), timeouts longs, corps illimité ;
- comptage des tokens lus dans le payload de fin (`prompt_eval_count`/`eval_count` ou `usage`).
Chaque requête (autorisée ou refusée) est journalisée dans usage_events.
"""
import ipaddress
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from . import apis, auth, bans, config, db, keys, quotas, reqlog, servers, usage

# En-têtes hop-by-hop / recalculés à ne pas recopier tels quels. x-api-key porte la clé
# cliente (SDK Anthropic) : strippé comme Authorization, jamais transmis à l'amont.
_DROP_REQ_HEADERS = {"host", "authorization", "x-api-key", "content-length", "connection",
                     "proxy-connection", "keep-alive", "transfer-encoding", "upgrade"}
_DROP_RESP_HEADERS = {"content-length", "transfer-encoding", "connection", "keep-alive"}

# Endpoints de listing de modèles (toutes APIs) : réponse filtrée sur l'allowlist de la clé.
# Ollama natif → {"models":[{"name"|"model":…}]} ; OpenAI/Anthropic → {"data":[{"id":…}]}.
_LISTING_PATHS = {"/api/tags", "/v1/models"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    servers.ensure_default()  # serveur local par défaut + réassignation des clés orphelines
    # Client sans base_url : chaque requête cible l'URL absolue du serveur rattaché à la clé.
    app.state.upstream = httpx.AsyncClient(
        timeout=httpx.Timeout(config.UPSTREAM_TIMEOUT_S, connect=15.0),
    )
    try:
        yield
    finally:
        await app.state.upstream.aclose()


def _filter_models(content: bytes, allowed: set[str]) -> bytes:
    """Filtre une réponse de listing pour ne garder que les modèles autorisés (formes Ollama et
    OpenAI/Anthropic). Renvoie le corps original si non-JSON ou forme inattendue."""
    try:
        obj = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return content
    if not isinstance(obj, dict):
        return content
    if isinstance(obj.get("models"), list):  # Ollama /api/tags
        obj["models"] = [m for m in obj["models"] if isinstance(m, dict)
                         and (m.get("name") in allowed or m.get("model") in allowed)]
    if isinstance(obj.get("data"), list):  # OpenAI/Anthropic /v1/models
        obj["data"] = [m for m in obj["data"]
                       if isinstance(m, dict) and m.get("id") in allowed]
    return json.dumps(obj).encode("utf-8")


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _peer_trusted(peer: str) -> bool:
    """True si le pair immédiat appartient à une IP/CIDR de confiance (Caddy)."""
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in config.TRUSTED_PROXY_IPS:
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """IP source réelle : XFF si le pair immédiat est un proxy de confiance (Caddy), sinon le pair."""
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for")
    if xff and _peer_trusted(peer):
        return xff.split(",")[0].strip()
    return peer


class _TokenSniffer:
    """Extrait model + compteurs de tokens d'un flux de réponse Ollama/OpenAI, ligne par ligne.

    Bornes mémoire : ne conserve qu'une ligne incomplète en tampon (les lignes parsées sont jetées).
    """

    def __init__(self) -> None:
        self.model = ""
        self.tokens_prompt = 0
        self.tokens_completion = 0
        self._buf = b""

    def _parse_line(self, line: bytes) -> None:
        s = line.strip()
        if not s:
            return
        if s.startswith(b"data:"):
            s = s[5:].strip()
        if s == b"[DONE]" or not (s.startswith(b"{") or s.startswith(b"[")):
            return
        try:
            obj = json.loads(s)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(obj, dict):
            return
        if obj.get("model"):
            self.model = obj["model"]
        # Ollama natif : prompt_eval_count / eval_count (présents au dernier chunk `done`).
        if "prompt_eval_count" in obj:
            self.tokens_prompt = int(obj.get("prompt_eval_count") or 0)
        if "eval_count" in obj:
            self.tokens_completion = int(obj.get("eval_count") or 0)
        # OpenAI-compat : usage.{prompt_tokens,completion_tokens}.
        u = obj.get("usage")
        if isinstance(u, dict):
            if u.get("prompt_tokens") is not None:
                self.tokens_prompt = int(u["prompt_tokens"])
            if u.get("completion_tokens") is not None:
                self.tokens_completion = int(u["completion_tokens"])

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._parse_line(line)

    def finish(self) -> None:
        if self._buf:
            self._parse_line(self._buf)
            self._buf = b""


def _model_from_body(body: bytes) -> str:
    try:
        obj = json.loads(body)
        if isinstance(obj, dict) and isinstance(obj.get("model"), str):
            return obj["model"]
    except (ValueError, UnicodeDecodeError):
        pass
    return ""


def _log(key_id, ip, method, path, model, status, t0, **kw) -> None:
    usage.record(
        key_id=key_id, client_ip=ip, method=method, path=path, model=model, status=status,
        duration_ms=int((time.monotonic() - t0) * 1000), **kw,
    )


@app.get("/_proxy_health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok\n")


@app.api_route("/{full_path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(request: Request, full_path: str):
    t0 = time.monotonic()
    ip = client_ip(request)
    method = request.method
    path = "/" + full_path

    # --- Bannissement global d'origine (DENY avant toute auth ; opéré depuis la console) ---
    if bans.is_banned(ip):
        _log(None, ip, method, path, "", 403, t0)
        return JSONResponse({"error": "origine bannie"}, status_code=403)

    if not path.startswith(config.ALLOWED_PATH_PREFIXES):
        return JSONResponse({"error": "not found"}, status_code=404)

    # --- Authentification par clé (Bearer, ou x-api-key pour le SDK Anthropic) ---
    key = auth.extract_api_key(request.headers)
    if not key:
        _log(None, ip, method, path, "", 401, t0)
        return JSONResponse({"error": "clé API manquante"}, status_code=401)

    row = keys.find_by_key(key)
    if row is None or not row["enabled"]:
        kid = row["id"] if row else None
        _log(kid, ip, method, path, "", 401, t0)
        return JSONResponse({"error": "clé API invalide ou désactivée"}, status_code=401)

    rec = keys.get_key(row["id"])

    # --- Restriction d'origine ---
    if not keys.origin_allowed(ip, rec.origins):
        _log(rec.id, ip, method, path, "", 403, t0)
        return JSONResponse({"error": "origine non autorisée pour cette clé"}, status_code=403)

    # --- Quotas + résolution du serveur d'exécution rattaché ---
    conn = db.connect()
    try:
        ok, reason = quotas.check(rec, conn)
        srv = servers.get_server(rec.server_id, conn) if rec.server_id else None
        srv_auth = servers.auth_header_for(rec.server_id, conn) if srv else {}
    finally:
        conn.close()
    if not ok:
        _log(rec.id, ip, method, path, "", 429, t0)
        return JSONResponse({"error": reason}, status_code=429)
    if srv is None or not srv.enabled:
        _log(rec.id, ip, method, path, "", 503, t0)
        return JSONResponse(
            {"error": "aucun serveur d'exécution disponible pour cette clé"}, status_code=503)

    # --- Restriction de modèle (agnostique de l'API : le modèle est à la racine du corps pour
    #     Ollama, OpenAI chat/responses et Anthropic messages) ---
    body = await request.body()
    req_model = _model_from_body(body)

    def _content_log(status: int, model: str) -> None:
        # Contenu COMPLET (sanitisé) sur disque, hors base — best-effort, ne lève jamais.
        reqlog.record(key_id=rec.id, ip=ip, method=method, path=path,
                      headers=request.headers, body=body, status=status, model=model)

    if rec.models and req_model and req_model not in set(rec.models):
        _log(rec.id, ip, method, path, req_model, 403, t0, bytes_in=len(body))
        _content_log(403, req_model)
        return JSONResponse(
            {"error": f"modèle non autorisé pour cette clé: {req_model}"}, status_code=403)

    # --- Restriction d'API (allow/forbid de CHEMIN, agnostique du schéma) : allowlist vide =
    #     toutes les familles autorisées. Les endpoints de listing restent toujours servis
    #     (déjà filtrés par l'allowlist de modèles). ---
    family = apis.family_for_path(path)
    if rec.apis and path not in _LISTING_PATHS and (family is None or family not in set(rec.apis)):
        _log(rec.id, ip, method, path, req_model, 403, t0, bytes_in=len(body))
        _content_log(403, req_model)
        return JSONResponse(
            {"error": f"API non autorisée pour cette clé: {family or path}"}, status_code=403)

    keys.touch_last_used(rec.id)

    # --- Relais amont (streaming) vers l'URL absolue du serveur rattaché ---
    fwd_headers = [(k, v) for k, v in request.headers.raw
                   if k.decode("latin-1").lower() not in _DROP_REQ_HEADERS]
    fwd_headers += [(k.encode("latin-1"), v.encode("latin-1")) for k, v in srv_auth.items()]
    url = httpx.URL(srv.base_url.rstrip("/") + path)
    if request.url.query:
        url = url.copy_with(query=request.url.query.encode("utf-8"))
    upstream: httpx.AsyncClient = request.app.state.upstream
    up_req = upstream.build_request(method, url, headers=fwd_headers, content=body)

    # Listing de modèles pour une clé restreinte : bufferiser + filtrer (petites réponses).
    if path in _LISTING_PATHS and rec.models:
        try:
            up_resp = await upstream.send(up_req)
        except httpx.HTTPError as exc:
            _log(rec.id, ip, method, path, req_model, 502, t0, bytes_in=len(body))
            _content_log(502, req_model)
            return JSONResponse({"error": f"upstream indisponible: {exc.__class__.__name__}"},
                                status_code=502)
        content = up_resp.content
        if up_resp.status_code == 200:
            content = _filter_models(content, set(rec.models))
        _log(rec.id, ip, method, path, "", up_resp.status_code, t0,
             bytes_in=len(body), bytes_out=len(content))
        _content_log(up_resp.status_code, req_model)
        media = up_resp.headers.get("content-type", "application/json")
        return Response(content, status_code=up_resp.status_code, media_type=media)

    try:
        up_resp = await upstream.send(up_req, stream=True)
    except httpx.HTTPError as exc:
        _log(rec.id, ip, method, path, req_model, 502, t0, bytes_in=len(body))
        _content_log(502, req_model)
        return JSONResponse({"error": f"upstream indisponible: {exc.__class__.__name__}"},
                            status_code=502)

    sniff = _TokenSniffer()
    sniff.model = req_model
    bytes_out = 0

    async def stream_body():
        nonlocal bytes_out
        try:
            async for chunk in up_resp.aiter_raw():
                bytes_out += len(chunk)
                sniff.feed(chunk)
                yield chunk
        finally:
            sniff.finish()
            await up_resp.aclose()

    def finalize():
        model = sniff.model or _model_from_body(body)
        _log(rec.id, ip, method, path, model, up_resp.status_code, t0,
             tokens_prompt=sniff.tokens_prompt, tokens_completion=sniff.tokens_completion,
             bytes_in=len(body), bytes_out=bytes_out)
        _content_log(up_resp.status_code, model)

    resp_headers = [(k, v) for k, v in up_resp.headers.items()
                    if k.lower() not in _DROP_RESP_HEADERS]
    return StreamingResponse(
        stream_body(), status_code=up_resp.status_code, headers=dict(resp_headers),
        background=BackgroundTask(finalize),
    )
