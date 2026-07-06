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
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask

from . import auth, config, db, keys, quotas, usage

# En-têtes hop-by-hop / recalculés à ne pas recopier tels quels.
_DROP_REQ_HEADERS = {"host", "authorization", "content-length", "connection",
                     "proxy-connection", "keep-alive", "transfer-encoding", "upgrade"}
_DROP_RESP_HEADERS = {"content-length", "transfer-encoding", "connection", "keep-alive"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    app.state.upstream = httpx.AsyncClient(
        base_url=config.OLLAMA_UPSTREAM,
        timeout=httpx.Timeout(config.UPSTREAM_TIMEOUT_S, connect=15.0),
    )
    try:
        yield
    finally:
        await app.state.upstream.aclose()


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

    if not path.startswith(config.ALLOWED_PATH_PREFIXES):
        return JSONResponse({"error": "not found"}, status_code=404)

    # --- Authentification par clé Bearer ---
    key = auth.extract_bearer(request.headers.get("authorization"))
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

    # --- Quotas ---
    conn = db.connect()
    try:
        ok, reason = quotas.check(rec, conn)
    finally:
        conn.close()
    if not ok:
        _log(rec.id, ip, method, path, "", 429, t0)
        return JSONResponse({"error": reason}, status_code=429)

    keys.touch_last_used(rec.id)

    # --- Relais amont (streaming) ---
    body = await request.body()
    fwd_headers = [(k, v) for k, v in request.headers.raw
                   if k.decode("latin-1").lower() not in _DROP_REQ_HEADERS]
    url = httpx.URL(path=path, query=request.url.query.encode("utf-8"))
    upstream: httpx.AsyncClient = request.app.state.upstream
    up_req = upstream.build_request(method, url, headers=fwd_headers, content=body)

    try:
        up_resp = await upstream.send(up_req, stream=True)
    except httpx.HTTPError as exc:
        _log(rec.id, ip, method, path, _model_from_body(body), 502, t0, bytes_in=len(body))
        return JSONResponse({"error": f"upstream indisponible: {exc.__class__.__name__}"},
                            status_code=502)

    sniff = _TokenSniffer()
    sniff.model = _model_from_body(body)
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
        _log(rec.id, ip, method, path, sniff.model or _model_from_body(body),
             up_resp.status_code, t0, tokens_prompt=sniff.tokens_prompt,
             tokens_completion=sniff.tokens_completion, bytes_in=len(body), bytes_out=bytes_out)

    resp_headers = [(k, v) for k, v in up_resp.headers.items()
                    if k.lower() not in _DROP_RESP_HEADERS]
    return StreamingResponse(
        stream_body(), status_code=up_resp.status_code, headers=dict(resp_headers),
        background=BackgroundTask(finalize),
    )
