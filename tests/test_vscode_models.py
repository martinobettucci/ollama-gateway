"""Gabarit VS Code (« point de terminaison personnalisé ») : SECRET réel + capacités RÉELLES.

Le gabarit proposé à la création d'une clé ne doit plus contenir de placeholder d'entrée VS Code
pour la clé (`${input:…}`) ni de capacités devinées : l'appel d'outils, la vision et la fenêtre de
contexte sont LUS sur le serveur d'exécution (`POST /api/show`), puis bornés par le plafond de
contexte de la clé.

Règle « chaque tâche a SES tests » : tests propres à cette unité (budget d'E/S `context.io_budget`,
sonde `servers.model_capabilities`, endpoint `GET /admin/keys/{id}/vscode-models`, gabarit rendu).
Le pendant E2E est `e2e/tests/vscode-template.spec.ts`.
"""
import json

import pytest

from app import context, keys, servers
from tests.conftest import admin_client, probe_via_fake  # noqa: F401 (fixtures)

PW = "admin-mdp"


async def _login(c):
    keys.set_admin_password(PW)
    await c.post("/admin/login", data={"password": PW})


# --- Budget entrée/sortie (pur) ---------------------------------------------------------------

def test_io_budget_reserves_output_within_model_window():
    """Fenêtre amont plus PETITE que le plafond de clé → c'est elle qui borne, sortie réservée."""
    max_in, max_out = context.io_budget(8192, 112 * 1024)
    assert max_out == 2048                     # un quart de 8192
    assert max_in == 6144                      # le reste
    assert max_in + max_out == 8192            # jamais plus que la fenêtre réelle


def test_io_budget_clamped_by_key_context_cap():
    """Fenêtre amont plus GRANDE que le plafond de clé → le plafond gagne (num_ctx le bornera)."""
    max_in, max_out = context.io_budget(262144, 112 * 1024)
    total = 112 * 1024
    assert max_out == 28672                    # un quart de 112k
    assert max_in == total - max_out


def test_io_budget_output_share_is_bounded():
    """La réserve de sortie ne descend pas sous 1k ni ne dépasse 32k."""
    assert context.io_budget(2048, 2048)[1] == context.OUTPUT_MIN
    assert context.io_budget(1024 * 1024, 1024 * 1024)[1] == context.OUTPUT_MAX


def test_io_budget_input_stays_under_the_413_margin():
    """L'entrée annoncée doit PASSER le garde-fou d'entrée, qui majore l'estimation de MARGIN."""
    limit = 1024 * 1024                        # plafond max : la marge devient contraignante
    max_in, _ = context.io_budget(limit, limit)
    assert context.with_margin(max_in) <= limit


def test_io_budget_without_upstream_window_falls_back_to_key_cap():
    """Fenêtre amont inconnue (`None`) → on s'en tient au plafond de la clé, sans rien inventer."""
    max_in, max_out = context.io_budget(None, 8 * 1024)
    assert max_in + max_out == 8 * 1024


# --- Lecture des capacités sur l'amont ---------------------------------------------------------

def test_context_length_read_from_declared_architecture():
    """`model_info` préfixe la fenêtre par l'architecture du GGUF."""
    assert servers._context_length(
        {"general.architecture": "qwen3", "qwen3.context_length": 262144}) == 262144


def test_context_length_falls_back_to_any_architecture_prefix():
    """Architecture non déclarée → n'importe quelle clé `*.context_length` fait l'affaire."""
    assert servers._context_length({"inconnue42.context_length": 4096}) == 4096
    assert servers._context_length({"general.parameter_count": 8_000_000_000}) is None
    assert servers._context_length(None) is None


def test_capabilities_read_from_declared_list():
    """`capabilities` publié par l'amont fait foi (Ollama ≥ 0.6)."""
    caps = servers._read_capabilities({"capabilities": ["completion", "tools", "vision"]})
    assert caps == {"tools": True, "vision": True, "thinking": False}


def test_capabilities_fall_back_to_template_and_families():
    """Sans `capabilities` (Ollama < 0.6) : `.Tools` dans le gabarit, projecteur dans les familles."""
    caps = servers._read_capabilities(
        {"template": "{{ if .Tools }}x{{ end }}", "details": {"families": ["mllama"]}})
    assert caps == {"tools": True, "vision": True, "thinking": False}
    assert servers._read_capabilities({}) == {"tools": False, "vision": False, "thinking": False}


async def test_model_capabilities_reads_real_values_per_model(probe_via_fake):
    """Chaque modèle ressort avec SES valeurs : outils/vision/fenêtre diffèrent d'un modèle à l'autre."""
    srv = servers.create_server("s", "http://fake")
    online, caps, err = await servers.model_capabilities(srv.id, ["demo:latest", "autre:latest"])
    assert online is True and err == ""
    by_id = {c["id"]: c for c in caps}
    # demo:latest publie `capabilities` (outils + vision), contexte 8k.
    assert by_id["demo:latest"] == {"id": "demo:latest", "known": True, "toolCalling": True,
                                    "vision": True, "thinking": False, "contextLength": 8192}
    # autre:latest ne publie PAS `capabilities` → déduit du gabarit `.Tools`, pas de vision, 256k.
    assert by_id["autre:latest"] == {"id": "autre:latest", "known": True, "toolCalling": True,
                                     "vision": False, "thinking": False, "contextLength": 262144}


async def test_model_capabilities_without_allowlist_uses_server_catalog(probe_via_fake):
    """Clé sans allowlist = tous les modèles → on interroge le CATALOGUE du serveur."""
    srv = servers.create_server("s", "http://fake")
    online, caps, _ = await servers.model_capabilities(srv.id, [])
    assert online is True
    assert {c["id"] for c in caps} == {"demo:latest", "autre:latest", "x/fakeflux:1b"}


async def test_model_capabilities_unknown_model_stays_conservative(probe_via_fake):
    """Modèle absent de l'amont (`/api/show` 404) → `known=False`, ni outils ni vision."""
    srv = servers.create_server("s", "http://fake")
    _, caps, _ = await servers.model_capabilities(srv.id, ["jamais-installé:9b"])
    assert caps == [{"id": "jamais-installé:9b", "known": False, "toolCalling": False,
                     "vision": False, "thinking": False, "contextLength": None}]


async def test_model_capabilities_disabled_server_reports_error():
    srv = servers.create_server("s", "http://fake")
    servers.set_enabled(srv.id, False)
    online, caps, err = await servers.model_capabilities(srv.id, ["demo:latest"])
    assert online is False and caps == [] and "désactivé" in err
    assert await servers.model_capabilities(None, []) == (False, [], "serveur introuvable")


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
    # 8k amont < 112k de plafond → borné par l'amont.
    assert (by_id["demo:latest"]["maxInputTokens"],
            by_id["demo:latest"]["maxOutputTokens"]) == (6144, 2048)
    assert by_id["demo:latest"]["toolCalling"] is True and by_id["demo:latest"]["vision"] is True
    # 256k amont > 112k de plafond → borné par la clé.
    assert (by_id["autre:latest"]["maxInputTokens"]
            + by_id["autre:latest"]["maxOutputTokens"]) == 112 * 1024
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
    assert m["maxInputTokens"] + m["maxOutputTokens"] == 4096


async def test_vscode_models_endpoint_is_guarded_and_404s(admin_client, probe_via_fake):
    """Endpoint LAN-only derrière la session admin ; clé inconnue → 404 explicite."""
    async with admin_client as c:
        anon = await c.get("/admin/keys/1/vscode-models")
        assert anon.status_code in (303, 401, 403)
        await _login(c)
        missing = await c.get("/admin/keys/9999/vscode-models")
    assert missing.status_code == 404 and missing.json()["models"] == []


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
