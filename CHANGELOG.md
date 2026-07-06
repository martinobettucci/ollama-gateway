# Changelog — ollama-gateway

Deux chapitres : **`[Non publié]`** (tampon des changements pas encore déployés en prod) puis
**`[Publié]`** (ce qui tourne réellement sur la Jetson). Toute nouvelle entrée va sous `[Non publié]`.
Surface publique ⇒ **zéro secret** (clés, tokens, hôtes/IP internes).

## [Non publié]

### Ajouté
- **Passerelle complète de gestion de clés Ollama** (première version).
  - Proxy d'inférence (`app/proxy.py`) : auth par clé `Authorization: Bearer`, restriction
    d'origine par clé (IP/CIDR), quotas (plafond mensuel de tokens + rate-limit req/min),
    journalisation d'usage par requête, streaming intégral (NDJSON/SSE) avec strip de la clé
    avant l'amont, proxy de **tous** les endpoints (`/api/*`, `/v1/*`) et `/_proxy_health`.
  - Panel d'admin web LAN-only (`app/admin.py`, Jinja) : login mot de passe, CRUD des clés
    (création avec secret affiché une seule fois, activation/désactivation, suppression, édition
    des origines et quotas), dashboard d'usage (totaux + détail par clé + dernières erreurs).
  - Stockage **SQLite** (WAL) : `api_keys` (clé hachée), `key_origins`, `key_quotas`,
    `usage_events` (append-only), `admin_auth`. Migrations idempotentes (`app/db.py`).
  - Dockerisation dev/staging/prod + lanceurs `runDev`/`runStaging`/`runProd` ; dev
    self-contained/self-seeded (faux upstream Ollama, clé + admin de démo).
  - **Caddy** avec module DNS Scaleway (`Dockerfile.caddy`) : TLS `llm.lelabs.tech` par challenge
    DNS-01 ; staging avec `tls internal` pour valider le routage localement.
  - Import d'une clé existante par valeur (migration) via `python -m app.bootstrap import-key`
    (origine paramétrable), sans jamais écrire la clé dans le repo.
  - Tests : 31 unitaires/intégration (pytest) + 3 E2E Playwright (admin UI + proxy), captures.

## [Publié]

_Rien à publier pour le moment…_
