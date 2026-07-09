"""Génération d'images : capability image (ollama-image/openai-image), allowlist de modèles d'image
séparée (x/…), gating proxy, et relais de test `try_image`."""
from app import apis, keys, servers
from tests.conftest import admin_client, probe_via_fake, proxy_client  # noqa: F401,F811

IMG = "x/fakeflux:1b"


def _auth(k):
    return {"authorization": f"Bearer {k}"}


# --- Unitaires ------------------------------------------------------------------------------

def test_is_image_model_and_capability():
    assert apis.is_image_model(IMG) and not apis.is_image_model("demo:latest")
    assert apis.capability_for_request("/v1/images/generations", IMG) == "openai-image"
    assert apis.capability_for_request("/api/generate", IMG) == "ollama-image"
    assert apis.capability_for_request("/api/generate", "demo:latest") == "ollama"
    assert set(apis.IMAGE_FAMILIES) <= set(apis.FAMILIES)


def test_image_models_roundtrip():
    rec, _ = keys.create_key("k", [], None, None, image_models=[IMG, "x/other:2b"])
    assert keys.get_key(rec.id).image_models == [IMG, "x/other:2b"]
    keys.update_key(rec.id, "k", [], None, None, "", image_models=[IMG])
    assert keys.get_key(rec.id).image_models == [IMG]
    keys.update_key(rec.id, "k", [], None, None, "", image_models=None)  # None = inchangé
    assert keys.get_key(rec.id).image_models == [IMG]


# --- Proxy : gating capability + modèle d'image ---------------------------------------------

async def test_ollama_image_passes_with_capability(fake_upstream):
    _, key = keys.create_key("k", [], None, None, key_apis=["ollama-image"])
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/generate", headers=_auth(key),
                         json={"model": IMG, "prompt": "a circle", "stream": False})
    assert r.status_code == 200 and "image" in r.text


async def test_ollama_image_forbidden_without_capability(fake_upstream):
    # Clé texte-only : le modèle x/ sur /api/generate exige la capability ollama-image → 403.
    _, key = keys.create_key("k", [], None, None, key_apis=["ollama"])
    async with proxy_client(fake_upstream) as c:
        r = await c.post("/api/generate", headers=_auth(key),
                         json={"model": IMG, "prompt": "x", "stream": False})
    assert r.status_code == 403


async def test_image_model_allowlist_separate_from_text(fake_upstream):
    # image_models restreint ≠ models texte : x/autre refusé, texte demo autorisé.
    _, key = keys.create_key("k", [], None, None, key_apis=["ollama", "ollama-image"],
                             image_models=[IMG])
    async with proxy_client(fake_upstream) as c:
        ok = await c.post("/api/generate", headers=_auth(key),
                          json={"model": IMG, "prompt": "x", "stream": False})
        bad = await c.post("/api/generate", headers=_auth(key),
                           json={"model": "x/nope:1b", "prompt": "x", "stream": False})
        txt = await c.post("/api/chat", headers=_auth(key),
                           json={"model": "demo:latest"})
    assert ok.status_code == 200 and bad.status_code == 403 and txt.status_code == 200


async def test_openai_image_endpoint_gated(fake_upstream):
    _, allow = keys.create_key("a", [], None, None, key_apis=["openai-image"])
    _, deny = keys.create_key("d", [], None, None, key_apis=["openai"])  # texte only
    async with proxy_client(fake_upstream) as c:
        ok = await c.post("/v1/images/generations", headers=_auth(allow),
                          json={"model": IMG, "prompt": "x"})
        ko = await c.post("/v1/images/generations", headers=_auth(deny),
                          json={"model": IMG, "prompt": "x"})
    assert ok.status_code == 200 and "b64_json" in ok.text and ko.status_code == 403


# --- Relais de test (« Essayer » onglet Image) ----------------------------------------------

async def test_try_image_ollama(probe_via_fake):
    srv = servers.create_server("s", "http://fake")
    b64, err = await servers.try_image(srv.id, "ollama-image", IMG, "a red circle")
    assert not err and b64.startswith("iVBOR")  # base64 PNG


async def test_try_image_openai(probe_via_fake):
    srv = servers.create_server("s", "http://fake")
    b64, err = await servers.try_image(srv.id, "openai-image", IMG, "a red circle")
    assert not err and b64.startswith("iVBOR")


async def test_try_image_with_input_image(probe_via_fake):
    srv = servers.create_server("s", "http://fake")
    b64, err = await servers.try_image(srv.id, "ollama-image", IMG, "edit this", "QUJD")
    assert not err and b64


# --- Admin : route try-image + rendu du formulaire clé --------------------------------------

async def test_admin_try_image_route(admin_client, probe_via_fake):
    keys.set_admin_password("pw")
    srv = servers.create_server("s", "http://fake")
    rec, _ = keys.create_key("k", [], None, None, server_id=srv.id,
                             key_apis=["ollama-image"], image_models=[IMG])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "pw"})
        r = await c.post(f"/admin/keys/{rec.id}/try-image",
                         json={"prompt": "a red circle", "model": IMG, "api": "ollama-image",
                               "image": "data:image/png;base64,QUJD"})
        assert r.status_code == 200
        assert r.json()["image"].startswith("data:image/png;base64,")
        # Modèle d'image hors allowlist → 403.
        bad = await c.post(f"/admin/keys/{rec.id}/try-image",
                           json={"prompt": "x", "model": "x/nope:1b", "api": "ollama-image"})
        assert bad.status_code == 403


async def test_key_form_renders_image_pickers(admin_client):
    keys.set_admin_password("pw")
    rec, _ = keys.create_key("k", [], None, None, key_apis=["ollama-image"], image_models=[IMG])
    async with admin_client as c:
        await c.post("/admin/login", data={"password": "pw"})
        r = await c.get(f"/admin/keys/{rec.id}")
    assert r.status_code == 200
    assert 'data-testid="api-image-checks"' in r.text
    assert 'data-testid="image-model-checks"' in r.text
    assert 'data-testid="tab-image"' in r.text  # onglet Image visible (capacité activée)
