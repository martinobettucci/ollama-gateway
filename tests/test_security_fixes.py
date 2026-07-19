"""Tests dédiés aux correctifs de l'audit de sécurité pré-open-source.

Chaque classe cible un item de l'audit (docs/SECURITY_AUDIT.md) : H2, M1, M2, L1, L2, L3, I1.
(H1 = bump des dépendances, prouvé par `pip-audit` ; L4 = flag cookie, couvert par config.)
"""
import glob
import hashlib
import json

import pytest

from app import auth, config, db, keys, quotas, reqlog, servers
from tests.conftest import proxy_client


def _auth(key):
    return {"authorization": f"Bearer {key}"}


@pytest.fixture(autouse=True)
def reset_inflight():
    """Évite la pollution inter-tests du compteur « en vol » (état mémoire process)."""
    quotas._INFLIGHT.clear()
    yield
    quotas._INFLIGHT.clear()


# --- H2 : le rôle admin refuse de démarrer sur un bind « toutes interfaces » en prod ----------

class TestAdminBindFailClosed:
    def _prod(self, monkeypatch, role, host):
        monkeypatch.setattr(config, "IS_PROD", True)
        monkeypatch.setattr(config, "ADMIN_SESSION_SECRET", "vrai-secret-aleatoire-long")
        monkeypatch.setattr(config, "P2E_MASTER_KEY", "autre-secret-aleatoire-long")
        monkeypatch.setattr(config, "GATEWAY_ROLE", role)
        monkeypatch.setattr(config, "ADMIN_HOST", host)

    def test_admin_role_rejects_wildcard_v4(self, monkeypatch):
        self._prod(monkeypatch, "admin", "0.0.0.0")
        with pytest.raises(RuntimeError) as exc:
            config.check_runtime_secrets()
        assert "ADMIN_HOST" in str(exc.value)

    def test_admin_role_rejects_wildcard_v6(self, monkeypatch):
        self._prod(monkeypatch, "admin", "::")
        with pytest.raises(RuntimeError):
            config.check_runtime_secrets()

    def test_admin_role_rejects_empty_bind(self, monkeypatch):
        self._prod(monkeypatch, "admin", "")
        with pytest.raises(RuntimeError):
            config.check_runtime_secrets()

    def test_admin_role_accepts_lan_ip(self, monkeypatch):
        self._prod(monkeypatch, "admin", "192.168.1.10")
        config.check_runtime_secrets()  # ne lève pas

    def test_proxy_role_ignores_admin_bind(self, monkeypatch):
        # Le rôle proxy ne lie jamais l'admin → un wildcard ne doit pas le bloquer.
        self._prod(monkeypatch, "proxy", "0.0.0.0")
        config.check_runtime_secrets()  # ne lève pas


# --- M1 : les endpoints de gestion du catalogue ne sont jamais proxifiés ----------------------

class TestManagementEndpointsBlocked:
    async def test_pull_delete_create_blocked(self, fake_upstream):
        _, key = keys.create_key("x", [], None, None)
        async with proxy_client(fake_upstream) as c:
            pull = await c.post("/api/pull", headers=_auth(key),
                                json={"name": "autre:latest"})
            delete = await c.request("DELETE", "/api/delete", headers=_auth(key),
                                     json={"name": "demo:latest"})
            create = await c.post("/api/create", headers=_auth(key), json={"name": "x"})
            push = await c.post("/api/push", headers=_auth(key), json={"name": "x"})
        assert pull.status_code == 403 and "gestion" in pull.text
        assert delete.status_code == 403
        assert create.status_code == 403
        assert push.status_code == 403

    async def test_blobs_subpath_blocked(self, fake_upstream):
        _, key = keys.create_key("x", [], None, None)
        async with proxy_client(fake_upstream) as c:
            r = await c.post("/api/blobs/sha256:abc", headers=_auth(key), json={})
        assert r.status_code == 403

    async def test_inference_still_allowed(self, fake_upstream):
        _, key = keys.create_key("x", [], None, None)
        async with proxy_client(fake_upstream) as c:
            chat = await c.post("/api/chat", headers=_auth(key),
                                json={"model": "demo:latest"})
        assert chat.status_code == 200


# --- M2 : le rate-limit compte les requêtes « en vol » (anti-concurrence) ----------------------

class TestInflightRateLimit:
    def test_inflight_request_counts_against_rpm(self):
        rec, _ = keys.create_key("x", [], None, 1)  # rpm_limit = 1
        r = keys.get_key(rec.id)
        conn = db.connect()
        try:
            ok, _ = quotas.check(r, conn)
            assert ok  # rien en vol → passe
            quotas.enter(r.id)  # une requête concurrente en vol, non encore journalisée
            try:
                blocked, reason = quotas.check(r, conn)
                assert not blocked and "rate-limit" in reason
            finally:
                quotas.leave(r.id)
            ok_again, _ = quotas.check(r, conn)
            assert ok_again  # libéré → repasse
        finally:
            conn.close()

    def test_inflight_counter_is_balanced(self):
        quotas.enter(42)
        quotas.enter(42)
        assert quotas.inflight(42) == 2
        quotas.leave(42)
        quotas.leave(42)
        assert quotas.inflight(42) == 0
        quotas.leave(42)  # sous-zéro sans effet
        assert quotas.inflight(42) == 0

    async def test_proxy_flow_releases_inflight(self, fake_upstream):
        # Après une requête proxy complète, le compteur en vol revient à zéro (pas de fuite).
        _, key = keys.create_key("x", [], None, None)
        rec = keys.list_keys()[0]
        async with proxy_client(fake_upstream) as c:
            await c.post("/api/chat", headers=_auth(key),
                         json={"model": "demo:latest", "stream": True})
        assert quotas.inflight(rec.id) == 0


# --- L1 : validation de l'URL amont (SSRF post-auth défense en profondeur) ---------------------

class TestBaseUrlValidation:
    def test_accepts_loopback_and_lan(self):
        servers.validate_base_url("http://127.0.0.1:11434")     # Ollama local
        servers.validate_base_url("https://192.168.1.5:11434")  # Ollama LAN
        servers.validate_base_url("http://ollama.example.com")  # hostname public

    def test_rejects_bad_scheme(self):
        with pytest.raises(ValueError):
            servers.validate_base_url("ftp://127.0.0.1")
        with pytest.raises(ValueError):
            servers.validate_base_url("file:///etc/passwd")

    def test_rejects_link_local_metadata(self):
        with pytest.raises(ValueError):
            servers.validate_base_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_missing_host(self):
        with pytest.raises(ValueError):
            servers.validate_base_url("http://")


# --- L2 : pbkdf2 à fort nombre de tours, rétro-compatible --------------------------------------

class TestPbkdf2Rounds:
    def test_hash_uses_strong_rounds(self):
        algo, rounds, _salt, _hash = auth.hash_password("x").split("$")
        assert algo == "pbkdf2_sha256"
        assert int(rounds) >= 600_000

    def test_verify_backward_compatible_with_legacy_rounds(self):
        salt = bytes.fromhex("00" * 16)
        dk = hashlib.pbkdf2_hmac("sha256", b"legacy", salt, 240_000)
        old = f"pbkdf2_sha256$240000${salt.hex()}${dk.hex()}"
        assert auth.verify_password("legacy", old)
        assert not auth.verify_password("wrong", old)


# --- L1 + L3 côté admin (route de création serveur + en-têtes de sécurité) ---------------------

class TestAdminSecurity:
    async def _login(self, c):
        await c.post("/admin/setup",
                     data={"password": "supersecret", "confirm": "supersecret"})

    async def test_security_headers_present(self, admin_client):
        async with admin_client as c:
            await self._login(c)
            r = await c.get("/admin")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert "content-security-policy" in {k.lower() for k in r.headers}

    async def test_server_create_rejects_link_local_url(self, admin_client):
        async with admin_client as c:
            await self._login(c)
            before = len(servers.list_servers())
            r = await c.post("/admin/servers", data={
                "name": "evil", "base_url": "http://169.254.169.254", "auth_token": ""})
            assert r.status_code == 303
            after = len(servers.list_servers())
        assert after == before  # serveur non créé (URL rejetée)


# --- I1 : opt-out de la journalisation du CORPS des requêtes (confidentialité) -----------------

class TestRequestBodyLoggingOptOut:
    def _read_line(self, base):
        files = glob.glob(str(base / "key-1" / "*.jsonl"))
        assert files, "aucun fichier de log écrit"
        return json.loads(open(files[0], encoding="utf-8").read().strip())

    def test_body_stored_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "REQUEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(config, "REQUEST_LOG_BODIES", True)
        reqlog.record(key_id=1, ip="1.2.3.4", method="POST", path="/api/chat",
                      headers={"authorization": "Bearer sk-x",
                               "content-type": "application/json"},
                      body=b'{"model":"m","prompt":"prompt sensible"}', status=200, model="m")
        rec = self._read_line(tmp_path)
        assert rec["body"]["prompt"] == "prompt sensible"       # corps conservé
        assert rec["headers"]["authorization"] == "«masqué»"    # secret masqué (inchangé)

    def test_body_suppressed_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "REQUEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(config, "REQUEST_LOG_BODIES", False)
        reqlog.record(key_id=1, ip="1.2.3.4", method="POST", path="/api/chat",
                      headers={"authorization": "Bearer sk-x"},
                      body=b'{"prompt":"prompt sensible"}', status=200, model="m")
        rec = self._read_line(tmp_path)
        assert "prompt sensible" not in json.dumps(rec)         # prompt jamais écrit
        assert "non journalisé" in rec["body"]
        assert rec["path"] == "/api/chat" and rec["model"] == "m"  # métadonnées conservées
