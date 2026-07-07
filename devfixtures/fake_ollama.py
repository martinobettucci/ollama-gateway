"""Faux upstream Ollama pour le mode dev self-contained (aucun GPU, aucune vraie box requise).

Imite juste ce dont la passerelle a besoin : /api/chat, /api/generate (NDJSON stream + compteurs
de tokens), /api/tags, /api/embed, et la racine. Déterministe → tests E2E reproductibles.
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_CHUNKS = ["Bonjour", ", ", "ceci ", "est ", "un ", "faux ", "modèle."]

# Dernier en-tête Authorization vu (les tests vérifient que le proxy le strip avant l'amont).
LAST_AUTH: str | None = "unset"


@app.get("/")
async def root() -> PlainTextResponse:
    return PlainTextResponse("Ollama is running")


@app.get("/api/tags")
async def tags() -> JSONResponse:
    # Deux modèles → permet de tester le filtrage de listing par l'allowlist d'une clé.
    return JSONResponse({"models": [
        {"name": "demo:latest", "model": "demo:latest"},
        {"name": "autre:latest", "model": "autre:latest"},
    ]})


@app.get("/v1/models")
async def openai_models() -> JSONResponse:
    # Forme OpenAI/Anthropic : {"object":"list","data":[{"id":…}]}.
    return JSONResponse({"object": "list", "data": [
        {"id": "demo:latest", "object": "model"},
        {"id": "autre:latest", "object": "model"},
    ]})


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    # OpenAI Chat Completions : modèle à la racine du corps (même gating que /api/chat).
    global LAST_AUTH
    LAST_AUTH = request.headers.get("authorization")
    body = await request.json()
    model = body.get("model", "demo:latest")
    return JSONResponse({
        "id": "chatcmpl-demo", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(_CHUNKS)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": len(_CHUNKS), "total_tokens": 18},
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
    global LAST_AUTH
    LAST_AUTH = request.headers.get("authorization")
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
    if body.get("stream", True):
        async def gen():
            for c in _CHUNKS:
                yield json.dumps({"model": model, "response": c, "done": False}).encode() + b"\n"
            yield json.dumps({"model": model, "response": "", "done": True,
                              "prompt_eval_count": 11, "eval_count": len(_CHUNKS)}).encode() + b"\n"
        return StreamingResponse(gen(), media_type="application/x-ndjson")
    return JSONResponse({"model": model, "response": "".join(_CHUNKS), "done": True,
                         "prompt_eval_count": 11, "eval_count": len(_CHUNKS)})
