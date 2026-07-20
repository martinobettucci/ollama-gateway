"""Tests unitaires des cibles publiques (ingress) : défaut seedé, CRUD, rattachement par clé,
et propagation vers la génération de variables d'environnement (URL de la cible)."""
from app import config, keys, targets


def test_ensure_default_seeds_from_public_base_url(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://gw.example:9000")
    tid = targets.ensure_default()
    t = targets.get_target(tid)
    assert t.is_default and t.base_url == "https://gw.example:9000"


def test_ensure_default_placeholder_when_unset(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    t = targets.get_target(targets.ensure_default())
    assert t.base_url == targets.PLACEHOLDER_URL


def test_ensure_default_is_idempotent_single_default():
    targets.ensure_default()
    targets.ensure_default()
    defaults = [t for t in targets.list_targets() if t.is_default]
    assert len(defaults) == 1


def test_new_key_attaches_default_target():
    tid = targets.ensure_default()
    rec, _ = keys.create_key("k", [], None, None)
    assert keys.get_key(rec.id).target_id == tid


def test_key_target_roundtrip_and_env_url():
    targets.ensure_default()
    t = targets.create_target("prod", "https://llm.example:8443/")  # slash final normalisé
    assert t.base_url == "https://llm.example:8443"
    rec, _ = keys.create_key("k", [], None, None, target_id=t.id)
    got = keys.get_key(rec.id)
    assert got.target_id == t.id and got.target_base_url == "https://llm.example:8443"
    # None = inchangé
    keys.update_key(rec.id, "k", [], None, None, "", target_id=None)
    assert keys.get_key(rec.id).target_id == t.id


def test_delete_default_forbidden_and_attached_blocked():
    did = targets.ensure_default()
    assert targets.delete_target(did) is not None  # défaut : interdit
    t = targets.create_target("x", "https://x.example")
    keys.create_key("k", [], None, None, target_id=t.id)
    assert targets.delete_target(t.id) is not None  # clés rattachées : bloqué


def test_delete_unused_target_ok():
    targets.ensure_default()
    t = targets.create_target("tmp", "https://tmp.example")
    assert targets.delete_target(t.id) is None
    assert targets.get_target(t.id) is None
