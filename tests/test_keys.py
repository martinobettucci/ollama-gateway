"""Tests unitaires du store de clés (CRUD, origines, migration/import de clé)."""
from app import auth, keys


def test_create_and_get_key():
    rec, secret = keys.create_key("acme", ["192.168.0.0/24"], 1000, 5, "note")
    assert secret.startswith("sk-ollama-")
    got = keys.get_key(rec.id)
    assert got.label == "acme" and got.enabled
    assert got.origins == ["192.168.0.0/24"]
    assert got.monthly_token_cap == 1000 and got.rpm_limit == 5
    # la clé n'est retrouvable que par sa valeur (hash), jamais stockée en clair
    assert keys.find_by_key(secret)["id"] == rec.id
    assert keys.find_by_key("sk-ollama-bidon") is None


def test_import_existing_key_value():
    existing = "sk-ollama-db0f4b6fa1849766fcba02cd5b4e34f964c1e9f0974200a0"
    rec, secret = keys.create_key("client", ["203.0.113.10"], None, None,
                                  key_value=existing)
    assert secret == existing
    assert keys.find_by_key(existing)["id"] == rec.id
    assert auth.key_prefix(existing) == rec.key_prefix


def test_enable_disable_and_delete():
    rec, _ = keys.create_key("x", [], None, None)
    keys.set_enabled(rec.id, False)
    assert not keys.get_key(rec.id).enabled
    keys.set_enabled(rec.id, True)
    assert keys.get_key(rec.id).enabled
    keys.delete_key(rec.id)
    assert keys.get_key(rec.id) is None


def test_update_key_replaces_origins_and_quota():
    rec, _ = keys.create_key("x", ["10.0.0.0/8"], 5, 5)
    keys.update_key(rec.id, "y", ["1.2.3.4"], None, 9, "n")
    got = keys.get_key(rec.id)
    assert got.label == "y" and got.origins == ["1.2.3.4"]
    assert got.monthly_token_cap is None and got.rpm_limit == 9


def test_origin_allowed_matrix():
    assert keys.origin_allowed("1.2.3.4", [])              # aucune restriction
    assert keys.origin_allowed("192.168.1.10", ["192.168.0.0/24"])
    assert not keys.origin_allowed("10.0.0.1", ["192.168.0.0/24"])
    assert keys.origin_allowed("203.0.113.10", ["203.0.113.10"])
    assert keys.origin_allowed("2001:bc8:711::1", ["2001:bc8:711::/48"])
    assert not keys.origin_allowed("bogus-ip", ["192.168.0.0/24"])


def test_admin_password_store():
    assert keys.get_admin_hash() is None
    keys.set_admin_password("s3cret-admin")
    stored = keys.get_admin_hash()
    assert stored and auth.verify_password("s3cret-admin", stored)
    keys.set_admin_password("nouveau-mdp")  # upsert
    assert auth.verify_password("nouveau-mdp", keys.get_admin_hash())


def test_create_key_with_server_and_models():
    from app import servers
    srv = servers.create_server("distant", "http://h:11434")
    rec, _ = keys.create_key("x", [], None, None, server_id=srv.id,
                             models=["demo:latest", "autre:latest"])
    got = keys.get_key(rec.id)
    assert got.server_id == srv.id and got.server_name == "distant"
    assert got.models == ["demo:latest", "autre:latest"]


def test_update_key_changes_server_and_models():
    from app import servers
    srv1 = servers.create_server("s1", "http://h1:11434")
    srv2 = servers.create_server("s2", "http://h2:11434")
    rec, _ = keys.create_key("x", [], None, None, server_id=srv1.id, models=["demo:latest"])
    keys.update_key(rec.id, "x", [], None, None, "n",
                    server_id=srv2.id, models=["autre:latest"])
    got = keys.get_key(rec.id)
    assert got.server_id == srv2.id and got.models == ["autre:latest"]


def test_update_key_none_keeps_server_and_models():
    from app import servers
    srv = servers.create_server("s", "http://h:11434")
    rec, _ = keys.create_key("x", [], None, None, server_id=srv.id, models=["demo:latest"])
    keys.update_key(rec.id, "y", [], None, None, "n")  # server_id/models None → inchangés
    got = keys.get_key(rec.id)
    assert got.label == "y" and got.server_id == srv.id and got.models == ["demo:latest"]
