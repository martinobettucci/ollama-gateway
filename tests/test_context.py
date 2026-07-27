"""Limite de contexte par clé (app/context.py) : validation/normalisation, comptage de tokens
multi-API, marge de 15 %, injection de `num_ctx`, et application par le proxy (413 avant l'amont)."""
import json

import pytest

from app import context, keys, servers
from tests.conftest import fake_upstream, proxy_client  # noqa: F401 (fixtures)


# --- Validation / normalisation ---------------------------------------------------------------

def test_default_is_112k_and_valid():
    assert context.CONTEXT_DEFAULT == 114688 == 112 * 1024
    assert context.is_valid(context.CONTEXT_DEFAULT)
    assert context.label(context.CONTEXT_DEFAULT) == "112k"


def test_is_valid_bounds_and_multiple():
    assert context.is_valid(4096) and context.is_valid(1024 * 1024)
    assert not context.is_valid(0)
    assert not context.is_valid(2048)             # sous la borne basse
    assert not context.is_valid(1024 * 1024 + 4096)  # au-dessus de 1M
    assert not context.is_valid(5000)             # non multiple de 4096
    assert not context.is_valid(True)             # bool n'est pas un entier valide


@pytest.mark.parametrize("raw,expected", [
    (None, context.CONTEXT_DEFAULT),      # jamais vide → défaut
    ("", context.CONTEXT_DEFAULT),
    ("bogus", context.CONTEXT_DEFAULT),
    (114688, 114688),
    ("114688", 114688),
    ("112k", 114688),
    ("112", 114688),                      # saisie en « k » sans suffixe
    ("1m", 1024 * 1024),
    (5000, 8192),                         # non aligné → multiple de 4k SUPÉRIEUR
    (100, 102400),                        # 100k (aligné : 25 × 4k)
    (10, 12288),                          # 10k = 10240 → arrondi au 4k supérieur
    (1, 4096),                            # sous la borne → bornée à 4k
    (99_999_999, 1024 * 1024),            # au-dessus → bornée à 1M
])
def test_normalize(raw, expected):
    got = context.normalize(raw)
    assert got == expected and context.is_valid(got)


def test_choices_all_valid_and_contains_default():
    ch = context.choices()
    assert context.CONTEXT_DEFAULT in ch
    assert all(context.is_valid(v) for v in ch)


# --- Comptage de tokens (multi-API) -----------------------------------------------------------

def test_count_tokens_empty_or_invalid():
    assert context.count_tokens(b"") == 0
    assert context.count_tokens(b"pas du json") == 0
    assert context.count_tokens(json.dumps({"model": "m"}).encode()) == 0  # aucun texte


def test_count_tokens_ollama_chat_and_generate():
    chat = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": "Bonjour, comment allez-vous aujourd'hui ?"}]}).encode()
    gen = json.dumps({"model": "m", "prompt": "Bonjour, comment allez-vous aujourd'hui ?"}).encode()
    assert context.count_tokens(chat) > 3
    assert context.count_tokens(gen) > 3


def test_count_tokens_openai_parts_and_anthropic_system():
    openai = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "un texte de test un peu long"}]}]})
    anthropic = json.dumps({"model": "m", "system": "tu es un assistant",
                            "messages": [{"role": "user", "content": "bonjour"}]})
    assert context.count_tokens(openai.encode()) > 3
    assert context.count_tokens(anthropic.encode()) > 3


def test_count_tokens_ignores_base64_images():
    """Une image base64 ne doit pas être comptée comme du texte (fausserait totalement l'estimation)."""
    huge_b64 = "A" * 200_000
    with_img = json.dumps({"model": "m", "prompt": "décris cette image",
                           "images": [huge_b64]}).encode()
    without = json.dumps({"model": "m", "prompt": "décris cette image"}).encode()
    assert context.count_tokens(with_img) == context.count_tokens(without)


def test_count_tokens_scales_with_text():
    small = json.dumps({"prompt": "mot " * 10}).encode()
    big = json.dumps({"prompt": "mot " * 1000}).encode()
    assert context.count_tokens(big) > context.count_tokens(small) * 50


def test_with_margin_is_15_percent():
    assert context.with_margin(1000) == 1150
    assert context.with_margin(0) == 0


def test_exceeds_uses_margin():
    body = json.dumps({"prompt": "mot " * 5000}).encode()
    tokens = context.count_tokens(body)
    billed = context.with_margin(tokens)
    # Juste au-dessus de l'estimation MAJORÉE → refusé ; bien au-dessus → accepté.
    over, est, b = context.exceeds(body, billed - 1)
    assert over and est == tokens and b == billed
    assert not context.exceeds(body, billed + 1)[0]


# --- Injection de num_ctx ---------------------------------------------------------------------

def test_inject_num_ctx_on_ollama_paths():
    body = json.dumps({"model": "m", "prompt": "salut"}).encode()
    out = json.loads(context.inject_num_ctx(body, "/api/generate", 114688))
    assert out["options"]["num_ctx"] == 114688
    assert out["prompt"] == "salut"           # reste du corps préservé


def test_inject_num_ctx_keeps_smaller_client_value():
    """La limite est un PLAFOND : un client demandant moins garde sa valeur."""
    body = json.dumps({"model": "m", "prompt": "x", "options": {"num_ctx": 8192,
                                                               "temperature": 0.5}}).encode()
    out = json.loads(context.inject_num_ctx(body, "/api/chat", 114688))
    assert out["options"]["num_ctx"] == 8192
    assert out["options"]["temperature"] == 0.5   # autres options préservées


def test_inject_num_ctx_caps_larger_client_value():
    body = json.dumps({"model": "m", "prompt": "x", "options": {"num_ctx": 262144}}).encode()
    out = json.loads(context.inject_num_ctx(body, "/api/chat", 114688))
    assert out["options"]["num_ctx"] == 114688     # rabaissé au plafond de la clé


def test_inject_num_ctx_untouched_on_non_ollama_paths():
    body = json.dumps({"model": "m", "messages": []}).encode()
    assert context.inject_num_ctx(body, "/v1/chat/completions", 114688) == body
    assert context.inject_num_ctx(body, "/v1/messages", 114688) == body
    assert not context.supports_num_ctx("/v1/chat/completions")
    assert context.supports_num_ctx("/api/chat")


# --- Application par le proxy -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_proxy_refuses_oversized_context_before_upstream(fake_upstream):  # noqa: F811
    """Une requête au-dessus du plafond est refusée 413 SANS jamais atteindre l'amont."""
    from devfixtures import fake_ollama
    servers.ensure_default()
    _rec, secret = keys.create_key("ctx", [], None, None, max_context_tokens=4096)
    fake_ollama.LAST_AUTH = "unset"
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={"Authorization": f"Bearer {secret}"},
                         json={"model": "demo:latest", "messages": [
                             {"role": "user", "content": "mot " * 5000}]})
    assert r.status_code == 413
    payload = r.json()
    assert payload["max_context_tokens"] == 4096
    assert payload["tokens_with_margin"] > 4096
    # L'amont n'a JAMAIS été appelé (aucune requête reçue par le faux Ollama).
    assert fake_ollama.LAST_AUTH == "unset"


@pytest.mark.asyncio
async def test_proxy_injects_num_ctx_upstream(fake_upstream):  # noqa: F811
    """Une requête admise part à l'amont avec `options.num_ctx` = plafond de la clé."""
    from devfixtures import fake_ollama
    servers.ensure_default()
    _rec, secret = keys.create_key("ctx-ok", [], None, None, max_context_tokens=8192)
    fake_ollama.LAST_BODY = None
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={"Authorization": f"Bearer {secret}"},
                         json={"model": "demo:latest",
                               "messages": [{"role": "user", "content": "bonjour"}]})
    assert r.status_code == 200
    assert fake_ollama.LAST_BODY is not None
    assert fake_ollama.LAST_BODY.get("options", {}).get("num_ctx") == 8192


@pytest.mark.asyncio
async def test_proxy_allows_normal_request_with_default_limit(fake_upstream):  # noqa: F811
    servers.ensure_default()
    _rec, secret = keys.create_key("ctx-def", [], None, None)
    assert keys.get_key(_rec.id).max_context_tokens == context.CONTEXT_DEFAULT
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers={"Authorization": f"Bearer {secret}"},
                         json={"model": "demo:latest",
                               "messages": [{"role": "user", "content": "bonjour"}]})
    assert r.status_code == 200
