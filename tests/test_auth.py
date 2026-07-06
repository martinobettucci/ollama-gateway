"""Tests unitaires des primitives d'auth (hachage clés, mot de passe, parsing Bearer)."""
from app import auth, config


def test_generate_key_has_prefix_and_entropy():
    k1, k2 = auth.generate_key(), auth.generate_key()
    assert k1.startswith(config.KEY_PREFIX) and k2.startswith(config.KEY_PREFIX)
    assert k1 != k2 and len(k1) > 40


def test_hash_key_deterministic_and_hex():
    k = auth.generate_key()
    h = auth.hash_key(k)
    assert h == auth.hash_key(k) and len(h) == 64
    assert auth.hash_key(k + "x") != h


def test_password_roundtrip():
    stored = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("correct horse", "garbage")


def test_extract_bearer():
    assert auth.extract_bearer("Bearer abc123") == "abc123"
    assert auth.extract_bearer("bearer abc123") == "abc123"
    assert auth.extract_bearer("Basic abc") is None
    assert auth.extract_bearer("") is None
    assert auth.extract_bearer(None) is None
    assert auth.extract_bearer("Bearer   ") is None
