"""Tests unitaires de la compatibilité d'API : mapping chemin→famille, allowlist par clé,
et testeur de compatibilité (matrice servi/non-servi). Le proxy est couvert dans test_proxy.py."""
from app import apis, db, keys, servers
from tests.conftest import probe_via_fake  # noqa: F401 (fixture)


def test_family_for_path():
    assert apis.family_for_path("/api/chat") == "ollama"
    assert apis.family_for_path("/api/tags") == "ollama"
    assert apis.family_for_path("/v1/messages") == "anthropic"
    assert apis.family_for_path("/v1/messages/count_tokens") == "anthropic"
    assert apis.family_for_path("/v1/chat/completions") == "openai"
    assert apis.family_for_path("/v1/models") == "openai"
    assert apis.family_for_path("/v1/embeddings") == "openai"
    assert apis.family_for_path("/nope") is None


def test_is_management_path_flags_all_catalog_mutations():
    """Tous les endpoints de gestion (pull/push/delete/create/copy/blobs) sont reconnus, avec ou
    sans slash final, et /api/blobs/<digest> ; les endpoints d'inférence/listing ne le sont pas."""
    for p in ("/api/pull", "/api/push", "/api/delete", "/api/create", "/api/copy", "/api/blobs"):
        assert apis.is_management_path(p) is True
        assert apis.is_management_path(p + "/") is True
    assert apis.is_management_path("/api/blobs/sha256:abc123") is True
    for p in ("/api/chat", "/api/generate", "/api/tags", "/v1/models", "/v1/chat/completions",
              "/api/embed", "/v1/messages"):
        assert apis.is_management_path(p) is False


def test_catalog_covers_three_families():
    assert set(apis.CATALOG) == set(apis.FAMILIES)
    for eps in apis.CATALOG.values():
        assert eps and all(len(e) == 3 for e in eps)


def test_key_apis_allowlist_roundtrip():
    rec, _ = keys.create_key("x", [], None, None, key_apis=["ollama", "anthropic", "bogus"])
    got = keys.get_key(rec.id)
    # 'bogus' filtré (hors familles connues) ; ordre d'insertion préservé.
    assert got.apis == ["ollama", "anthropic"]


def test_key_apis_default_empty_means_all():
    rec, _ = keys.create_key("x", [], None, None)
    assert keys.get_key(rec.id).apis == []


def test_update_key_apis():
    rec, _ = keys.create_key("x", [], None, None, key_apis=["ollama"])
    keys.update_key(rec.id, "x", [], None, None, "", key_apis=["openai"])
    assert keys.get_key(rec.id).apis == ["openai"]
    # None = inchangé
    keys.update_key(rec.id, "x", [], None, None, "", key_apis=None)
    assert keys.get_key(rec.id).apis == ["openai"]


async def test_run_compat_builds_and_persists_matrix(probe_via_fake):
    srv = servers.create_server("s", "http://fake")
    matrix = await servers.run_compat(srv.id)
    assert set(matrix) == set(apis.FAMILIES)
    # Le faux upstream sert /api/chat mais pas /api/version → matrice mixte servi/non-servi.
    ollama = {e["path"]: e for e in matrix["ollama"]}
    assert ollama["/api/chat"]["served"] is True
    assert ollama["/api/chat"]["status"] == 200
    assert ollama["/api/version"]["served"] is False   # 404 sur le faux upstream
    assert ollama["/api/version"]["status"] == 404
    # Persisté et relu depuis la base.
    got = servers.get_server(srv.id)
    assert got.last_compat_at
    assert got.last_compat["ollama"]
