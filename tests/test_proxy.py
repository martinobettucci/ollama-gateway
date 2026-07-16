"""Tests d'intégration du proxy : auth, origine, quota, streaming, comptage tokens, strip clé."""
from app import db, keys
from devfixtures import fake_ollama
from tests.conftest import proxy_client


def _auth(key):
    return {"authorization": f"Bearer {key}"}


def _usage_rows():
    conn = db.connect()
    try:
        return conn.execute("SELECT * FROM usage_events ORDER BY id").fetchall()
    finally:
        conn.close()


async def test_missing_key_401(fake_upstream):
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", json={"model": "demo:latest"})
    assert r.status_code == 401


async def test_invalid_key_401(fake_upstream):
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth("sk-ollama-nope"), json={})
    assert r.status_code == 401


async def test_disabled_key_401(fake_upstream):
    rec, key = keys.create_key("x", [], None, None)
    keys.set_enabled(rec.id, False)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={})
    assert r.status_code == 401


async def test_origin_denied_403(fake_upstream):
    _, key = keys.create_key("x", ["10.0.0.0/8"], None, None)
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat", headers=_auth(key), json={})
    assert r.status_code == 403


async def test_origin_allowed_passes(fake_upstream):
    _, key = keys.create_key("x", ["203.0.113.0/24"], None, None)
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_api_allowlist_empty_allows_all(fake_upstream):
    _, key = keys.create_key("x", [], None, None)  # aucune API restreinte = toutes
    async with proxy_client(fake_upstream) as c:
        r1 = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
        r2 = await c.post("/v1/chat/completions", headers=_auth(key),
                          json={"model": "demo:latest"})
    assert r1.status_code == 200 and r2.status_code == 200


async def test_api_allowlist_forbids_other_family(fake_upstream):
    _, key = keys.create_key("x", [], None, None, key_apis=["ollama"])
    async with proxy_client(fake_upstream) as c:
        ok = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
        openai = await c.post("/v1/chat/completions", headers=_auth(key),
                              json={"model": "demo:latest"})
        anthropic = await c.post("/v1/messages", headers=_auth(key),
                                 json={"model": "demo:latest"})
    assert ok.status_code == 200
    assert openai.status_code == 403 and anthropic.status_code == 403


async def test_api_allowlist_listing_paths_always_served(fake_upstream):
    # Une clé restreinte à Anthropic doit tout de même pouvoir lister les modèles OpenAI.
    _, key = keys.create_key("x", [], None, None, key_apis=["anthropic"])
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/v1/models", headers=_auth(key))
    assert r.status_code == 200


async def test_streaming_chat_ok_and_strips_authorization(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key),
                         json={"model": "demo:latest", "stream": True})
    assert r.status_code == 200
    # streaming intégral : premier chunk de contenu + chunk final `done` traversés
    assert "Bonjour" in r.text and '"eval_count": 7' in r.text
    # la clé cliente ne doit JAMAIS atteindre l'upstream
    assert fake_ollama.LAST_AUTH is None


async def test_x_api_key_auth_ok_and_stripped(fake_upstream):
    """SDK Anthropic (ANTHROPIC_API_KEY → en-tête x-api-key) : la clé authentifie comme un
    Bearer et n'atteint JAMAIS l'amont."""
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/v1/chat/completions", headers={"x-api-key": key},
                         json={"model": "demo:latest"})
    assert r.status_code == 200
    assert fake_ollama.LAST_AUTH is None and fake_ollama.LAST_XAPIKEY is None


async def test_x_api_key_invalid_401(fake_upstream):
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/v1/chat/completions", headers={"x-api-key": "sk-ollama-nope"},
                         json={"model": "demo:latest"})
    assert r.status_code == 401


async def test_usage_recorded_with_tokens(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        await c.post("/api/chat", headers=_auth(key),
                     json={"model": "demo:latest", "stream": True})
    rows = _usage_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == 200 and row["model"] == "demo:latest"
    assert row["tokens_prompt"] == 11 and row["tokens_completion"] == 7
    assert row["bytes_out"] > 0


async def test_all_endpoints_proxied(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        tags = await c.get("/api/tags", headers=_auth(key))
        emb = await c.post("/api/embed", headers=_auth(key),
                           json={"model": "demo-embed", "input": "hi"})
    assert tags.status_code == 200 and "demo:latest" in tags.text
    assert emb.status_code == 200 and "embeddings" in emb.text


async def test_disallowed_path_404(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/admin", headers=_auth(key))
    assert r.status_code == 404


async def test_rpm_quota_429(fake_upstream):
    _, key = keys.create_key("x", [], monthly_token_cap=None, rpm_limit=1)
    async with proxy_client(fake_upstream) as c:
        first = await c.post("/api/chat", headers=_auth(key),
                             json={"model": "demo:latest"})
        second = await c.post("/api/chat", headers=_auth(key),
                              json={"model": "demo:latest"})
    assert first.status_code == 200 and second.status_code == 429


async def test_monthly_cap_429(fake_upstream):
    _, key = keys.create_key("x", [], monthly_token_cap=5, rpm_limit=None)
    async with proxy_client(fake_upstream) as c:
        first = await c.post("/api/chat", headers=_auth(key),
                             json={"model": "demo:latest"})
        second = await c.post("/api/chat", headers=_auth(key),
                              json={"model": "demo:latest"})
    assert first.status_code == 200 and second.status_code == 429


async def test_health_no_auth(fake_upstream):
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/_proxy_health")
    assert r.status_code == 200 and r.text.strip() == "ok"


# --- Restriction de modèle (agnostique de l'API) + filtrage des listings ----------------------

async def test_model_restriction_ollama_chat(fake_upstream):
    _, key = keys.create_key("x", [], None, None, models=["demo:latest"])
    async with proxy_client(fake_upstream) as c:
        blocked = await c.post("/api/chat", headers=_auth(key),
                               json={"model": "autre:latest"})
        allowed = await c.post("/api/chat", headers=_auth(key),
                               json={"model": "demo:latest"})
    assert blocked.status_code == 403 and "non autorisé" in blocked.text
    assert allowed.status_code == 200


async def test_model_restriction_openai_chat_completions(fake_upstream):
    # Même gating quel que soit l'API : OpenAI met aussi `model` à la racine du corps.
    _, key = keys.create_key("x", [], None, None, models=["demo:latest"])
    async with proxy_client(fake_upstream) as c:
        blocked = await c.post("/v1/chat/completions", headers=_auth(key),
                               json={"model": "autre:latest", "messages": []})
        allowed = await c.post("/v1/chat/completions", headers=_auth(key),
                               json={"model": "demo:latest", "messages": []})
    assert blocked.status_code == 403
    assert allowed.status_code == 200 and "chat.completion" in allowed.text


async def test_no_restriction_allows_any_model(fake_upstream):
    _, key = keys.create_key("x", [], None, None)  # allowlist vide = tous
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "autre:latest"})
    assert r.status_code == 200


async def test_tags_listing_filtered_for_restricted_key(fake_upstream):
    _, key = keys.create_key("x", [], None, None, models=["demo:latest"])
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/api/tags", headers=_auth(key))
    assert r.status_code == 200
    body = r.json()
    names = {m.get("name") for m in body["models"]}
    assert names == {"demo:latest"}  # 'autre:latest' filtré


async def test_v1_models_listing_filtered_for_restricted_key(fake_upstream):
    _, key = keys.create_key("x", [], None, None, models=["demo:latest"])
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/v1/models", headers=_auth(key))
    assert r.status_code == 200
    ids = {m.get("id") for m in r.json()["data"]}
    assert ids == {"demo:latest"}


async def test_unrestricted_key_sees_all_models(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.get("/api/tags", headers=_auth(key))
    names = {m.get("name") for m in r.json()["models"]}
    assert names == {"demo:latest", "autre:latest", "x/fakeflux:1b"}


async def test_disabled_server_returns_503(fake_upstream):
    from app import servers
    srv = servers.create_server("hors-ligne", "http://unused:11434")
    _, key = keys.create_key("x", [], None, None, server_id=srv.id)
    servers.set_enabled(srv.id, False)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert r.status_code == 503 and "serveur d'exécution" in r.text


# --- Résistance à l'usurpation de X-Forwarded-For (sécurité) ----------------------------------

async def test_xff_spoof_does_not_bypass_origin_allowlist(fake_upstream):
    """Un client externe forge `X-Forwarded-For: <IP-autorisée>` ; Caddy (pair de confiance) ajoute
    l'IP RÉELLE à droite. Le proxy doit retenir l'IP réelle (droite), pas l'IP forgée (gauche)."""
    _, key = keys.create_key("x", ["203.0.113.0/24"], None, None)
    # Pair = 127.0.0.1 (Caddy, de confiance). Chaîne telle que Caddy la produit : forgée, réelle.
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat", headers={**_auth(key),
                                               "x-forwarded-for": "203.0.113.9, 9.9.9.9"},
                         json={"model": "demo:latest"})
    assert r.status_code == 403  # l'IP réelle 9.9.9.9 n'est pas dans l'allowlist


async def test_xff_legit_client_ip_from_trusted_proxy(fake_upstream):
    """XFF légitime (Caddy n'a ajouté que l'IP réelle) : l'origine autorisée passe."""
    _, key = keys.create_key("x", ["203.0.113.0/24"], None, None)
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat", headers={**_auth(key),
                                               "x-forwarded-for": "203.0.113.9"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200


async def test_xff_ignored_from_untrusted_peer(fake_upstream):
    """Un pair NON de confiance ne peut pas injecter d'IP via XFF : c'est l'IP du pair qui compte."""
    _, key = keys.create_key("x", ["203.0.113.0/24"], None, None)
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat", headers={**_auth(key), "x-forwarded-for": "10.0.0.1"},
                         json={"model": "demo:latest"})
    assert r.status_code == 200  # XFF ignoré (pair non de confiance) → IP du pair, autorisée


async def test_xff_spoof_does_not_bypass_ban(fake_upstream):
    """Une origine bannie ne peut pas s'échapper en forgeant une IP non bannie à gauche du XFF."""
    from app import bans
    bans.add_ban("9.9.9.9")
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream, source_ip="127.0.0.1") as c:
        r = await c.post("/api/chat", headers={**_auth(key),
                                               "x-forwarded-for": "1.2.3.4, 9.9.9.9"},
                         json={"model": "demo:latest"})
    assert r.status_code == 403 and "bannie" in r.text  # IP réelle 9.9.9.9 bannie


async def test_forwards_server_auth_token_to_upstream(fake_upstream):
    # Un serveur avec jeton : le proxy l'injecte vers l'amont (déchiffré), la clé cliente reste strippée.
    from app import servers
    srv = servers.create_server("distant", "http://remote:11434", auth_token="up-secret")
    _, key = keys.create_key("x", [], None, None, server_id=srv.id)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert r.status_code == 200
    assert fake_ollama.LAST_AUTH == "Bearer up-secret"
