"""Paramètres des modèles : lecture sur l'amont, exposition au gabarit VS Code et au sélecteur.

Trois familles d'amont, un seul résultat : la fiche native Ollama (`POST /api/show`, servie par
Ollama et ollama.cpp) d'abord, `GET /v1/models` en repli pour un amont seulement
OpenAI-compatible. Ce qui est annoncé au client est ensuite **borné par la clé** (`io_budget`).

Règle « chaque tâche a SES tests » : tests propres à cette unité (`context.io_budget`,
`servers.read_specs`/`model_specs`, endpoints `GET /admin/servers/{id}/models` et
`GET /admin/keys/{id}/vscode-models`, gabarit et sélecteur rendus). Pendant E2E :
`e2e/tests/vscode_template.spec.ts`.
"""
import json

import pytest

from app import context, keys, servers
from tests.conftest import admin_client, probe_via_fake  # noqa: F401 (fixtures)

PW = "admin-mdp"


async def _login(c):
    keys.set_admin_password(PW)
    await c.post("/admin/login", data={"password": PW})


# --- Bornes annoncées (pur) --------------------------------------------------------------------

def test_io_budget_announces_the_model_window():
    """Fenêtre du modèle plus PETITE que le plafond de clé → c'est elle qui est annoncée."""
    assert context.io_budget(8192, None, 112 * 1024) == (8192, 8192)


def test_io_budget_clamped_by_the_key_context_cap():
    """Fenêtre du modèle plus GRANDE que le plafond → le plafond gagne (le proxy refuserait au-delà).

    L'entrée descend d'un cran sous le plafond : le garde-fou compare une estimation MAJORÉE de
    `MARGIN`, donc annoncer le plafond brut ferait refuser en 413 ce qu'on venait d'autoriser."""
    max_in, max_out = context.io_budget(262144, None, 112 * 1024)
    assert max_in < 112 * 1024
    assert context.with_margin(max_in) <= 112 * 1024
    assert max_out == context.OUTPUT_DEFAULT


def test_io_budget_uses_the_declared_output():
    """Sortie déclarée par le serveur ⇒ reprise telle quelle, sinon la valeur par défaut."""
    assert context.io_budget(8192, 512, 112 * 1024)[1] == 512
    assert context.io_budget(262144, None, 112 * 1024)[1] == context.OUTPUT_DEFAULT
    assert context.io_budget(262144, -1, 112 * 1024)[1] == context.OUTPUT_DEFAULT   # sentinelle


def test_io_budget_output_never_exceeds_the_window():
    """Une sortie plus large que la fenêtre n'a pas de sens : elle est ramenée à la fenêtre."""
    assert context.io_budget(4096, 999999, 112 * 1024) == (4096, 4096)
    assert context.io_budget(4096, None, 112 * 1024)[1] == 4096   # défaut 16k > fenêtre 4k


def test_io_budget_without_model_window_falls_back_to_key_cap():
    """Fenêtre amont inconnue → on s'en tient au plafond de la clé, sans rien inventer."""
    max_in, _ = context.io_budget(None, None, 8 * 1024)
    assert 0 < max_in <= 8 * 1024


# --- Lecture d'une fiche amont (pur, toutes formes) --------------------------------------------

def test_read_specs_from_ollama_show():
    """Fiche native Ollama : `capabilities` fait foi, fenêtre sous `<arch>.context_length`."""
    assert servers.read_specs({
        "capabilities": ["completion", "tools", "vision"],
        "model_info": {"general.architecture": "llama", "llama.context_length": 8192},
    }) == {"toolCalling": True, "vision": True, "contextLength": 8192, "maxOutput": None}


def test_read_specs_falls_back_to_template_and_families():
    """Sans `capabilities` (Ollama < 0.6) : `.Tools` dans le gabarit, projecteur dans les familles."""
    assert servers.read_specs({
        "template": "{{ if .Tools }}x{{ end }}", "details": {"families": ["mllama"]},
    }) == {"toolCalling": True, "vision": True, "contextLength": None, "maxOutput": None}
    assert servers.read_specs({}) == {"toolCalling": False, "vision": False,
                                      "contextLength": None, "maxOutput": None}


def test_read_specs_modelfile_parameters_win_over_architecture():
    """`num_ctx` = fenêtre RÉELLEMENT servie ⇒ prime sur le maximum théorique de l'architecture."""
    specs = servers.read_specs({
        "parameters": 'stop  "<|end|>"\nnum_ctx    2048\nnum_predict   512',
        "model_info": {"general.architecture": "flux", "flux.context_length": 4096}})
    assert specs["contextLength"] == 2048 and specs["maxOutput"] == 512


def test_read_specs_from_openai_compatible_entry():
    """Fiche `/v1/models` d'un amont OpenAI-compatible : autres noms, même résultat."""
    assert servers.read_specs({
        "id": "m", "max_model_len": 32768, "max_output_tokens": 4096,
        "capabilities": ["completion", "tools"],
    }) == {"toolCalling": True, "vision": False, "contextLength": 32768, "maxOutput": 4096}
    # llama-server imbrique ses métadonnées sous `meta`.
    assert servers.read_specs({"meta": {"n_ctx_train": 4096}})["contextLength"] == 4096


def test_read_specs_ignores_sentinels():
    """`num_predict: -1` (illimité) / `-2` (remplir le contexte) ne sont pas des bornes."""
    assert servers.read_specs({"parameters": "num_predict -1"})["maxOutput"] is None


# --- Sonde d'un serveur d'exécution ------------------------------------------------------------

async def test_model_specs_reads_real_values_per_model(probe_via_fake):
    """Chaque modèle ressort avec SES valeurs : elles diffèrent d'un modèle à l'autre."""
    srv = servers.create_server("s", "http://fake")
    online, specs, err = await servers.model_specs(srv.id, ["demo:latest", "autre:latest"])
    assert online is True and err == ""
    by_id = {s["id"]: s for s in specs}
    assert by_id["demo:latest"] == {"id": "demo:latest", "known": True, "toolCalling": True,
                                    "vision": True, "contextLength": 8192, "maxOutput": None}
    assert by_id["autre:latest"] == {"id": "autre:latest", "known": True, "toolCalling": True,
                                     "vision": False, "contextLength": 262144, "maxOutput": None}


async def test_model_specs_reads_declared_modelfile_bounds(probe_via_fake):
    """Le modèle qui déclare `num_ctx`/`num_predict` ressort avec CES valeurs, pas celles du GGUF."""
    srv = servers.create_server("s", "http://fake")
    _, specs, _ = await servers.model_specs(srv.id, ["x/fakeflux:1b"])
    assert specs[0]["contextLength"] == 2048 and specs[0]["maxOutput"] == 512


async def test_model_specs_falls_back_to_openai_models(probe_via_fake):
    """Modèle absent de `/api/show` mais présent dans `/v1/models` : c'est le repli OpenAI-compat."""
    srv = servers.create_server("s", "http://fake")
    _, specs, _ = await servers.model_specs(srv.id, ["openai-only:latest"])
    assert specs[0] == {"id": "openai-only:latest", "known": True, "toolCalling": True,
                        "vision": False, "contextLength": 32768, "maxOutput": 4096}


async def test_model_specs_without_allowlist_describes_the_catalog(probe_via_fake):
    """Clé sans allowlist = tous les modèles → on décrit le CATALOGUE du serveur."""
    srv = servers.create_server("s", "http://fake")
    online, specs, _ = await servers.model_specs(srv.id)
    assert online is True
    assert {s["id"] for s in specs} == {"demo:latest", "autre:latest", "x/fakeflux:1b",
                                        "embed-mini:latest"}


async def test_model_specs_falls_back_to_the_ollama_catalog(probe_via_fake):
    """Modèle sans fiche `/api/show` mais listé par `/api/tags` avec ses capacités.

    C'est le comportement d'ollama.cpp, qui joint `capabilities` à chaque entrée du catalogue —
    seule source pour un modèle fraîchement tiré, que la fiche détaillée ne décrit pas encore."""
    from devfixtures import fake_ollama
    fake_ollama.reset_models()
    fake_ollama.MODELS.append("pulled:1b")
    try:
        srv = servers.create_server("s", "http://fake")
        _, specs, _ = await servers.model_specs(srv.id, ["pulled:1b"])
    finally:
        fake_ollama.reset_models()
    assert specs[0] == {"id": "pulled:1b", "known": True, "toolCalling": True,
                        "vision": False, "contextLength": None, "maxOutput": None}


async def test_model_specs_unknown_model_stays_conservative(probe_via_fake):
    """Modèle inconnu des DEUX voies → `known=False`, ni outils ni vision, aucune fenêtre."""
    srv = servers.create_server("s", "http://fake")
    _, specs, _ = await servers.model_specs(srv.id, ["jamais-installé:9b"])
    assert specs == [{"id": "jamais-installé:9b", "known": False, "toolCalling": False,
                      "vision": False, "contextLength": None, "maxOutput": None}]


async def test_model_specs_disabled_server_reports_error():
    srv = servers.create_server("s", "http://fake")
    servers.set_enabled(srv.id, False)
    online, specs, err = await servers.model_specs(srv.id, ["demo:latest"])
    assert online is False and specs == [] and "désactivé" in err
    assert await servers.model_specs(None) == (False, [], "serveur introuvable")


# --- Endpoint admin ----------------------------------------------------------------------------

async def test_vscode_models_endpoint_returns_real_capabilities(admin_client, probe_via_fake):
    """L'endpoint compose capacités amont + plafond de contexte de la clé, SANS aucun secret."""
    srv = servers.create_server("s", "http://fake")
    rec, secret = keys.create_key(label="c", origins=[], monthly_token_cap=None, rpm_limit=None,
                                  server_id=srv.id,
                                  models=["demo:latest", "autre:latest"],
                                  max_context_tokens=112 * 1024)
    async with admin_client as c:
        await _login(c)
        r = await c.get(f"/admin/keys/{rec.id}/vscode-models")
    assert r.status_code == 200
    body = r.json()
    assert body["online"] is True
    by_id = {m["id"]: m for m in body["models"]}
    # 8k amont < 112k de plafond → c'est la fenêtre du modèle qui est annoncée.
    assert (by_id["demo:latest"]["maxInputTokens"],
            by_id["demo:latest"]["maxOutputTokens"]) == (8192, 8192)
    assert by_id["demo:latest"]["toolCalling"] is True and by_id["demo:latest"]["vision"] is True
    # 256k amont > 112k de plafond → borné par la clé (et d'un cran sous, pour passer le 413).
    assert context.with_margin(by_id["autre:latest"]["maxInputTokens"]) <= 112 * 1024
    assert by_id["autre:latest"]["maxOutputTokens"] == context.OUTPUT_DEFAULT
    assert by_id["autre:latest"]["vision"] is False
    assert secret not in r.text                      # jamais de secret dans la réponse


async def test_vscode_models_endpoint_respects_key_context_cap(admin_client, probe_via_fake):
    """Un plafond de clé PLUS PETIT que la fenêtre du modèle borne bien ce qui est annoncé."""
    srv = servers.create_server("s", "http://fake")
    rec, _ = keys.create_key(label="petite", origins=[], monthly_token_cap=None, rpm_limit=None,
                             server_id=srv.id, models=["demo:latest"],
                             max_context_tokens=4096)
    async with admin_client as c:
        await _login(c)
        body = (await c.get(f"/admin/keys/{rec.id}/vscode-models")).json()
    m = body["models"][0]
    assert m["maxInputTokens"] <= 4096 and m["maxOutputTokens"] <= 4096
    assert context.with_margin(m["maxInputTokens"]) <= 4096


async def test_vscode_models_endpoint_honours_declared_bounds(admin_client, probe_via_fake):
    """Fenêtre et sortie déclarées par l'amont traversent jusqu'au gabarit."""
    srv = servers.create_server("s", "http://fake")
    rec, _ = keys.create_key(label="declaree", origins=[], monthly_token_cap=None, rpm_limit=None,
                             server_id=srv.id, image_models=["x/fakeflux:1b"],
                             max_context_tokens=112 * 1024)
    async with admin_client as c:
        await _login(c)
        body = (await c.get(f"/admin/keys/{rec.id}/vscode-models")).json()
    m = body["models"][0]
    # `num_ctx 2048` / `num_predict 512` du Modelfile : ni le maximum du GGUF (4096), ni la sortie
    # par défaut (16k) — ces valeurs ne peuvent venir que de la déclaration de l'amont.
    assert (m["maxInputTokens"], m["maxOutputTokens"]) == (2048, 512)


async def test_vscode_models_endpoint_is_guarded_and_404s(admin_client, probe_via_fake):
    """Endpoint LAN-only derrière la session admin ; clé inconnue → 404 explicite."""
    async with admin_client as c:
        anon = await c.get("/admin/keys/1/vscode-models")
        assert anon.status_code in (303, 401, 403)
        await _login(c)
        missing = await c.get("/admin/keys/9999/vscode-models")
    assert missing.status_code == 404 and missing.json()["models"] == []


# --- Sélecteur de modèles (formulaire de création de clé) ---------------------------------------

async def test_server_models_endpoint_carries_specs(admin_client, probe_via_fake):
    """La sonde du sélecteur remonte les paramètres, pas seulement les noms : on choisit informé."""
    srv = servers.create_server("s", "http://fake")
    async with admin_client as c:
        await _login(c)
        body = (await c.get(f"/admin/servers/{srv.id}/models")).json()
    assert body["online"] is True
    assert "demo:latest" in body["models"]                    # forme historique préservée
    by_id = {s["id"]: s for s in body["specs"]}
    assert by_id["demo:latest"]["toolCalling"] is True
    assert by_id["demo:latest"]["vision"] is True
    assert by_id["demo:latest"]["contextLength"] == 8192
    assert by_id["autre:latest"]["vision"] is False


async def test_model_picker_renders_specs(admin_client, probe_via_fake):
    """Le sélecteur affiche les paramètres à côté de chaque case (libellés i18n, pas de valeur en dur)."""
    async with admin_client as c:
        await _login(c)
        page = await c.get("/admin")
    # Les libellés viennent du catalogue i18n (attributs rendus serveur) ; les pastilles elles-
    # mêmes sont posées par le script au retour de la sonde — leur rendu réel est couvert en E2E.
    assert 'data-tools="outils"' in page.text and 'data-vision="vision"' in page.text
    assert "dataset.testid = 'model-spec'" in page.text
    assert "/admin/servers/' + target + '/models" in page.text


# --- Gabarit rendu -----------------------------------------------------------------------------

async def test_dashboard_template_embeds_real_secret_not_vscode_input(admin_client, probe_via_fake):
    """Après création, la modale porte le SECRET réel — plus de placeholder `${input:…}`."""
    srv = servers.create_server("s", "http://fake")
    async with admin_client as c:
        await _login(c)
        await c.post("/admin/keys", data={"label": "vscode-client", "server_id": str(srv.id),
                                          "model_check": "demo:latest"})
        page = await c.get("/admin")
    assert "${input:chat.lm.secret" not in page.text
    rec = keys.list_keys()[0]
    assert f"/admin/keys/' + keyId" in page.text          # capacités lues sur l'amont
    assert json.dumps(rec.id) in page.text
    # Le secret réel est bien injecté (même valeur que le flash « à copier maintenant »).
    assert page.text.count('data-testid="created-secret"') == 1
    # `apiType` aligné sur la voie OpenAI-compat réellement empruntée par l'éditeur.
    assert '"apiType": "chat-completions"' in page.text


async def test_env_vars_expose_the_key_context_cap(admin_client, probe_via_fake):
    """Le plafond de contexte part aussi dans les variables d'environnement (voie Ollama).

    C'est la seule variable STANDARD portant un paramètre de modèle : OpenAI et Anthropic n'ont
    pas d'équivalent, on n'en invente donc pas pour eux."""
    srv = servers.create_server("s", "http://fake")
    async with admin_client as c:
        await _login(c)
        await c.post("/admin/keys", data={"label": "ctx-env", "server_id": str(srv.id),
                                          "max_context_tokens": "8k"})
        page = await c.get("/admin")
    assert "OLLAMA_CONTEXT_LENGTH=" in page.text
    assert f"const ctx = {8 * 1024};" in page.text
    assert "OPENAI_CONTEXT_LENGTH" not in page.text and "ANTHROPIC_CONTEXT" not in page.text


async def test_dashboard_modal_has_two_independent_copy_blocks(admin_client, probe_via_fake):
    """Le gabarit VS Code est une zone copiable SÉPARÉE : sa propre sortie et son propre bouton."""
    srv = servers.create_server("s", "http://fake")
    async with admin_client as c:
        await _login(c)
        await c.post("/admin/keys", data={"label": "deux-blocs", "server_id": str(srv.id)})
        page = await c.get("/admin")
    for testid in ("env-output", "env-copy", "env-vscode-output", "env-vscode-copy"):
        assert f'data-testid="{testid}"' in page.text, testid
    # Le bloc VS Code est masqué tant qu'il n'est pas demandé, mais existe déjà dans le DOM.
    assert 'id="env-vscode-block" data-testid="env-vscode-block" hidden' in page.text


async def test_reissue_flash_carries_key_id_for_capabilities(admin_client, probe_via_fake):
    """La réémission ouvre la MÊME modale : elle doit aussi porter l'id de clé (sinon pas de sonde)."""
    srv = servers.create_server("s", "http://fake")
    rec, _ = keys.create_key(label="c", origins=[], monthly_token_cap=None, rpm_limit=None,
                             server_id=srv.id, models=["demo:latest"])
    async with admin_client as c:
        await _login(c)
        await c.post(f"/admin/keys/{rec.id}/reissue")
        page = await c.get("/admin")
    assert f"const keyId = {rec.id};" in page.text
