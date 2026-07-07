"""Tests des serveurs d'exécution : chiffrement des jetons, CRUD, défaut, sonde de disponibilité."""
import httpx
import pytest

from app import config, crypto, keys, servers
from devfixtures import fake_ollama


# --- Chiffrement (crypto.py) ------------------------------------------------------------------

def test_crypto_round_trip():
    token = "secret-bearer-xyz"
    enc = crypto.encrypt(token)
    assert enc and enc != token
    assert crypto.decrypt(enc) == token


def test_crypto_empty():
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""


def test_crypto_wrong_master_key_returns_empty(monkeypatch):
    enc = crypto.encrypt("secret")
    monkeypatch.setattr(config, "P2E_MASTER_KEY", "une-autre-cle-maitre")
    assert crypto.decrypt(enc) == ""  # jeton illisible avec une autre clé


# --- Défaut / reconciler ----------------------------------------------------------------------

def test_ensure_default_idempotent_and_single():
    did1 = servers.ensure_default()
    did2 = servers.ensure_default()
    assert did1 == did2
    defaults = [s for s in servers.list_servers() if s.is_default]
    assert len(defaults) == 1 and defaults[0].base_url == config.OLLAMA_UPSTREAM


def test_new_key_attached_to_default_server():
    rec, _ = keys.create_key("k", [], None, None)
    default = [s for s in servers.list_servers() if s.is_default][0]
    assert rec.server_id == default.id and rec.server_name == default.name


# --- CRUD -------------------------------------------------------------------------------------

def test_create_server_encrypts_token_and_hides_it():
    srv = servers.create_server("distant", "http://192.168.0.42:11434/", auth_token="tok-123")
    assert srv.base_url == "http://192.168.0.42:11434"  # slash final retiré
    assert srv.has_auth is True
    # Le jeton n'est jamais exposé en clair par le record ; il se déchiffre pour l'amont.
    conn = None
    from app import db
    conn = db.connect()
    try:
        assert servers.auth_header_for(srv.id, conn) == {"Authorization": "Bearer tok-123"}
    finally:
        conn.close()


def test_update_server_keeps_token_when_blank():
    srv = servers.create_server("s", "http://h:11434", auth_token="tok")
    servers.update_server(srv.id, "s2", "http://h2:11434", enabled=True, auth_token="")
    from app import db
    conn = db.connect()
    try:
        assert servers.auth_header_for(srv.id, conn) == {"Authorization": "Bearer tok"}
    finally:
        conn.close()
    again = servers.get_server(srv.id)
    assert again.name == "s2" and again.base_url == "http://h2:11434" and again.has_auth


def test_update_server_clear_auth():
    srv = servers.create_server("s", "http://h:11434", auth_token="tok")
    servers.update_server(srv.id, "s", "http://h:11434", enabled=True, clear_auth=True)
    assert servers.get_server(srv.id).has_auth is False


def test_delete_default_refused():
    servers.ensure_default()
    default = [s for s in servers.list_servers() if s.is_default][0]
    assert servers.delete_server(default.id) is not None  # message d'erreur


def test_delete_server_with_keys_refused_then_ok():
    srv = servers.create_server("s", "http://h:11434")
    keys.create_key("k", [], None, None, server_id=srv.id)
    assert servers.keys_count(srv.id) == 1
    assert servers.delete_server(srv.id) is not None  # clés rattachées → refus
    # Sans clé, la suppression passe.
    srv2 = servers.create_server("vide", "http://h2:11434")
    assert servers.delete_server(srv2.id) is None
    assert servers.get_server(srv2.id) is None


# --- Sonde de disponibilité -------------------------------------------------------------------

@pytest.fixture
def probe_via_fake(monkeypatch):
    """Route les appels httpx de la sonde vers le faux Ollama (ASGI in-process)."""
    real_client = httpx.AsyncClient

    def _client(*a, **k):
        return real_client(transport=httpx.ASGITransport(app=fake_ollama.app))
    monkeypatch.setattr(servers.httpx, "AsyncClient", _client)


async def test_probe_online_lists_models(probe_via_fake):
    online, models, err = await servers.probe("http://fake")
    assert online is True and err == ""
    assert "demo:latest" in models and "autre:latest" in models


async def test_test_server_persists_result(probe_via_fake):
    srv = servers.create_server("s", "http://fake")
    online, models, _ = await servers.test_server(srv.id)
    assert online is True
    stored = servers.get_server(srv.id)
    assert stored.last_online is True and "demo:latest" in stored.last_models
    assert stored.last_checked_at is not None
