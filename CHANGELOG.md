# Changelog — ollama-gateway

Deux chapitres : **`[Non publié]`** (tampon des changements pas encore déployés en prod) puis
**`[Publié]`** (ce qui tourne réellement en production). Toute nouvelle entrée va sous `[Non publié]`.
Surface publique ⇒ **zéro secret** (clés, tokens, hôtes/IP internes).

## [Non publié]

- **Panel d'admin restylé selon la charte graphique P2Enjoy** : thème clair, cartes blanches
  arrondies avec codage couleur par catégorie (bleu = clés, vert = usage, jaune = tokens,
  rouge = erreurs), navigation en pilules, icônes vectorielles lucide, écrans de connexion et
  d'initialisation avec bandeau dégradé. Accessibilité renforcée (focus clavier visible,
  contrastes AA, états vides explicites, `prefers-reduced-motion`).
- **Tests E2E déterministes** : la base dédiée aux tests est supprimée puis re-seedée à chaque
  run (plus de résidus entre exécutions) ; capture de l'écran de connexion ajoutée aux
  références visuelles.
- **Documentation** : nouveau manuel public (`docs/manual.md`, schémas Mermaid), journal des
  décisions (`docs/JOURNAL.md`), design system adapté au projet (`docs/DESIGN_SYSTEM.md`),
  retrait des hôtes/domaines réels des documents publiables.

## [Publié]

### Déployé en production — 2026-07-06 (migrations ≤ 0001)

Bascule effectuée et vérifiée en prod : reverse-proxy nginx mono-clé retiré (sauvegardé),
**Caddy termine le TLS du domaine public** (cert Let's Encrypt via DNS-01 Scaleway), la clé
historique du client existant a été migrée (avec son origine), et l'agent client bascule sur
la nouvelle chaîne HTTPS. Preuves live : chaîne HTTPS externe 200, chat streaming + embed réels
via l'agent (l'embed qui échouait en 403 avec l'ancien nginx fonctionne désormais), usage
journalisé (tokens comptés).

- **Passerelle complète de gestion de clés Ollama** (première version).
  - Proxy d'inférence : auth par clé `Authorization: Bearer`, restriction d'origine par clé
    (IP/CIDR), quotas (plafond mensuel de tokens + rate-limit req/min), journalisation d'usage
    par requête, streaming intégral (NDJSON/SSE) avec strip de la clé avant l'amont, proxy de
    **tous** les endpoints (`/api/*`, `/v1/*`) et `/_proxy_health`.
  - Panel d'admin web LAN-only (Jinja) : login mot de passe, CRUD des clés (création avec secret
    affiché une seule fois, activation/désactivation, suppression, édition origines/quotas),
    dashboard d'usage (totaux + détail par clé + dernières erreurs).
  - Stockage **SQLite** (WAL) : `api_keys` (clé hachée), `key_origins`, `key_quotas`,
    `usage_events` (append-only), `admin_auth`. Migrations idempotentes.
  - Dockerisation dev/staging/prod + lanceurs ; dev self-contained/self-seeded (faux upstream).
  - **Caddy** avec module DNS Scaleway (Caddy 2.11) : TLS par challenge DNS-01
    (`secret_key` + `organization_id` + `dns_ttl` requis ; `auto_https disable_redirects`).
  - Import d'une clé existante par valeur (migration) via `python -m app.bootstrap import-key`.
  - Tests : 31 unitaires/intégration (pytest) + 3 E2E Playwright (admin UI + proxy), vérifiés
    en vision.
