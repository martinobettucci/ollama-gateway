"""Tests des serveurs d'exécution : chiffrement des jetons, CRUD, défaut, sonde de disponibilité."""
from app import config, crypto, keys, servers


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


def test_ensure_default_collapses_duplicate_defaults():
    """Auto-réparation : deux serveurs défaut (course de démarrage antérieure) → un seul conservé,
    la clé qui pointait sur le doublon est réaffectée (jamais orpheline) et le doublon supprimé."""
    from app import db
    did = servers.ensure_default()  # défaut local canonique
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO servers(name, base_url, is_default, enabled) "
                "VALUES ('Ollama local', ?, 1, 1)", (config.OLLAMA_UPSTREAM,))
            dup_id = cur.lastrowid
            conn.execute("INSERT INTO api_keys(label, key_prefix, key_hash, server_id) "
                         "VALUES ('sur-doublon', 'pfx', 'hash-uniq', ?)", (dup_id,))
    finally:
        conn.close()
    assert len([s for s in servers.list_servers() if s.is_default]) == 2  # doublon bien en place

    kept = servers.ensure_default()  # doit collapser
    defaults = [s for s in servers.list_servers() if s.is_default]
    assert len(defaults) == 1 and defaults[0].id == kept == did
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) n FROM servers").fetchone()["n"] == 1
        row = conn.execute("SELECT server_id FROM api_keys WHERE key_hash='hash-uniq'").fetchone()
        assert row["server_id"] == did  # clé réaffectée au défaut conservé
    finally:
        conn.close()


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


# --- Gestion du catalogue (pull / delete) — commandes d'admin LAN-only vers l'amont -------------

async def test_pull_model_adds_to_upstream_catalog(probe_via_fake):
    from devfixtures import fake_ollama
    fake_ollama.reset_models()
    srv = servers.create_server("s", "http://fake")
    ok, msg = await servers.pull_model(srv.id, "  newmodel:1b  ")  # trim du nom
    assert ok is True and msg == "newmodel:1b"
    assert "newmodel:1b" in fake_ollama.MODELS


async def test_delete_model_removes_from_upstream_catalog(probe_via_fake):
    from devfixtures import fake_ollama
    fake_ollama.reset_models()
    srv = servers.create_server("s", "http://fake")
    ok, msg = await servers.delete_model(srv.id, "demo:latest")
    assert ok is True and msg == "demo:latest"
    assert "demo:latest" not in fake_ollama.MODELS


async def test_delete_model_absent_reports_not_found(probe_via_fake):
    from devfixtures import fake_ollama
    fake_ollama.reset_models()
    srv = servers.create_server("s", "http://fake")
    ok, msg = await servers.delete_model(srv.id, "jamais-installé:9b")
    assert ok is False and "introuvable" in msg


async def test_pull_and_delete_guards_before_any_upstream_call():
    # Nom manquant, serveur inconnu, serveur désactivé → refus SANS toucher l'amont (pas de fixture).
    assert await servers.pull_model(1, "") == (False, "nom de modèle manquant")
    assert await servers.delete_model(1, "  ") == (False, "nom de modèle manquant")
    assert await servers.pull_model(999999, "m:1b") == (False, "serveur introuvable")
    srv = servers.create_server("off", "http://fake")
    servers.set_enabled(srv.id, False)
    assert await servers.pull_model(srv.id, "m:1b") == (False, "serveur désactivé")
    assert await servers.delete_model(srv.id, "m:1b") == (False, "serveur désactivé")
