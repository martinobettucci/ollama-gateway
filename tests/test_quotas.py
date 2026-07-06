"""Tests unitaires des quotas (plafond mensuel de tokens + rate-limit req/min)."""
from app import db, keys, quotas, usage


def _check(rec_id):
    conn = db.connect()
    try:
        return quotas.check(keys.get_key(rec_id, conn), conn)
    finally:
        conn.close()


def test_no_quota_always_allowed():
    rec, _ = keys.create_key("x", [], None, None)
    ok, reason = _check(rec.id)
    assert ok and reason is None


def test_monthly_cap_blocks_when_reached():
    rec, _ = keys.create_key("x", [], monthly_token_cap=20, rpm_limit=None)
    ok, _ = _check(rec.id)
    assert ok
    usage.record(key_id=rec.id, client_ip="1.1.1.1", method="POST", path="/api/chat",
                 model="m", status=200, duration_ms=1, tokens_prompt=15, tokens_completion=10)
    ok, reason = _check(rec.id)
    assert not ok and "plafond mensuel" in reason


def test_rpm_limit_blocks():
    rec, _ = keys.create_key("x", [], monthly_token_cap=None, rpm_limit=2)
    for _ in range(2):
        usage.record(key_id=rec.id, client_ip="1.1.1.1", method="POST", path="/api/chat",
                     model="m", status=200, duration_ms=1)
    ok, reason = _check(rec.id)
    assert not ok and "rate-limit" in reason
