"""Tests des plafonds/expiration de VIE d'une clé (distinct du rate-limit et du plafond mensuel).
Vérifie l'application par `quotas.check` : date d'expiration, inactivité, plafonds absolus."""
from app import db, keys, quotas, usage


def _check(key_id):
    conn = db.connect()
    try:
        return quotas.check(keys.get_key(key_id, conn), conn)
    finally:
        conn.close()


def _emit(key_id, n=1, tokens=0):
    for _ in range(n):
        usage.record(key_id=key_id, client_ip="203.0.113.9", method="POST", path="/api/chat",
                     model="demo:latest", status=200, duration_ms=1,
                     tokens_prompt=tokens, tokens_completion=0)


def test_no_limits_allows():
    rec, _ = keys.create_key("k", [], None, None)
    assert _check(rec.id) == (True, None)


def test_expired_at_past_refused():
    rec, _ = keys.create_key("k", [], None, None, expires_at="2000-01-01 00:00:00")
    ok, reason = _check(rec.id)
    assert not ok and "expirée" in reason


def test_expires_future_allows():
    rec, _ = keys.create_key("k", [], None, None, expires_at="2999-01-01 00:00:00")
    assert _check(rec.id)[0] is True


def test_total_request_cap():
    rec, _ = keys.create_key("k", [], None, None, total_request_cap=2)
    _emit(rec.id, n=2)
    ok, reason = _check(rec.id)
    assert not ok and "requêtes" in reason


def test_total_token_cap():
    rec, _ = keys.create_key("k", [], None, None, total_token_cap=100)
    _emit(rec.id, n=1, tokens=150)
    ok, reason = _check(rec.id)
    assert not ok and "tokens" in reason


def test_total_token_cap_under_limit_allows():
    rec, _ = keys.create_key("k", [], None, None, total_token_cap=100)
    _emit(rec.id, n=1, tokens=10)
    assert _check(rec.id)[0] is True


def test_idle_expiry_refused_when_stale():
    rec, _ = keys.create_key("k", [], None, None, idle_expiry_days=7)
    # last_used_at ancien → inactivité dépassée.
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE api_keys SET last_used_at = datetime('now','-30 days') "
                         "WHERE id = ?", (rec.id,))
    finally:
        conn.close()
    ok, reason = _check(rec.id)
    assert not ok and "inactivité" in reason


def test_idle_expiry_ok_when_recent():
    rec, _ = keys.create_key("k", [], None, None, idle_expiry_days=7)
    keys.touch_last_used(rec.id)
    assert _check(rec.id)[0] is True


def test_expiry_fields_roundtrip():
    rec, _ = keys.create_key("k", [], None, None, total_token_cap=5, total_request_cap=6,
                             expires_at="2999-01-01 00:00:00", idle_expiry_days=9)
    g = keys.get_key(rec.id)
    assert (g.total_token_cap, g.total_request_cap, g.idle_expiry_days) == (5, 6, 9)
    assert g.expires_at == "2999-01-01 00:00:00"
    keys.update_key(rec.id, "k", [], None, None, "", total_token_cap=None)
    assert keys.get_key(rec.id).total_token_cap is None
