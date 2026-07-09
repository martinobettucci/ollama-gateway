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
FAMILIES = ("ollama", "openai", "anthropic")

FAMILY_LABELS = {
    "ollama": "Ollama natif",
    "openai": "OpenAI-compatible",
    "anthropic": "Anthropic Messages",
}

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
}

# Endpoints de listing : toujours autorisés quelle que soit l'allowlist d'API (ils sont déjà
# filtrés par l'allowlist de modèles de la clé). Évite de casser la découverte de modèles d'un
# SDK (ex. client Anthropic qui interroge /v1/models) restreint à une autre famille.
LISTING_PATHS = {"/api/tags", "/v1/models"}


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
