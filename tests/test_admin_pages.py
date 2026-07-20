"""Rendu des pages admin (dashboard, clé, serveurs, cibles) après les ajouts Phase 8, et
routes CRUD des cibles. Garantit qu'aucune erreur de template n'est introduite et que les
nouveaux champs (API, expiration, cible, filtres) sont bien présents."""
from app import keys, targets
from tests.conftest import admin_client  # noqa: F401 (fixture)

PW = "admin-mdp"


async def _login(c):
    keys.set_admin_password(PW)
    await c.post("/admin/login", data={"password": PW})


async def test_dashboard_renders_filters_and_expiry(admin_client):
    async with admin_client as c:
        await _login(c)
        keys.create_key("client-acme", [], None, None)
        r = await c.get("/admin")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="key-search"' in body           # F4 recherche
    assert 'data-testid="key-filters"' in body
    assert 'data-testid="expiry-fields"' in body         # F3 champs d'expiration
    assert 'data-testid="target-select"' in body         # F2 sélecteur de cible
    assert 'data-testid="api-checks"' in body            # F1 cases d'API


async def test_targets_crud_flow(admin_client):
    async with admin_client as c:
        await _login(c)
        # page cibles rendue avec la cible par défaut
        page = await c.get("/admin/targets")
        assert page.status_code == 200 and "Cibles publiques" in page.text
        # création
        await c.post("/admin/targets", data={"name": "prod", "base_url": "https://llm.example:8443"})
        t = [x for x in targets.list_targets() if x.name == "prod"][0]
        assert t.base_url == "https://llm.example:8443"
        # mise à jour
        await c.post(f"/admin/targets/{t.id}",
                     data={"name": "prod2", "base_url": "https://llm2.example:8443"})
        assert targets.get_target(t.id).name == "prod2"
        # suppression (aucune clé rattachée)
        await c.post(f"/admin/targets/{t.id}/delete")
        assert targets.get_target(t.id) is None


async def test_create_key_with_apis_target_expiry(admin_client):
    async with admin_client as c:
        await _login(c)
        tid = targets.default_id(__import__("app").db.connect())
        await c.post("/admin/keys", data={
            "label": "trial", "api_check": ["ollama", "openai"], "target_id": str(tid),
            "total_token_cap": "10000", "total_request_cap": "50",
            "expires_at": "2999-01-01T12:00", "idle_expiry_days": "14"})
    rec = [k for k in keys.list_keys() if k.label == "trial"][0]
    got = keys.get_key(rec.id)
    assert set(got.apis) == {"ollama", "openai"}
    assert got.total_token_cap == 10000 and got.total_request_cap == 50
    assert got.idle_expiry_days == 14 and got.expires_at == "2999-01-01 12:00:00"


async def test_key_detail_page_renders(admin_client):
    async with admin_client as c:
        await _login(c)
        rec, _ = keys.create_key("k", [], None, None, key_apis=["anthropic"])
        r = await c.get(f"/admin/keys/{rec.id}")
    assert r.status_code == 200
    assert 'data-testid="api-checks"' in r.text and 'data-testid="expiry-fields"' in r.text


async def test_footer_attribution_and_p2enjoy_link(admin_client):
    """Le pied de page d'attribution P2Enjoy (lien vers le site) apparaît sur les pages,
    y compris la page de login (déconnecté) — première chose que voit un nouvel utilisateur."""
    keys.set_admin_password(PW)
    async with admin_client as c:
        login = await c.get("/admin/login")            # déconnecté
        await c.post("/admin/login", data={"password": PW})
        dash = await c.get("/admin")                    # connecté
    for r in (login, dash):
        assert r.status_code == 200
        assert 'data-testid="app-footer"' in r.text
        assert "Made proudly with AI by" in r.text
        assert 'href="https://p2enjoy.studio"' in r.text
        assert 'rel="noopener noreferrer"' in r.text
