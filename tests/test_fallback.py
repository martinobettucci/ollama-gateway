"""Repli (fallback) transparent : sur erreur serveur (5xx) de l'amont primaire, le proxy rejoue
la requête vers le serveur de repli. Le faux upstream renvoie 500 quand le Host contient « fail »."""
from app import db, keys, servers
from tests.conftest import proxy_client


def _auth(key):
    return {"authorization": f"Bearer {key}"}


def _events():
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT status, server_id FROM usage_events ORDER BY id").fetchall()
    finally:
        conn.close()


async def test_fallback_on_primary_5xx(fake_upstream):
    # Primaire → Host « fail.example » (le faux renvoie 500) ; repli → Host sain (200).
    primary = servers.create_server("primary", "http://fail.example")
    fb = servers.create_server("secours", "http://ok.example")
    rec, key = keys.create_key("k", [], None, None, server_id=primary.id,
                               fallback_server_id=fb.id)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key),
                         json={"model": "demo:latest", "stream": False})
    assert r.status_code == 200 and "Bonjour" in r.text
    # L'événement d'usage est attribué au serveur de REPLI.
    ev = _events()[-1]
    assert ev["status"] == 200 and ev["server_id"] == fb.id


async def test_no_fallback_returns_5xx(fake_upstream):
    primary = servers.create_server("primary", "http://fail.example")
    rec, key = keys.create_key("k", [], None, None, server_id=primary.id)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key),
                         json={"model": "demo:latest", "stream": False})
    # Sans repli, l'erreur serveur du primaire est relayée telle quelle.
    assert r.status_code == 500


async def test_primary_ok_not_using_fallback(fake_upstream):
    primary = servers.create_server("primary", "http://ok.example")
    fb = servers.create_server("secours", "http://also-ok.example")
    rec, key = keys.create_key("k", [], None, None, server_id=primary.id,
                               fallback_server_id=fb.id)
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/chat", headers=_auth(key),
                         json={"model": "demo:latest", "stream": False})
    assert r.status_code == 200
    assert _events()[-1]["server_id"] == primary.id


async def test_fallback_roundtrip():
    p = servers.create_server("p", "http://p.example")
    f = servers.create_server("f", "http://f.example")
    rec, _ = keys.create_key("k", [], None, None, server_id=p.id, fallback_server_id=f.id)
    got = keys.get_key(rec.id)
    assert got.fallback_server_id == f.id and got.fallback_server_name == "f"
    keys.update_key(rec.id, "k", [], None, None, "", clear_fallback=True)
    assert keys.get_key(rec.id).fallback_server_id is None
