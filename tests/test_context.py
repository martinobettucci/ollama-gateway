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


def test_ladder_is_the_allowed_set():
    """L'échelle de paliers EST l'ensemble des valeurs autorisées (2k → 1M, 112k inclus)."""
    assert context.CONTEXT_SIZES_K == (2, 4, 8, 12, 24, 36, 48, 64, 72, 96, 108, 112, 128,
                                       144, 180, 224, 256, 384, 512, 640, 768, 1024)
    assert context.CONTEXT_MIN == 2 * 1024 and context.CONTEXT_MAX == 1024 * 1024
    assert list(context.CONTEXT_SIZES) == sorted(context.CONTEXT_SIZES)  # croissante
    assert all(context.is_valid(v) for v in context.CONTEXT_SIZES)


def test_is_valid_only_on_ladder():
    assert context.is_valid(2048) and context.is_valid(1024 * 1024)
    assert not context.is_valid(0)
    assert not context.is_valid(1024)             # sous le premier palier
    assert not context.is_valid(1024 * 1024 + 4096)  # au-dessus du dernier
    assert not context.is_valid(5000)             # hors échelle
    assert not context.is_valid(16384)            # 16k n'est PAS un palier de l'échelle
    assert not context.is_valid(True)             # bool n'est pas un entier valide


@pytest.mark.parametrize("tokens,expected_k", [
    (0, 2), (1, 2), (2048, 2),           # tout ce qui tient dans 2k → 2k
    (2049, 4), (2096, 4), (4096, 4),     # 2 096 tokens → 4k (exemple de la spec)
    (4097, 8),
    (24576, 24), (24577, 36),            # ne tient plus dans 24k → 36k
    (27734, 36),                         # 27 734 tokens → 36k (exemple de la spec)
    (110592, 108),                       # pile 108k → tient dans 108k
    (110593, 112), (114688, 112),        # 108k < n ≤ 112k → 112k
    (114689, 128),                       # au-delà de 112k → 128k
    (1024 * 1024, 1024),
    (99_999_999, 1024),                  # au-delà du dernier palier → plafonné à 1M
])
def test_bucket_is_lowest_fitting_size(tokens, expected_k):
    assert context.bucket(tokens) == expected_k * 1024


def test_bucket_always_on_ladder():
    for n in (0, 1, 3000, 50_000, 200_000, 900_000, 5_000_000):
        assert context.bucket(n) in context.CONTEXT_SIZES


@pytest.mark.parametrize("raw,expected", [
    (None, context.CONTEXT_DEFAULT),      # jamais vide → défaut
    ("", context.CONTEXT_DEFAULT),
    ("bogus", context.CONTEXT_DEFAULT),
    (114688, 114688),
    ("114688", 114688),
    ("112k", 114688),
    ("112", 114688),                      # saisie en « k » sans suffixe
    ("1m", 1024 * 1024),
    (5000, 8192),                         # hors palier → palier supérieur (8k)
    (100, 110592),                        # 100k ne tient pas dans 96k → palier 108k
    (10, 12288),                          # 10k = 10240 → palier supérieur (12k)
    (1, 2048),                            # sous le premier palier → 2k
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


# --- Statistique des paliers réellement utilisés ----------------------------------------------

@pytest.mark.asyncio
async def test_usage_records_ctx_bucket_per_key_and_server(fake_upstream):  # noqa: F811
    """Chaque requête est classée dans le plus petit palier qui la contient ; l'agrégat par clé et
    par serveur compte les usages et retient le DERNIER usage de chaque palier."""
    from app import usage
    sid = servers.ensure_default()
    _rec, secret = keys.create_key("stats", [], None, None)
    kid = _rec.id
    async with proxy_client(fake_upstream) as c:
        for content in ("bonjour", "mot " * 3000, "mot " * 3000):
            await c.post("/api/chat", headers={"Authorization": f"Bearer {secret}"},
                         json={"model": "demo:latest",
                               "messages": [{"role": "user", "content": content}]})
    by_key = usage.key_ctx_buckets(kid)
    assert by_key, "au moins un palier enregistré"
    assert all(b["bucket"] in context.CONTEXT_SIZES for b in by_key)
    assert all(b["last_seen"] for b in by_key)              # dernier usage suivi
    assert sum(b["reqs"] for b in by_key) == 3              # 3 requêtes classées
    # (Le faux amont renvoie des compteurs FIXES : les 3 requêtes tombent donc dans le même
    #  palier — c'est le comportement attendu, le réel prime sur l'estimation d'entrée.)
    # Même agrégat côté serveur.
    by_srv = usage.server_ctx_buckets(sid)
    assert sum(b["reqs"] for b in by_srv) == 3


def test_ctx_buckets_aggregate_counts_and_last_usage():
    """Agrégat multi-paliers : compte par palier, dernier usage, tri du plus grand au plus petit."""
    from app import usage
    sid = servers.ensure_default()
    rec, _s = keys.create_key("agg", [], None, None)
    for bucket_size, n in ((4096, 3), (24576, 1), (114688, 2)):
        for _ in range(n):
            usage.record(key_id=rec.id, client_ip="1.2.3.4", method="POST", path="/api/chat",
                         model="m", status=200, duration_ms=5, tokens_prompt=10,
                         server_id=sid, ctx_bucket=bucket_size)
    rows = usage.key_ctx_buckets(rec.id)
    assert [r["bucket"] for r in rows] == [114688, 24576, 4096]     # décroissant
    assert {r["bucket"]: r["reqs"] for r in rows} == {4096: 3, 24576: 1, 114688: 2}
    assert all(r["last_seen"] and r["first_seen"] for r in rows)
    assert {r["bucket"]: r["reqs"] for r in usage.server_ctx_buckets(sid)} == {
        4096: 3, 24576: 1, 114688: 2}


@pytest.mark.asyncio
async def test_ctx_bucket_uses_real_upstream_tokens(fake_upstream):  # noqa: F811
    """Le palier est affiné avec les compteurs RÉELS de l'amont quand ils sont disponibles."""
    from app import db, usage
    servers.ensure_default()
    _rec, secret = keys.create_key("real", [], None, None)
    async with proxy_client(fake_upstream) as c:
        await c.post("/api/chat", headers={"Authorization": f"Bearer {secret}"},
                     json={"model": "demo:latest", "stream": True,
                           "messages": [{"role": "user", "content": "bonjour"}]})
    conn = db.connect()
    row = conn.execute(
        "SELECT tokens_prompt, tokens_completion, ctx_bucket FROM usage_events "
        "WHERE key_id = ? ORDER BY id DESC LIMIT 1", (_rec.id,)).fetchone()
    conn.close()
    real = row["tokens_prompt"] + row["tokens_completion"]
    assert real > 0                                        # le faux amont renvoie des compteurs
    assert row["ctx_bucket"] == context.bucket(real)
    assert usage.key_ctx_buckets(_rec.id)[0]["bucket"] == context.bucket(real)


def test_ctx_buckets_exclude_unmeasured_events():
    """Les événements sans palier (refus avant lecture du corps) sont hors agrégat."""
    from app import db, usage
    servers.ensure_default()
    rec, _s = keys.create_key("nobucket", [], None, None)
    usage.record(key_id=rec.id, client_ip="1.2.3.4", method="POST", path="/api/chat",
                 model="", status=401, duration_ms=1)       # ctx_bucket NULL
    usage.record(key_id=rec.id, client_ip="1.2.3.4", method="POST", path="/api/chat",
                 model="m", status=200, duration_ms=5, ctx_bucket=4096)
    buckets = usage.key_ctx_buckets(rec.id)
    assert len(buckets) == 1 and buckets[0]["bucket"] == 4096 and buckets[0]["reqs"] == 1
    del db
