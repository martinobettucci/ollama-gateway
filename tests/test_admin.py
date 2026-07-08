"""Tests d'intégration du panel admin : setup, login/guard, CRUD clés, flash secret unique."""
import pytest

from app import keys


async def test_first_run_redirects_to_setup(admin_client):
    async with admin_client as c:
        r = await c.get("/admin")
    assert r.status_code == 303 and r.headers["location"] == "/admin/setup"


async def test_setup_then_dashboard(admin_client):
    async with admin_client as c:
        r = await c.post("/admin/setup",
                         data={"password": "supersecret", "confirm": "supersecret"})
        assert r.status_code == 303 and r.headers["location"] == "/admin"
        r = await c.get("/admin")
        assert r.status_code == 200 and "Tableau de bord" in r.text


async def test_requires_login_when_admin_set(admin_client):
    keys.set_admin_password("admin-mdp")
    async with admin_client as c:
        r = await c.get("/admin")
        assert r.status_code == 303 and r.headers["location"] == "/admin/login"
        bad = await c.post("/admin/login", data={"password": "faux"})
        assert bad.status_code == 401
        ok = await c.post("/admin/login", data={"password": "admin-mdp"})
        assert ok.status_code == 303 and ok.headers["location"] == "/admin"
        dash = await c.get("/admin")
        assert dash.status_code == 200


async def test_create_key_shows_secret_once(admin_client):
    async with admin_client as c:
        await c.post("/admin/setup", data={"password": "supersecret", "confirm": "supersecret"})
        r = await c.post("/admin/keys", data={
            "label": "client-acme", "origins": "203.0.113.10\n192.168.0.0/24",
            "monthly_token_cap": "100000", "rpm_limit": "", "note": "prod"})
        assert r.status_code == 303
        dash = await c.get("/admin")
        assert "client-acme" in dash.text and "created-secret" in dash.text
        # le secret ne s'affiche qu'UNE fois (flash consommé)
        dash2 = await c.get("/admin")
        assert "created-secret" not in dash2.text
    # persistance + restriction d'origine enregistrée
    rec = keys.list_keys()[0]
    assert rec.label == "client-acme"
    assert rec.origins == ["203.0.113.10", "192.168.0.0/24"]
    assert rec.monthly_token_cap == 100000


async def test_env_modal_shown_once_with_public_base_url(admin_client, monkeypatch):
    """Modale « configurer le client » : à la création d'une clé, le dashboard embarque la
    modale des variables d'env (PUBLIC_BASE_URL + secret) ; plus jamais au rendu suivant."""
    from app import config
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://gw.test")
    async with admin_client as c:
        await c.post("/admin/setup", data={"password": "supersecret", "confirm": "supersecret"})
        await c.post("/admin/keys", data={"label": "cli", "origins": "", "note": ""})
        dash = await c.get("/admin")
        assert 'data-testid="env-dialog"' in dash.text
        assert '"https://gw.test"' in dash.text          # base publique injectée
        assert "OLLAMA_HOST" in dash.text and "ANTHROPIC_BASE_URL" in dash.text
        # le secret n'est rendu que dans CE rendu (flash consommé)
        dash2 = await c.get("/admin")
        assert 'data-testid="env-dialog"' not in dash2.text


async def test_create_key_merges_checked_and_free_models(admin_client):
    """Spec « rattachement » : l'allowlist = cases cochées (model_check) + saisie libre (models),
    dédupliquées en conservant l'ordre cases → texte."""
    async with admin_client as c:
        await c.post("/admin/setup", data={"password": "supersecret", "confirm": "supersecret"})
        r = await c.post("/admin/keys", data={
            "label": "client-mix", "origins": "", "note": "",
            "model_check": ["demo:latest", "autre:latest"],
            "models": "autre:latest\nperso:7b"})
        assert r.status_code == 303
    rec = keys.list_keys()[0]
    assert rec.models == ["demo:latest", "autre:latest", "perso:7b"]


async def test_toggle_and_delete_key(admin_client):
    async with admin_client as c:
        await c.post("/admin/setup", data={"password": "supersecret", "confirm": "supersecret"})
        await c.post("/admin/keys", data={"label": "k", "origins": "", "note": ""})
        kid = keys.list_keys()[0].id
        await c.post(f"/admin/keys/{kid}/toggle")
        assert not keys.get_key(kid).enabled
        await c.post(f"/admin/keys/{kid}/delete")
    assert keys.get_key(kid) is None


async def test_try_chat_requires_login(admin_client):
    keys.set_admin_password("admin-mdp")
    async with admin_client as c:
        r = await c.post("/admin/keys/1/try-chat", json={"message": "salut"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


async def test_try_chat_returns_reply(admin_client, probe_via_fake):
    """« Essayer maintenant » : relais LAN vers le serveur rattaché, réponse du modèle renvoyée
    (modèle choisi automatiquement quand la clé n'a pas d'allowlist)."""
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    rec, _ = keys.create_key("cli", [], None, None, server_id=sid, models=[])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.post(f"/admin/keys/{rec.id}/try-chat", json={"message": "Bonjour ?"})
    assert r.status_code == 200
    data = r.json()
    assert "faux modèle" in data["reply"]
    assert data["model"] in ("demo:latest", "autre:latest")


async def test_try_chat_rejects_model_outside_allowlist(admin_client, probe_via_fake):
    """Fidèle au proxy : un modèle hors de l'allowlist de la clé est refusé (403)."""
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    rec, _ = keys.create_key("cli", [], None, None, server_id=sid, models=["demo:latest"])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.post(f"/admin/keys/{rec.id}/try-chat",
                         json={"message": "x", "model": "autre:latest"})
    assert r.status_code == 403


async def test_try_chat_empty_message_400(admin_client, probe_via_fake):
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    rec, _ = keys.create_key("cli", [], None, None, server_id=sid, models=[])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.post(f"/admin/keys/{rec.id}/try-chat", json={"message": "   "})
    assert r.status_code == 400


@pytest.mark.parametrize("api", ["ollama", "openai-chat", "openai-responses", "anthropic"])
async def test_try_chat_each_api_returns_reply(admin_client, probe_via_fake, api):
    """« Essayer maintenant » : chaque API sélectionnable relaie et renvoie la réponse du modèle
    (le faux Ollama sert /api/chat, /v1/chat/completions, /v1/responses, /v1/messages)."""
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    rec, _ = keys.create_key("cli", [], None, None, server_id=sid, models=[])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.post(f"/admin/keys/{rec.id}/try-chat",
                         json={"message": "salut", "model": "demo:latest", "api": api})
    assert r.status_code == 200
    data = r.json()
    assert "faux modèle" in data["reply"] and data["api"] == api


async def test_try_chat_unknown_api_400(admin_client, probe_via_fake):
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    rec, _ = keys.create_key("cli", [], None, None, server_id=sid, models=[])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.post(f"/admin/keys/{rec.id}/try-chat",
                         json={"message": "x", "model": "demo:latest", "api": "bogus"})
    assert r.status_code == 400


async def test_guard_blocks_key_creation_without_session(admin_client):
    keys.set_admin_password("x")
    async with admin_client as c:
        r = await c.post("/admin/keys", data={"label": "hack", "origins": ""})
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    assert keys.list_keys() == []


async def test_server_models_requires_login(admin_client):
    keys.set_admin_password("admin-mdp")
    async with admin_client as c:
        r = await c.get("/admin/servers/1/models")
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


async def test_server_models_probes_live(admin_client, probe_via_fake):
    """Spec « rattachement » : l'endpoint sonde le serveur en LIVE et renvoie les modèles
    réellement disponibles (peuple les cases à cocher des formulaires de clé)."""
    from app import servers
    keys.set_admin_password("admin-mdp")
    sid = servers.ensure_default()
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.get(f"/admin/servers/{sid}/models")
    assert r.status_code == 200
    data = r.json()
    assert data["online"] is True
    assert "demo:latest" in data["models"] and "autre:latest" in data["models"]
    # La sonde persiste aussi le résultat (état du serveur rafraîchi).
    assert servers.get_server(sid).last_online is True


async def test_manual_requires_login(admin_client):
    keys.set_admin_password("admin-mdp")
    async with admin_client as c:
        r = await c.get("/admin/manual")
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


async def test_manual_rendered_with_screenshots(admin_client):
    """Le manuel (docs/manual.md) est rendu en HTML : titres, captures remappées vers
    /static/manual/, blocs Mermaid retirés."""
    keys.set_admin_password("admin-mdp")
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "admin-mdp"})
        r = await c.get("/admin/manual")
    assert r.status_code == 200
    assert "<h1>Manuel" in r.text and "<h2" in r.text
    assert 'src="/static/manual/01-dashboard.jpg"' in r.text
    assert "mermaid" not in r.text and "```" not in r.text
