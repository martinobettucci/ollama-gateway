"""Familles d'API servies par un serveur d'exécution : catalogue d'endpoints + mapping chemin→famille.

Source de vérité **partagée** :
- `app/proxy.py` — `family_for_path()` applique l'allowlist d'API **par clé** : allow/forbid de
  **chemin** uniquement, **aucune validation de schéma** ;
- `app/servers.py::run_compat` — `CATALOG` des endpoints sondés pour la matrice de compatibilité.

Specs de référence (2026-07) : Ollama `docs/api.md` + `docs/openai.md` (compat OpenAI),
Anthropic Messages `/v1/messages` (+ `count_tokens`). La sonde ne teste que l'**accessibilité du
chemin** (servi vs 404) via un corps minimal `{}` — l'amont répond 400 *avant* toute génération.
Les endpoints **destructifs/mutants** (`pull`/`push`/`delete`/`create`/`copy`/`blobs`) sont
volontairement **exclus** : la matrice couvre la surface d'inférence/lecture réellement proxifiée.
"""

# Identifiants stables des familles (colonnes de la matrice, valeurs de l'allowlist par clé).
# Les familles « -image » sont des capacités de GÉNÉRATION D'IMAGES, distinctes du texte :
# - openai-image : endpoint dédié POST /v1/images/generations ;
# - ollama-image : PAS de chemin dédié — Ollama génère via POST /api/generate avec un modèle
#   d'image (préfixe `x/`). La capability est donc déduite du MODÈLE, pas seulement du chemin.
FAMILIES = ("ollama", "openai", "anthropic", "ollama-image", "openai-image")

# Familles de génération d'images (cases à cocher séparées côté clé).
IMAGE_FAMILIES = ("ollama-image", "openai-image")

FAMILY_LABELS = {
    "ollama": "Ollama natif",
    "openai": "OpenAI-compatible",
    "anthropic": "Anthropic Messages",
    "ollama-image": "Ollama image (x/…)",
    "openai-image": "OpenAI image",
}

# Préfixe des modèles d'IMAGE dans Ollama (namespace expérimental « x/ », ex. x/flux2-klein:4b).
IMAGE_MODEL_PREFIX = "x/"


def is_image_model(model: str | None) -> bool:
    """True si le modèle appartient au namespace image d'Ollama (préfixe `x/`)."""
    return isinstance(model, str) and model.startswith(IMAGE_MODEL_PREFIX)

# Endpoints sondés par famille : (méthode, chemin, libellé). Corps de sonde = {} pour les POST.
CATALOG: dict[str, list[tuple[str, str, str]]] = {
    "ollama": [
        ("GET", "/api/version", "version"),
        ("GET", "/api/tags", "liste des modèles"),
        ("GET", "/api/ps", "modèles chargés"),
        ("POST", "/api/show", "info modèle"),
        ("POST", "/api/generate", "génération"),
        ("POST", "/api/chat", "chat"),
        ("POST", "/api/embed", "embeddings"),
        ("POST", "/api/embeddings", "embeddings (legacy)"),
    ],
    "openai": [
        ("GET", "/v1/models", "liste des modèles"),
        ("POST", "/v1/chat/completions", "chat completions"),
        ("POST", "/v1/completions", "completions (legacy)"),
        ("POST", "/v1/embeddings", "embeddings"),
        ("POST", "/v1/responses", "responses"),
    ],
    "anthropic": [
        ("POST", "/v1/messages", "messages"),
        ("POST", "/v1/messages/count_tokens", "comptage de tokens"),
    ],
    "openai-image": [
        ("POST", "/v1/images/generations", "génération d'images"),
    ],
    "ollama-image": [
        # Pas de chemin dédié : Ollama génère via /api/generate + modèle `x/…`.
        ("POST", "/api/generate", "génération d'images (modèle x/…)"),
    ],
}

# Endpoints de listing : toujours autorisés quelle que soit l'allowlist d'API (ils sont déjà
# filtrés par l'allowlist de modèles de la clé). Évite de casser la découverte de modèles d'un
# SDK (ex. client Anthropic qui interroge /v1/models) restreint à une autre famille.
LISTING_PATHS = {"/api/tags", "/v1/models"}

# Endpoints de GESTION du catalogue de modèles d'Ollama : `pull`/`push`/`delete`/`create`/`copy`/
# `blobs`. Ils MUTENT l'état du serveur d'exécution partagé (télécharger un modèle géant = DoS
# disque, supprimer un modèle = indispo). La passerelle est un proxy d'INFÉRENCE : ces endpoints
# n'y ont pas leur place et sont refusés pour toute clé (ils échappaient sinon à l'allowlist de
# modèles, qui ne s'applique qu'aux corps portant un champ `model` — pull/delete utilisent `name`).
MANAGEMENT_PATHS = ("/api/pull", "/api/push", "/api/delete", "/api/create",
                    "/api/copy", "/api/blobs")


def is_management_path(path: str) -> bool:
    """True si `path` est un endpoint de gestion du catalogue (jamais proxifié)."""
    return path.rstrip("/") in MANAGEMENT_PATHS or path.startswith("/api/blobs/")


def family_for_path(path: str) -> str | None:
    """Famille d'API d'un chemin amont, ou None s'il n'appartient à aucune famille connue.

    Ordre important : `/v1/messages*` = Anthropic ; tout autre `/v1/*` = OpenAI-compat ;
    `/api/*` = Ollama natif.
    """
    if path.startswith("/api/"):
        return "ollama"
    if path.startswith("/v1/messages"):
        return "anthropic"
    if path.startswith("/v1/"):
        return "openai"
    return None


def capability_for_request(path: str, model: str | None) -> str | None:
    """Capability requise par une requête, **image comprise** (dépend du chemin ET du modèle) :

    - `POST /v1/images/*`  → `openai-image` (endpoint dédié) ;
    - `/api/*` avec un modèle `x/…` → `ollama-image` (Ollama génère l'image via /api/generate) ;
    - sinon → la famille texte du chemin (`family_for_path`).

    C'est cette capability que le proxy confronte à l'allowlist d'API de la clé.
    """
    if path.startswith("/v1/images"):
        return "openai-image"
    if path.startswith("/api/") and is_image_model(model):
        return "ollama-image"
    return family_for_path(path)
