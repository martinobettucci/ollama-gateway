# Rapport de compatibilité multi-API — passerelle Ollama

> Sonde exécutée le 2026-07-09 contre un serveur d'exécution de test (staging), Ollama
> **0.30.11**, modèle `ornith:9b` (capacités : `completion`, `tools`, `thinking`).
> **Aucun secret ni hôte réel n'est reproduit ici** (règle « surface publique = surface
> documentaire »). Le script reproductible est productisé dans la passerelle : voir
> « Matrice de compatibilité » dans le manuel.

## TL;DR pour le client « la passerelle ignore mes schémas de sortie structurée »

**La passerelle n'ignore rien.** Le corps de requête est relayé **octet pour octet** vers
l'amont (`app/proxy.py`) : `format` (Ollama) et `response_format` (OpenAI) arrivent intacts.
La sortie structurée **fonctionne** de bout en bout :

| Voie | Résultat | `content` renvoyé |
|------|----------|-------------------|
| `POST /api/chat` + `format: <schema>` | ✅ conforme | `{"name": "Bob", "age": 42}` |
| `POST /v1/chat/completions` + `response_format: json_schema` | ✅ conforme | `{"name": "Carol", "age": 25}` |
| `POST /api/generate` + `format: <schema>` | ⚠️ **piège** | `response: ""` — le JSON part dans `thinking` |

**Le vrai piège** : `ornith:9b` est un modèle **à raisonnement** (`thinking`). Sur
`/api/generate` avec un schéma, le modèle a placé le JSON **dans le champ `thinking`** et a
laissé `response` **vide**. Un client qui lit `response` voit une chaîne vide et conclut « le
schéma est ignoré » — alors que la passerelle et le schéma ont parfaitement fonctionné, c'est
le **routage sortie/raisonnement du modèle** qui est en cause.

**Remède côté client** (aucun changement passerelle requis) : sur un modèle *thinking*,
soit désactiver le raisonnement (`"think": false` en natif ; endpoint chat plutôt que
generate), soit lire le champ `thinking` en repli quand `response`/`content` est vide.
Il n'y a **aucune raison** de passer d'un format JSON à un format ligne-à-ligne.

## Matrice observée (25 sondes)

Statut = code HTTP réellement renvoyé par l'amont **et relayé tel quel** par la passerelle.

### Ollama natif (`/api/*`)

| Endpoint | Option testée | Statut | Verdict |
|----------|---------------|:------:|---------|
| `GET /api/version` | — | 200 | ✅ servi |
| `GET /api/tags` | liste modèles | 200 | ✅ servi |
| `GET /api/ps` | modèles chargés | 200 | ✅ servi |
| `POST /api/show` | info modèle | 200 | ✅ servi |
| `POST /api/generate` | `stream:false` | 200 | ✅ servi |
| `POST /api/generate` | **`format` schema** | 200 | ⚠️ JSON dans `thinking` (voir piège) |
| `POST /api/generate` | `stream:true` (NDJSON) | 200 | ✅ servi |
| `POST /api/chat` | `stream:false` | 200 | ✅ servi |
| `POST /api/chat` | **`format` schema** | 200 | ✅ conforme |
| `POST /api/chat` | `tools` | 200 | ✅ servi |
| `POST /api/chat` | `think:true` | 200 | ✅ servi |
| `POST /api/embed` | — | 501 | ⛔ modèle sans embeddings (amont) |
| `POST /api/embeddings` | legacy | 500 | ⛔ modèle sans embeddings (amont) |

### OpenAI-compatible (`/v1/*`)

| Endpoint | Option testée | Statut | Verdict |
|----------|---------------|:------:|---------|
| `GET /v1/models` | — | 200 | ✅ servi |
| `POST /v1/chat/completions` | basique | 200 | ✅ servi |
| `POST /v1/chat/completions` | `response_format: json_object` | 200 | ✅ servi |
| `POST /v1/chat/completions` | **`response_format: json_schema`** | 200 | ✅ conforme |
| `POST /v1/chat/completions` | `tools` | 200 | ✅ servi |
| `POST /v1/chat/completions` | `stream:true` (SSE) | 200 | ✅ servi |
| `POST /v1/completions` | legacy | 200 | ✅ servi |
| `POST /v1/embeddings` | — | 501 | ⛔ modèle sans embeddings (amont) |

### Anthropic Messages (`/v1/messages`)

| Endpoint | Option testée | Statut | Verdict |
|----------|---------------|:------:|---------|
| `POST /v1/messages` | auth `x-api-key` | 200 | ✅ servi (clé strippée avant amont) |
| `POST /v1/messages` | auth `Bearer` | 200 | ✅ servi |
| `POST /v1/messages` | `tools` | 200 | ✅ servi |
| `POST /v1/messages` | `stream:true` (SSE) | 200 | ✅ servi |

## Conclusions

1. **La passerelle est transparente au corps** : elle ne réécrit jamais `format` /
   `response_format` / `tools` / `stream`. Preuve : les statuts amont 500/501 (embeddings)
   sont relayés à l'identique.
2. **Les 3 familles d'API répondent** sur ce serveur : Ollama natif, OpenAI-compat, Anthropic.
   Anthropic accepte `x-api-key` **et** `Bearer` (la clé cliente est strippée dans les deux cas).
3. **Sortie structurée = OK**, avec la réserve *thinking* documentée ci-dessus.
4. **Embeddings indisponibles** sur ce modèle/serveur (démarrer l'amont avec `--embeddings`) —
   limite **amont**, pas passerelle.

## Reproductibilité

Cette sonde est productisée : chaque serveur d'exécution ajouté peut être testé depuis le panel
(« Tester la compatibilité »), le résultat est **stocké** et **affiché sous forme de matrice**.
Le test vérifie l'**accessibilité des chemins** (servi / non servi), **sans** valider les schémas
de réponse. Voir `docs/manual.md` § Matrice de compatibilité et `app/servers.py::run_compat`.
