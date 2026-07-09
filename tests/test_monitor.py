"""Monitoring par serveur : agrégations d'usage (attribution serveur), graphiques SVG purs,
et rendu de la page Monitor."""
from app import charts, db, keys, servers, usage
from tests.conftest import admin_client  # noqa: F401 (fixture)

PW = "admin-mdp"


def _emit(key_id, server_id, status=200, tokens=0):
    usage.record(key_id=key_id, client_ip="203.0.113.9", method="POST", path="/api/chat",
                 model="demo:latest", status=status, duration_ms=1,
                 tokens_prompt=tokens, tokens_completion=0, server_id=server_id)


# --- Agrégations -----------------------------------------------------------------------------

def test_server_summary_and_per_key():
    srv = servers.create_server("s", "http://s")
    k1, _ = keys.create_key("a", [], None, None, server_id=srv.id)
    k2, _ = keys.create_key("b", [], None, None, server_id=srv.id)
    _emit(k1.id, srv.id, 200, tokens=100)
    _emit(k1.id, srv.id, 500, tokens=0)
    _emit(k2.id, srv.id, 200, tokens=50)
    s = usage.server_summary(srv.id)
    assert s["requests"] == 3 and s["tokens"] == 150 and s["errors"] == 1 and s["keys"] == 2
    per_key = usage.server_per_key(srv.id)
    assert per_key[0]["label"] == "a" and per_key[0]["tokens"] == 100
    assert per_key[0]["errors"] == 1


def test_server_status_breakdown():
    srv = servers.create_server("s", "http://s")
    k, _ = keys.create_key("a", [], None, None, server_id=srv.id)
    _emit(k.id, srv.id, 200)
    _emit(k.id, srv.id, 404)
    _emit(k.id, srv.id, 503)
    b = usage.server_status_breakdown(srv.id)
    assert b == {"2xx": 1, "3xx": 0, "4xx": 1, "5xx": 1}


def test_server_isolation_by_server_id():
    s1 = servers.create_server("s1", "http://s1")
    s2 = servers.create_server("s2", "http://s2")
    k, _ = keys.create_key("a", [], None, None, server_id=s1.id)
    _emit(k.id, s1.id, 200, tokens=10)
    _emit(k.id, s2.id, 200, tokens=99)  # même clé, autre serveur (repli)
    assert usage.server_summary(s1.id)["tokens"] == 10
    assert usage.server_summary(s2.id)["tokens"] == 99


# --- Graphiques SVG (fonctions pures) --------------------------------------------------------

def test_hbar_renders_and_empty():
    svg = charts.hbar([("clé-a", 100), ("clé-b", 40)], "T", unit=" tok")
    assert svg.startswith("<svg") and "clé-a" in svg and "<rect" in svg
    assert "Aucune donnée" in charts.hbar([], "T")
    assert "Aucune donnée" in charts.hbar([("x", 0)], "T")


def test_donut_renders_and_empty():
    svg = charts.donut([("2xx", 3, charts.SUCCESS), ("5xx", 1, charts.DANGER)], "S")
    assert "<circle" in svg and charts.SUCCESS in svg and charts.DANGER in svg
    assert "Aucune donnée" in charts.donut([("2xx", 0, charts.SUCCESS)], "S")


def test_line_renders_and_degrades():
    svg = charts.line([("06-01", 3), ("06-02", 7), ("06-03", 2)], "R")
    assert "<polyline" in svg and "<polygon" in svg
    assert "Aucune donnée" in charts.line([("06-01", 5)], "R")  # < 2 points


def test_fmt():
    assert charts._fmt(500) == "500"
    assert charts._fmt(1500) == "1.5k"
    assert charts._fmt(2_000_000) == "2.0M"


# --- Page ------------------------------------------------------------------------------------

async def test_monitor_page_renders(admin_client):
    async with admin_client as c:
        keys.set_admin_password(PW)
        await c.post("/admin/login", data={"password": PW})
        srv = servers.create_server("s", "http://s")
        k, _ = keys.create_key("client-a", [], None, None, server_id=srv.id)
        _emit(k.id, srv.id, 200, tokens=123)
        r = await c.get(f"/admin/servers/{srv.id}/monitor")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="mon-reqs"' in body
    assert 'data-testid="status-donut"' in body
    assert 'data-testid="monitor-perkey"' in body
    assert "client-a" in body and "<svg" in body
