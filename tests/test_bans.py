"""Bannissement global d'origines : normalisation, application par le proxy, pilotage admin."""
from app import bans, keys
from tests.conftest import proxy_client


def test_normalize_cidr():
    assert bans.normalize_cidr("203.0.113.7") == "203.0.113.7/32"
    assert bans.normalize_cidr("203.0.113.0/24") == "203.0.113.0/24"
    assert bans.normalize_cidr("::1") == "::1/128"
    assert bans.normalize_cidr("pas-une-ip") is None
    assert bans.normalize_cidr("") is None


def test_add_list_remove_is_banned():
    assert bans.add_ban("203.0.113.7") == "203.0.113.7/32"
    assert bans.is_banned("203.0.113.7")
    assert not bans.is_banned("203.0.113.8")
    bans.add_ban("203.0.113.7")  # idempotent (UNIQUE) → pas de doublon
    rows = bans.list_bans()
    assert len(rows) == 1
    bans.remove_ban(rows[0]["id"])
    assert not bans.is_banned("203.0.113.7")


def test_cidr_ban_covers_range():
    bans.add_ban("203.0.113.0/24", "scan")
    assert bans.is_banned("203.0.113.50")
    assert not bans.is_banned("203.0.114.1")


def test_banned_among():
    bans.add_ban("10.0.0.0/8")
    got = bans.banned_among(["10.1.2.3", "192.168.0.1", "", "10.9.9.9"])
    assert got == {"10.1.2.3", "10.9.9.9"}


# --- Application par le proxy (DENY avant toute authentification de clé) ---

async def test_banned_origin_blocked_before_auth(fake_upstream):
    """Une origine bannie est refusée (403) AVANT même le contrôle de clé (aucune clé fournie)."""
    bans.add_ban("203.0.113.9")
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat", json={"model": "demo:latest"})
    assert r.status_code == 403
    assert "bannie" in r.json()["error"]


async def test_banned_cidr_blocks_range_on_proxy(fake_upstream):
    bans.add_ban("203.0.113.0/24")
    async with proxy_client(fake_upstream, source_ip="203.0.113.50") as c:
        r = await c.post("/api/chat", headers={"authorization": "Bearer x"}, json={})
    assert r.status_code == 403


async def test_unbanned_origin_reaches_auth(fake_upstream):
    """Sans bannissement, la requête sans clé retombe sur le 401 d'auth (preuve d'ordre)."""
    async with proxy_client(fake_upstream, source_ip="203.0.113.9") as c:
        r = await c.post("/api/chat", json={})
    assert r.status_code == 401


# --- Pilotage depuis la console admin ---

async def test_logs_requires_login(admin_client):
    keys.set_admin_password("mdp")
    async with admin_client as c:
        r = await c.get("/admin/logs")
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


async def test_logs_ban_and_unban(admin_client):
    keys.set_admin_password("mdp")
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "mdp"})
        r = await c.post("/admin/logs/ban", data={"cidr": "203.0.113.7", "reason": "scan"})
        assert r.status_code == 303
        assert bans.is_banned("203.0.113.7")
        page = await c.get("/admin/logs")
        assert "203.0.113.7" in page.text
        bid = bans.list_bans()[0]["id"]
        await c.post(f"/admin/bans/{bid}/delete")
    assert not bans.is_banned("203.0.113.7")


async def test_logs_ban_invalid_input(admin_client):
    keys.set_admin_password("mdp")
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "mdp"})
        await c.post("/admin/logs/ban", data={"cidr": "pas-une-ip"})
    assert bans.list_bans() == []
