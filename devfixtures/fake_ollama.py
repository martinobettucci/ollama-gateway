"""Faux upstream Ollama pour le mode dev self-contained (aucun GPU, aucune vraie box requise).

Imite juste ce dont la passerelle a besoin : /api/chat, /api/generate (NDJSON stream + compteurs
de tokens), /api/tags, /api/embed, et la racine. Déterministe → tests E2E reproductibles.
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_CHUNKS = ["Bonjour", ", ", "ceci ", "est ", "un ", "faux ", "modèle."]

# Derniers en-têtes porteurs de clé vus (les tests vérifient que le proxy les strip avant l'amont).
LAST_AUTH: str | None = "unset"
LAST_XAPIKEY: str | None = "unset"


@app.get("/")
async def root() -> PlainTextResponse:
    return PlainTextResponse("Ollama is running")


# PNG 1×1 transparent (base64) — image de test déterministe renvoyée par les endpoints d'image.
_TINY_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
             "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


# Catalogue MUTABLE : /api/pull y ajoute un modèle, /api/delete l'en retire → la gestion de
# modèles du panel (LAN-only) est testable de bout en bout de façon déterministe.
_DEFAULT_MODELS = ["demo:latest", "autre:latest", "x/fakeflux:1b"]
MODELS: list[str] = list(_DEFAULT_MODELS)


def reset_models() -> None:
    """Réinitialise le catalogue (isolation inter-tests)."""
    MODELS[:] = list(_DEFAULT_MODELS)


@app.get("/api/tags")
async def tags() -> JSONResponse:
    # Modèles texte + un modèle d'IMAGE (préfixe x/) → teste le filtrage et la séparation image.
    return JSONResponse({"models": [{"name": m, "model": m} for m in MODELS]})


@app.post("/api/pull")
async def pull(request: Request) -> JSONResponse:
    # Ajoute le modèle au catalogue (idempotent) et répond comme Ollama (stream=false).
    body = await request.json()
    model = (body.get("model") or body.get("name") or "").strip()
    if not model:
        return JSONResponse({"error": "model is required"}, status_code=400)
    if model not in MODELS:
        MODELS.append(model)
    return JSONResponse({"status": "success"})


@app.delete("/api/delete")
async def delete(request: Request) -> JSONResponse:
    # Retire le modèle ; 404 s'il est déjà absent (comportement Ollama).
    body = await request.json()
    model = (body.get("model") or body.get("name") or "").strip()
    if model not in MODELS:
        return JSONResponse({"error": "model not found"}, status_code=404)
    MODELS.remove(model)
    return JSONResponse({"status": "success"})


@app.get("/v1/models")
async def openai_models() -> JSONResponse:
    # Forme OpenAI/Anthropic : {"object":"list","data":[{"id":…}]}.
    return JSONResponse({"object": "list", "data": [
        {"id": "demo:latest", "object": "model"},
        {"id": "autre:latest", "object": "model"},
    ]})


@app.post("/v1/images/generations")
async def openai_images(request: Request):
    # OpenAI-compat : {"created":…, "data":[{"b64_json":…}]}.
    body = await request.json()
    return JSONResponse({"created": 1783000000, "data": [
        {"b64_json": _TINY_PNG}], "model": body.get("model", "x/fakeflux:1b")})


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    # OpenAI Chat Completions : modèle à la racine du corps (même gating que /api/chat).
    global LAST_AUTH, LAST_XAPIKEY
    LAST_AUTH = request.headers.get("authorization")
    LAST_XAPIKEY = request.headers.get("x-api-key")
    body = await request.json()
    model = body.get("model", "demo:latest")
    return JSONResponse({
        "id": "chatcmpl-demo", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(_CHUNKS)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": len(_CHUNKS), "total_tokens": 18},
    })


@app.post("/v1/responses")
async def openai_responses(request: Request):
    # OpenAI Responses API : entrée `input`, sortie `output[].content[].text` (+ `output_text`).
    global LAST_AUTH, LAST_XAPIKEY
    LAST_AUTH = request.headers.get("authorization")
    LAST_XAPIKEY = request.headers.get("x-api-key")
    body = await request.json()
    model = body.get("model", "demo:latest")
    full = "".join(_CHUNKS)
    return JSONResponse({
        "id": "resp-demo", "object": "response", "model": model, "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": full}]}],
        "output_text": full,
        "usage": {"input_tokens": 11, "output_tokens": len(_CHUNKS)},
    })


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    # Anthropic Messages API : sortie `content[].text` ; modèle à la racine (même gating).
    global LAST_AUTH, LAST_XAPIKEY
    LAST_AUTH = request.headers.get("authorization")
    LAST_XAPIKEY = request.headers.get("x-api-key")
    body = await request.json()
    model = body.get("model", "demo:latest")
    return JSONResponse({
        "id": "msg-demo", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": "".join(_CHUNKS)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": len(_CHUNKS)},
    })


@app.post("/api/embed")
async def embed(request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse({"model": body.get("model", "demo-embed"),
                         "embeddings": [[0.01, 0.02, 0.03, 0.04]]})


async def _ndjson_stream(model: str):
    for c in _CHUNKS:
        yield json.dumps({"model": model, "created_at": "2026-01-01T00:00:00Z",
                          "message": {"role": "assistant", "content": c},
                          "done": False}).encode() + b"\n"
    yield json.dumps({"model": model, "done": True, "done_reason": "stop",
                      "prompt_eval_count": 11, "eval_count": len(_CHUNKS)}).encode() + b"\n"


@app.post("/api/chat")
async def chat(request: Request):
    global LAST_AUTH, LAST_XAPIKEY
    LAST_AUTH = request.headers.get("authorization")
    LAST_XAPIKEY = request.headers.get("x-api-key")
    # Simulation d'erreur serveur pour tester le repli : Host contenant « fail » → 500.
    if "fail" in (request.headers.get("host", "")):
        return JSONResponse({"error": "boom"}, status_code=500)
    body = await request.json()
    model = body.get("model", "demo:latest")
    if body.get("stream", True):
        return StreamingResponse(_ndjson_stream(model), media_type="application/x-ndjson")
    full = "".join(_CHUNKS)
    return JSONResponse({"model": model, "done": True,
                         "message": {"role": "assistant", "content": full},
                         "prompt_eval_count": 11, "eval_count": len(_CHUNKS)})


@app.post("/api/generate")
async def generate(request: Request):
    body = await request.json()
    model = body.get("model", "demo:latest")
    # Modèle d'IMAGE (x/…) : réponse non-stream avec `image` (base64 PNG), comme Ollama.
    if str(model).startswith("x/"):
        return JSONResponse({"model": model, "created_at": "2026-01-01T00:00:00Z",
                             "done": True, "done_reason": "stop", "image": _TINY_PNG})
    if body.get("stream", True):
        async def gen():
            for c in _CHUNKS:
                yield json.dumps({"model": model, "response": c, "done": False}).encode() + b"\n"
            yield json.dumps({"model": model, "response": "", "done": True,
                              "prompt_eval_count": 11, "eval_count": len(_CHUNKS)}).encode() + b"\n"
        return StreamingResponse(gen(), media_type="application/x-ndjson")
    return JSONResponse({"model": model, "response": "".join(_CHUNKS), "done": True,
                         "prompt_eval_count": 11, "eval_count": len(_CHUNKS)})


# --- Capteur de webhook (tests E2E de la livraison déclarative) --------------------------------
# Enregistre la DERNIÈRE charge utile POSTée sur /webhook ; /webhook/last la restitue au test.
LAST_WEBHOOK: dict | None = None


@app.post("/webhook")
async def webhook_sink(request: Request):
    global LAST_WEBHOOK
    raw = (await request.body()).decode("utf-8", "replace")
    LAST_WEBHOOK = {"headers": dict(request.headers), "body": raw}
    return JSONResponse({"ok": True})


@app.get("/webhook/last")
async def webhook_last() -> JSONResponse:
    return JSONResponse(LAST_WEBHOOK or {})
