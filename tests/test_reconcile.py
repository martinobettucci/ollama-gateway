"""Tests de la réconciliation déclarative (app/reconcile.py) : interpolation d'env, validation,
upsert serveurs/cibles/clés, idempotence, import de clé connue, élagage (disable/prune)."""
import pytest

from app import config, keys, reconcile, servers, targets


def _write(tmp_path, text: str) -> str:
    p = tmp_path / "gateway.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


# --- Interpolation d'environnement ------------------------------------------------------------

def test_interpolate_replaces_env(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cr3t")
    assert reconcile.interpolate("Bearer ${MY_TOKEN}") == "Bearer s3cr3t"
    assert reconcile.interpolate({"a": ["${MY_TOKEN}"]}) == {"a": ["s3cr3t"]}


def test_interpolate_missing_env_fails():
    with pytest.raises(reconcile.ConfigError):
        reconcile.interpolate("${DEFINITELY_UNSET_VAR_XYZ}")


# --- Validation -------------------------------------------------------------------------------

def test_validate_rejects_bad_base_url(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: s1
    base_url: ftp://nope
""")
    with pytest.raises(reconcile.ConfigError):
        reconcile.apply(path)


def test_validate_rejects_unknown_server_ref(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: s1
    base_url: http://127.0.0.1:11434
keys:
  - name: k1
    server: does-not-exist
""")
    with pytest.raises(reconcile.ConfigError):
        reconcile.apply(path)


def test_validate_rejects_unknown_api(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: s1
    base_url: http://127.0.0.1:11434
keys:
  - name: k1
    apis: [ollama, bogus-api]
""")
    with pytest.raises(reconcile.ConfigError):
        reconcile.apply(path)


def test_validate_rejects_duplicate_default_server(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: a
    base_url: http://127.0.0.1:11434
    default: true
  - name: b
    base_url: http://127.0.0.1:11435
    default: true
""")
    with pytest.raises(reconcile.ConfigError):
        reconcile.apply(path)


# --- Upsert serveurs / cibles / clés ----------------------------------------------------------

def test_apply_creates_servers_targets_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("REMOTE_TOKEN", "remote-bearer-xyz")
    monkeypatch.setenv("ACME_KEY", "sk-ollama-acmeknownkey000000000000000000000000000000000000000000")
    path = _write(tmp_path, """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
    models: [llama3:8b, qwen3:4b]
  - name: gpu
    base_url: http://127.0.0.1:11435
    token: ${REMOTE_TOKEN}
targets:
  - name: public
    base_url: https://llm.example:8443
    default: true
keys:
  - name: acme-prod
    value: ${ACME_KEY}
    label: ACME production
    server: gpu
    target: public
    origins: [203.0.113.0/24]
    models: [llama3:8b]
    apis: [ollama, openai]
    rpm_limit: 60
    monthly_token_cap: 1000000
""")
    report = reconcile.apply(path)
    assert set(report.servers_created) == {"local", "gpu"}
    assert report.targets_created == ["public"]
    assert report.keys_created == ["acme-prod"]

    srvs = {s.name: s for s in servers.list_servers()}
    assert srvs["local"].is_default and not srvs["gpu"].is_default
    assert srvs["local"].last_models == ["llama3:8b", "qwen3:4b"]
    assert srvs["gpu"].has_auth  # jeton distant chiffré au repos

    # La clé importée (valeur connue) est retrouvable par le proxy et correctement configurée.
    row = keys.find_by_key("sk-ollama-acmeknownkey000000000000000000000000000000000000000000")
    assert row is not None
    rec = keys.get_key(row["id"])
    assert rec.external_ref == "acme-prod" and rec.enabled
    assert rec.server_name == "gpu" and rec.target_name == "public"
    assert rec.models == ["llama3:8b"] and set(rec.apis) == {"ollama", "openai"}
    assert rec.rpm_limit == 60 and rec.monthly_token_cap == 1000000
    assert rec.origins == ["203.0.113.0/24"]


def test_apply_is_idempotent(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: k1
""")
    r1 = reconcile.apply(path)
    assert r1.keys_created == ["k1"]
    r2 = reconcile.apply(path)
    assert r2.keys_created == [] and r2.keys_updated == ["k1"]
    assert r2.servers_created == [] and r2.servers_updated == ["local"]
    # Une seule clé gérée, un seul serveur (rien de dupliqué au 2e passage).
    assert len(keys.managed_refs()) == 1
    assert len([s for s in servers.list_servers() if s.name == "local"]) == 1


def test_apply_updates_key_config_without_regenerating_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("K", "sk-ollama-stablekey00000000000000000000000000000000000000000000000")
    base = """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: k1
    value: ${K}
    rpm_limit: %d
"""
    reconcile.apply(_write(tmp_path, base % 10))
    reconcile.apply(_write(tmp_path, base % 99))
    row = keys.find_by_key("sk-ollama-stablekey00000000000000000000000000000000000000000000000")
    assert row is not None  # même secret : la clé reste utilisable après mise à jour
    assert keys.get_key(row["id"]).rpm_limit == 99


# --- Élagage (prune) --------------------------------------------------------------------------

def _two_keys_then_one(tmp_path, prune: bool):
    both = """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: k1
  - name: k2
"""
    one = both.replace("  - name: k2\n", "")
    prune_line = "prune: true\n" if prune else ""
    reconcile.apply(_write(tmp_path, both))
    return reconcile.apply(_write(tmp_path, prune_line + one))


def test_prune_default_disables_removed_key(tmp_path):
    report = _two_keys_then_one(tmp_path, prune=False)
    assert report.keys_disabled == ["k2"] and report.keys_deleted == []
    refs = keys.managed_refs()
    assert "k2" in refs  # toujours en base, mais désactivée
    assert keys.get_key(refs["k2"]).enabled is False


def test_prune_true_deletes_removed_key(tmp_path):
    report = _two_keys_then_one(tmp_path, prune=True)
    assert report.keys_deleted == ["k2"] and report.keys_disabled == []
    assert "k2" not in keys.managed_refs()


def test_reconcile_never_touches_ui_keys(tmp_path):
    # Une clé créée « par l'UI » (external_ref NULL) ne doit jamais être désactivée/supprimée.
    servers.ensure_default()
    ui_rec, _secret = keys.create_key(label="ui", origins=[], monthly_token_cap=None,
                                      rpm_limit=None)
    path = _write(tmp_path, """
prune: true
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: managed1
""")
    reconcile.apply(path)
    assert keys.get_key(ui_rec.id) is not None
    assert keys.get_key(ui_rec.id).enabled is True


def test_disabled_key_reenabled_when_back_in_yaml(tmp_path):
    both = """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: k1
  - name: k2
"""
    one = both.replace("  - name: k2\n", "")
    reconcile.apply(_write(tmp_path, both))
    reconcile.apply(_write(tmp_path, one))            # k2 désactivée
    refs = keys.managed_refs()
    assert keys.get_key(refs["k2"]).enabled is False
    reconcile.apply(_write(tmp_path, both))           # k2 réintroduite
    assert keys.get_key(keys.managed_refs()["k2"]).enabled is True


# --- Garde-fou du mode déclaratif -------------------------------------------------------------

def _delivered_at(ref: str):
    from app import db
    conn = db.connect()
    try:
        r = conn.execute(
            "SELECT secret_delivered_at FROM api_keys WHERE external_ref = ?", (ref,)).fetchone()
        return r["secret_delivered_at"] if r else None
    finally:
        conn.close()


# --- Livraison du secret (phase 2) ------------------------------------------------------------

_DELIVER_YAML = """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
targets:
  - name: pub
    base_url: https://gw.example:8443
    default: true
keys:
  - name: gen1
    target: pub
    deliver:
      - webhook: { url: http://hook.local/x, preset: slack }
"""


def test_generated_key_delivered_and_marked_then_idempotent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(reconcile.deliver, "deliver_key",
                        lambda channels, smtp, **kw: (calls.append(kw), [])[1])
    path = _write(tmp_path, _DELIVER_YAML)
    report = reconcile.apply(path)
    assert report.keys_delivered == ["gen1"] and report.delivery_errors == []
    assert len(calls) == 1
    assert calls[0]["url"] == "https://gw.example:8443"     # URL publique de la cible = #OllamaUrl
    assert calls[0]["secret"].startswith("sk-")            # secret généré transmis
    assert _delivered_at("gen1") is not None               # horodatage de livraison posé

    calls.clear()
    report2 = reconcile.apply(path)                         # 2e passage : clé déjà là
    assert calls == [] and report2.keys_delivered == []    # aucune relivraison (idempotent)


def test_delivery_failure_reported_and_not_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile.deliver, "deliver_key", lambda *a, **k: ["boom"])
    report = reconcile.apply(_write(tmp_path, _DELIVER_YAML))
    assert report.keys_delivered == [] and report.delivery_errors
    assert _delivered_at("gen1") is None                   # échec → pas d'horodatage


def test_imported_key_is_not_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv("K", "sk-ollama-importedvalue000000000000000000000000000000000000000000")
    calls = []
    monkeypatch.setattr(reconcile.deliver, "deliver_key",
                        lambda *a, **k: calls.append(k) or [])
    path = _write(tmp_path, """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: imp1
    value: ${K}
    deliver:
      - webhook: { url: http://hook.local/x, preset: slack }
""")
    reconcile.apply(path)
    assert calls == []                                     # clé importée : secret connu, pas de livraison


def test_email_channel_requires_smtp(tmp_path):
    path = _write(tmp_path, """
servers:
  - name: local
    base_url: http://127.0.0.1:11434
    default: true
keys:
  - name: k1
    deliver:
      - email: { to: ops@acme.example }
""")
    with pytest.raises(reconcile.ConfigError):
        reconcile.apply(path)


def test_declarative_mode_skips_auto_default_server(monkeypatch):
    # En mode déclaratif, ensure_default n'auto-crée PAS « Ollama local » (le reconciler le fera).
    monkeypatch.setattr(config, "DECLARATIVE", True)
    assert servers.ensure_default() == 0
    assert servers.list_servers() == []
    assert targets.ensure_default() == 0
    assert targets.list_targets() == []
