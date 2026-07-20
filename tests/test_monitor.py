"""Monitoring par serveur : agrégations d'usage (attribution serveur), graphiques SVG purs,
et rendu de la page Monitor."""
from app import charts, keys, servers, usage
from tests.conftest import admin_client  # noqa: F401,F811 (fixture)

PW = "admin-mdp"


def _emit(key_id, server_id, status=200, tokens=0, model="demo:latest"):
    usage.record(key_id=key_id, client_ip="203.0.113.9", method="POST", path="/api/chat",
                 model=model, status=status, duration_ms=1,
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
    assert s["requests"] == 3 and s["tokens"] == 150 and s["errors"] == 1 and s["key_count"] == 2
    per_key = usage.server_per_key(srv.id)
    assert per_key[0]["label"] == "a" and per_key[0]["tokens"] == 100
    assert per_key[0]["errors"] == 1


def _emit_at(key_id, server_id, ts, model, status=200, tokens=0):
    """Insère un événement avec un horodatage EXPLICITE (SQLite `ts` a une résolution à la seconde ;
    les émissions d'un même test s'égaliseraient sinon, rendant le tri par dernier usage non testable)."""
    from app import db
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO usage_events(key_id, client_ip, method, path, model, status, "
                "duration_ms, tokens_prompt, tokens_completion, server_id, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (key_id, "203.0.113.9", "POST", "/api/chat", model, status, 1,
                 tokens, 0, server_id, ts))
    finally:
        conn.close()


def test_server_per_model_traces_latest_usage():
    """Traçage par modèle : agrégats corrects et TRI par dernier usage (plus récent d'abord).
    Les événements sans modèle résolu (`model=''`) sont exclus du traçage par modèle."""
    srv = servers.create_server("s", "http://s")
    k, _ = keys.create_key("a", [], None, None, server_id=srv.id)
    _emit_at(k.id, srv.id, "2026-07-01 09:00:00", "demo:latest", 200, tokens=10)
    _emit_at(k.id, srv.id, "2026-07-01 10:00:00", "demo:latest", 500, tokens=0)
    _emit_at(k.id, srv.id, "2026-07-05 08:00:00", "autre:latest", 200, tokens=5)  # + récent
    _emit_at(k.id, srv.id, "2026-07-06 08:00:00", "", 200, tokens=0)              # exclu
    rows = usage.server_per_model(srv.id)
    assert [r["model"] for r in rows] == ["autre:latest", "demo:latest"]  # tri par last_seen DESC
    demo = next(r for r in rows if r["model"] == "demo:latest")
    assert demo["reqs"] == 2 and demo["tokens"] == 10 and demo["errors"] == 1
    assert demo["first_seen"] == "2026-07-01 09:00:00"
    assert demo["last_seen"] == "2026-07-01 10:00:00"


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


async def test_monitor_page_shows_per_model_tracing(admin_client):
    async with admin_client as c:
        keys.set_admin_password(PW)
        await c.post("/admin/login", data={"password": PW})
        srv = servers.create_server("s", "http://s")
        k, _ = keys.create_key("client-a", [], None, None, server_id=srv.id)
        _emit(k.id, srv.id, 200, tokens=42, model="mistral:7b")
        r = await c.get(f"/admin/servers/{srv.id}/monitor")
    assert r.status_code == 200
    assert 'data-testid="monitor-permodel"' in r.text
    assert "mistral:7b" in r.text  # modèle tracé avec son dernier usage


async def test_admin_model_pull_and_delete_routes(admin_client, probe_via_fake):
    """Routes d'admin de gestion de modèles : pull ajoute au catalogue amont, delete l'en retire,
    et la sonde est rejouée pour rafraîchir last_models. Amont routé vers le faux Ollama."""
    from devfixtures import fake_ollama
    fake_ollama.reset_models()
    async with admin_client as c:
        keys.set_admin_password(PW)
        await c.post("/admin/login", data={"password": PW})
        srv = servers.create_server("atelier", "http://fake")
        pull = await c.post(f"/admin/servers/{srv.id}/models/pull",
                            data={"model": "newmodel:1b"})
        assert pull.status_code == 303
        assert "newmodel:1b" in fake_ollama.MODELS
        page = await c.get("/admin/servers")
        assert "téléchargé" in page.text  # flash de succès (fr par défaut)
        assert "newmodel:1b" in page.text  # last_models rafraîchi par la sonde
        delete = await c.post(f"/admin/servers/{srv.id}/models/delete",
                              data={"model": "demo:latest"})
        assert delete.status_code == 303
        assert "demo:latest" not in fake_ollama.MODELS


async def test_admin_model_routes_require_login(admin_client):
    async with admin_client as c:
        keys.set_admin_password(PW)  # mdp défini mais pas de session → garde vers /admin/login
        r1 = await c.post("/admin/servers/1/models/pull", data={"model": "m:1b"})
        r2 = await c.post("/admin/servers/1/models/delete", data={"model": "m:1b"})
    assert r1.status_code == 303 and r1.headers["location"] == "/admin/login"
    assert r2.status_code == 303 and r2.headers["location"] == "/admin/login"
