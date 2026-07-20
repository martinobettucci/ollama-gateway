"""Fixtures de test : DB SQLite jetable + clients ASGI (proxy avec faux upstream, admin)."""
import httpx
import pytest

from app import config, db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Chaque test part d'un SQLite neuf (migrations appliquées)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "gateway.db"))
    db.apply_migrations()
    yield


@pytest.fixture(autouse=True)
def reset_login_throttle():
    """Vide l'état mémoire du throttle de login entre les tests (évite la pollution inter-tests)."""
    from app import admin
    admin._LOGIN_FAILS.clear()
    yield
    admin._LOGIN_FAILS.clear()


@pytest.fixture
def fake_upstream():
    """Client httpx branché sur le faux Ollama (ASGI in-process)."""
    from devfixtures import fake_ollama
    fake_ollama.LAST_AUTH = "unset"
    fake_ollama.reset_models()
    transport = httpx.ASGITransport(app=fake_ollama.app)
    return httpx.AsyncClient(transport=transport, base_url="http://fake")


def proxy_client(fake_upstream, source_ip="203.0.113.9"):
    """Client ASGI vers le proxy, avec IP source simulée et upstream injecté."""
    from app import proxy
    proxy.app.state.upstream = fake_upstream
    transport = httpx.ASGITransport(app=proxy.app, client=(source_ip, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://gw")


@pytest.fixture
def admin_client():
    from app import admin
    transport = httpx.ASGITransport(app=admin.app, client=("192.168.0.10", 5555))
    return httpx.AsyncClient(transport=transport, base_url="http://admin", follow_redirects=False)


@pytest.fixture
def probe_via_fake(monkeypatch):
    """Route les appels httpx de la sonde de serveur vers le faux Ollama (ASGI in-process)."""
    from app import servers
    from devfixtures import fake_ollama
    real_client = httpx.AsyncClient

    def _client(*a, **k):
        return real_client(transport=httpx.ASGITransport(app=fake_ollama.app))
    monkeypatch.setattr(servers.httpx, "AsyncClient", _client)
