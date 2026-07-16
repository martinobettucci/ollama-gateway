"""Tests du garde-fou fail-closed des secrets de production (`config.check_runtime_secrets`)."""
import pytest

from app import config


def test_no_check_outside_prod(monkeypatch):
    """Dev/staging self-contained : les défauts non secrets sont tolérés (pas de levée)."""
    monkeypatch.setattr(config, "IS_PROD", False)
    monkeypatch.setattr(config, "ADMIN_SESSION_SECRET", config.DEV_SESSION_SECRET)
    monkeypatch.setattr(config, "P2E_MASTER_KEY", config.DEV_MASTER_KEY)
    config.check_runtime_secrets()  # ne lève pas


def test_prod_rejects_default_secrets(monkeypatch):
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.setattr(config, "ADMIN_SESSION_SECRET", config.DEV_SESSION_SECRET)
    monkeypatch.setattr(config, "P2E_MASTER_KEY", config.DEV_MASTER_KEY)
    with pytest.raises(RuntimeError) as exc:
        config.check_runtime_secrets()
    assert "ADMIN_SESSION_SECRET" in str(exc.value)
    assert "P2E_MASTER_KEY" in str(exc.value)


def test_prod_rejects_empty_secret(monkeypatch):
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.setattr(config, "ADMIN_SESSION_SECRET", "")
    monkeypatch.setattr(config, "P2E_MASTER_KEY", "un-vrai-secret-aleatoire-long")
    with pytest.raises(RuntimeError) as exc:
        config.check_runtime_secrets()
    assert "ADMIN_SESSION_SECRET" in str(exc.value)
    assert "P2E_MASTER_KEY" not in str(exc.value)


def test_prod_accepts_real_secrets(monkeypatch):
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.setattr(config, "ADMIN_SESSION_SECRET", "b3f1c2…-aleatoire-openssl-rand-hex-32")
    monkeypatch.setattr(config, "P2E_MASTER_KEY", "9a8b7c…-autre-aleatoire-openssl-rand-hex-32")
    config.check_runtime_secrets()  # ne lève pas
