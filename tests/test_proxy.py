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
