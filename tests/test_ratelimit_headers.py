"""En-têtes d'état de quota (x-ratelimit-*) exposés au client (style OpenAI/Groq).

But : permettre aux clients bien élevés (et surtout aux boucles d'agents) de se rythmer sans
percuter les 429 — lire `remaining`/`reset` et décider d'attendre ou de s'arrêter avant l'appel
qui échouerait, ce qui évite aussi les tempêtes de retry dans les logs.
"""
import pytest

from app import db, keys, quotas, usage
from tests.conftest import proxy_client


def _auth(key):
    return {"authorization": f"Bearer {key}"}


@pytest.fixture(autouse=True)
def reset_inflight():
    quotas._INFLIGHT.clear()
    yield
    quotas._INFLIGHT.clear()


# --- Unitaire : quotas.rate_limit_headers -----------------------------------------------------

def test_headers_rpm_and_tokens_no_usage():
    rec, _ = keys.create_key("x", [], monthly_token_cap=1000, rpm_limit=5)
    r = keys.get_key(rec.id)
    conn = db.connect()
    try:
        h = quotas.rate_limit_headers(r, conn)
    finally:
        conn.close()
    assert h["x-ratelimit-limit-requests"] == "5"
    assert h["x-ratelimit-remaining-requests"] == "4"   # 5 - la requête courante
    assert int(h["x-ratelimit-reset-requests"]) == 0    # aucune requête en fenêtre
    assert h["x-ratelimit-limit-tokens"] == "1000"
    assert h["x-ratelimit-remaining-tokens"] == "1000"
    assert int(h["x-ratelimit-reset-tokens"]) > 0       # secondes jusqu'à la fin du mois


def test_headers_absent_when_unlimited():
    rec, _ = keys.create_key("x", [], None, None)
    r = keys.get_key(rec.id)
    conn = db.connect()
    try:
        assert quotas.rate_limit_headers(r, conn) == {}
    finally:
        conn.close()


def test_headers_reflect_usage():
    rec, _ = keys.create_key("x", [], monthly_token_cap=1000, rpm_limit=5)
    for _ in range(2):
        usage.record(key_id=rec.id, client_ip="1.2.3.4", method="POST", path="/api/chat",
                     model="m", status=200, duration_ms=1, tokens_prompt=100,
                     tokens_completion=50)
    r = keys.get_key(rec.id)
    conn = db.connect()
    try:
        h = quotas.rate_limit_headers(r, conn)
    finally:
        conn.close()
    assert h["x-ratelimit-remaining-requests"] == "2"   # 5 - (2 récentes + courante)
    assert h["x-ratelimit-remaining-tokens"] == "700"   # 1000 - 2×150
    assert int(h["x-ratelimit-reset-requests"]) > 0     # fenêtre non vide


# --- Intégration proxy ------------------------------------------------------------------------

async def test_proxy_success_exposes_headers(fake_upstream):
    _, key = keys.create_key("x", [], monthly_token_cap=100000, rpm_limit=30)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit-requests"] == "30"
    assert r.headers["x-ratelimit-remaining-requests"] == "29"
    assert r.headers["x-ratelimit-limit-tokens"] == "100000"
    assert "x-ratelimit-reset-tokens" in r.headers


async def test_proxy_429_has_retry_after(fake_upstream):
    _, key = keys.create_key("x", [], monthly_token_cap=None, rpm_limit=1)
    async with proxy_client(fake_upstream) as c:
        first = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
        second = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert first.status_code == 200 and second.status_code == 429
    assert second.headers["x-ratelimit-remaining-requests"] == "0"
    assert "retry-after" in second.headers
    assert int(second.headers["retry-after"]) >= 0


async def test_unlimited_key_no_headers(fake_upstream):
    _, key = keys.create_key("x", [], None, None)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key), json={"model": "demo:latest"})
    assert r.status_code == 200
    assert "x-ratelimit-limit-requests" not in r.headers
