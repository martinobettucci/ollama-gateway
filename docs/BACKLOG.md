# Backlog — ollama-gateway

Marquage : `[x]` fait & prouvé (unit + E2E + vision), `[~]` en cours, `[ ]` à faire.
Règle DoD : pas de `[x]` sans ses tests propres.

## Phase 1 — Passerelle & admin (cœur)

- [x] Schéma SQLite + migrations idempotentes — *tests : test_keys, test_quotas*.
- [x] Génération/hachage des clés + mot de passe admin — *test_auth*.
- [x] CRUD clés + lookup + contrôle d'origine (IP/CIDR v4/v6) — *test_keys*.
- [x] Journalisation d'usage + agrégats — *test_quotas, test_proxy, E2E dashboard*.
- [x] Quotas (plafond mensuel + rate-limit) réellement appliqués — *test_quotas, test_proxy (429), E2E*.
- [x] Proxy streaming (NDJSON/SSE), strip clé, tous endpoints, 401/403/429 — *test_proxy, E2E proxy*.
- [x] Comptage des tokens (payload de fin, y c. streaming) — *test_proxy (11/7), E2E usage*.
- [x] Panel admin : login/guard, CRUD, secret unique, dashboard — *test_admin, E2E admin*.
- [x] Vérification en vision de l'UI (captures dashboard/création/détail/usage).

## Phase 2 — Packaging & déploiement

- [x] Dockerisation dev/staging/prod + lanceurs + entrypoint (rôle par env).
- [x] Dev self-contained/self-seeded (faux upstream Ollama, seeds déterministes).
- [x] Caddy + module DNS Scaleway (Dockerfile.caddy, Caddy 2.11) ; Caddyfile prod + staging.
- [x] Import de clé existante par valeur (migration) — *test_keys (import), CLI bootstrap*.
- [x] **Build des images sur la hôte self-hosted (aarch64)** — gateway + Caddy buildés OK ; `dns.providers.scaleway`
  présent dans le binaire. *Note : le plugin scaleway v0.2.2 impose Caddy 2.11 + `GOTOOLCHAIN=auto`.*
- [x] **Smoke non-disruptif sur la hôte self-hosted** : proxy (port libre) → **vrai Ollama** avec la clé client-exemple
  → 200 / 16 modèles ; sans clé → 401 ; health 200. Sans toucher nginx/11435/client-exemple. Nettoyé.
- [x] **Émission TLS DNS-01 validée** (port temporaire 11436, non-disruptif) : cert Let's Encrypt
  `llm.example.com` obtenu via Scaleway ; chaîne HTTPS complète 200 (clé client-exemple) / 401 (sans) /
  404 (`/admin`). *Config requise : bloc `dns scaleway {secret_key; organization_id}`, `dns_ttl 3600s`
  (l'API Scaleway exige un TTL), `auto_https disable_redirects`, `handle` (pas `respond` nu).*
- [x] **Cutover prod hôte self-hosted** — FAIT et vérifié (2026-07-06) : nginx retiré (sauvegardé), Caddy TLS
  sur :11435, clé client-exemple migrée, agent client-exemple basculé sur `https://llm.example.com:21434` (pin
  `/etc/hosts`→IPv4 côté client-exemple car l'IPv6 n'est pas routé par le forward). Preuves : HTTPS externe 200,
  chat streaming + embed réels via l'agent (embed corrigé vs 403 nginx), usage journalisé (tokens).
- [~] **Cutover client-exemple** `OLLAMA_BASE_URL` http→https — à coordonner après bascule prod.

## Phase 3 — Conformité charte P2Enjoy & règles de repo (2026-07-07)

- [x] **UI admin restylée charte P2Enjoy** (thème clair, tokens, cartes `rounded-xl` à liseré de
  catégorie, nav pilules, icônes lucide inline, héros login/setup) — *tests : E2E admin.spec
  (login + dashboard + création + détail) & proxy.spec (badges d'état), test_admin (rendu),
  captures 00–04 observées en vision.*
- [x] **E2E déterministe** : base `e2e-data/gateway.db` supprimée puis re-seedée à chaque run
  (`global-setup.ts`) — *preuve : suite E2E verte sur runs consécutifs.*
- [x] Docs de conformité : `docs/manual.md` (public, Mermaid), `docs/JOURNAL.md`,
  `DESIGN_SYSTEM.md` adapté au repo (écart Jinja justifié § 6), section « Spécifique à ce
  repo » de `CLAUDE.md` réécrite, purge hôtes/domaines de `CHANGELOG.md`/`README.md`.
- [ ] Hook `.claude/hooks/session-start.sh` + `settings.json` (démarrage daemon Docker) —
  bloqué par le classifieur de permissions (self-modification) ; à créer/approuver par le
  responsable.
- [x] **Manuel utilisateur en modale** (`GET /admin/manual`, markdown rendu serveur, captures
  par fonctionnalité servies depuis `app/static/manual/`, sync `npm run sync-manual`) —
  *tests : test_admin (test_manual_requires_login, test_manual_rendered_with_screenshots),
  E2E admin.spec « manuel utilisateur affiché en modale », capture 05-manual observée en
  vision, validé aussi dans le conteneur Docker.*
- [x] **`runDev` affiche le mot de passe admin dev** dans le récapitulatif de lancement.

## Phase 4 — Serveurs d'exécution multi-Ollama & restriction de modèles (2026-07-07)

- [x] **Registre de serveurs d'exécution** (local par défaut indélébile + distants), CRUD,
  jeton Bearer distant **chiffré au repos** (Fernet, `P2E_MASTER_KEY`), reconciler `ensure_default`
  — *tests : test_servers (crypto, CRUD, défaut, suppression protégée), E2E servers.spec.*
- [x] **Test de disponibilité** d'un serveur (sonde `/api/tags` → en ligne/hors ligne + modèles)
  — *tests : test_servers (probe/test_server via ASGI), E2E « test du serveur par défaut ».*
- [x] **Rattachement clé → un serveur unique** (`api_keys.server_id`, défaut auto) — *tests :
  test_keys (server_id), test_servers (réassignation orpheline), E2E rattachement.*
- [x] **Restriction de modèles par clé, agnostique de l'API** (Ollama/OpenAI/Anthropic : `model`
  à la racine) : 403 hors allowlist + filtrage `/api/tags` & `/v1/models` ; 503 serveur indispo
  — *tests : test_proxy (gating multi-API, filtrage, 503, injection jeton amont), E2E restriction.*
- [x] **UI** : page Serveurs (charte), sélecteur de serveur + cases de modèles sur la clé, colonnes
  dashboard — *vision : captures 06-servers, 07-key-restricted ; manuel + captures synchronisés.*
  *Rouvert puis reclos le 2026-07-07 : la 1ʳᵉ version ne montrait les cases qu'après un « Tester »
  manuel du serveur (spec non respectée). Corrigé : les formulaires de clé (création ET édition)
  sondent en direct le serveur choisi (`GET /admin/servers/{id}/models`) et affichent ses modèles
  en cases à cocher, re-sonde au changement de serveur, repli en saisie libre si hors ligne
  (`_model_picker.html`). Preuves : test_admin (sonde live + fusion cases/saisie), E2E servers.spec
  (cases au rattachement + repli hors ligne), captures 07 & 08 vérifiées en vision, manuel à jour.*
- [x] **Robustesse démarrage** : migrations concurrent-safe (`flock`) + `busy_timeout` avant WAL
  (les rôles proxy/admin migrent en parallèle sur le même SQLite).

## Phase 5 — Plein viewport & configuration client (2026-07-07)

- [x] **Layout plein viewport (règle dure du responsable)** : 100 % largeur + hauteur partout
  (dashboard et détail de clé en 2 colonnes ≥ 1360 px, Serveurs en grille de cartes, login en
  split hero/formulaire pleine hauteur) — *tests : E2E admin.spec « plein viewport » (main =
  largeur client, login compris) ; vision : captures 00/01/06 + rendus 1920 px observés.*
- [x] **Modale « configurer le client » à la création d'une clé** : variables d'env générées
  selon les API cochées (Ollama `OLLAMA_HOST`/`OLLAMA_API_KEY`, OpenAI `OPENAI_BASE_URL`/
  `OPENAI_API_KEY`, Anthropic `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`), copie en un clic
  (repli execCommand en http), base = `PUBLIC_BASE_URL` (config + composes + .env.prod.example)
  — *tests : test_admin (modale rendue une seule fois, base injectée), E2E admin.spec « modale
  de configuration client » ; vision : capture 09-env-modal ; manuel synchronisé.*
- [x] **Proxy : clé acceptée en `x-api-key`** (SDK Anthropic) en plus du Bearer, en-tête strippé
  avant l'amont — *tests : test_proxy (x-api-key ok + strip, x-api-key invalide → 401).*
- [x] **« Essayer maintenant » : chat de test d'une clé** (relais admin LAN-only
  `POST /admin/keys/{id}/try-chat` vers le serveur rattaché) avec fenêtre de chat sur la page de
  la clé — *tests : test_admin (login requis, réponse renvoyée, modèle hors allowlist → 403,
  message vide → 400), E2E admin.spec « essayer maintenant » ; vision : capture 10 ; manuel à jour.*

## Phase 6 — Console de logs, bannissement d'origines, try-me modèle+API (2026-07-08)

- [x] **Console de logs (journal complet)** : page `/admin/logs` listant l'intégralité du journal
  `usage_events` (jamais purgé), la plus récente d'abord (`usage.recent_events`/`total_events`)
  — *tests : test_bans (login requis, page rendue), E2E admin.spec « console de logs » ; vision :
  capture 11-logs.*
- [x] **Bannissement GLOBAL d'origines (IP/CIDR)** : table `banned_origins` (migration 0003),
  module `bans.py` (normalisation IP→/32·/128, add/list/remove, `is_banned`), appliqué par le
  proxy **avant l'auth** (403), pilotable depuis la console (bouton par ligne + saisie manuelle +
  débannir) — *tests : test_bans (normalisation, CIDR couvrant une plage, DENY proxy avant auth,
  ban/unban admin, entrée invalide), E2E « bannir bloque le proxy (403) puis débannir » ; vision :
  capture logs état banni.*
- [x] **« Essayer maintenant » : choix du modèle ET de l'API** (Ollama chat, OpenAI Chat
  Completions, OpenAI Responses, Anthropic Messages) via `servers.try_call` + `TRY_APIS` ; faux
  Ollama étendu (`/v1/responses`, `/v1/messages`) — *tests : test_admin (4 API paramétrées → réponse,
  API inconnue → 400), E2E admin.spec (select modèle sondé + API OpenAI, réponse étiquetée) ;
  vision : capture 10 (selects).*

## Phase 7 — Contenu des requêtes sur fichiers + origines/WHOIS (2026-07-09)

- [x] **Journal de CONTENU complet des requêtes hors base** (`app/reqlog.py`) : un dossier par
  clé, un fichier JSONL par heure, secrets (`Authorization`/`x-api-key`) retirés ; écrit par le
  proxy pour toute requête authentifiée. `REQUEST_LOG_DIR` (vide = désactivé), câblé dev/staging
  (volume `/data/reqlogs`) + prod (`.env.prod`) — *tests : test_reqlog (écriture + secrets
  masqués + désactivation), E2E (fichiers réellement écrits, `authorization: «masqué»`, zéro clé
  en clair).*
- [x] **Cron de compaction/purge, rétention PAR CLÉ** (`reqlog.compact_and_purge` + CLI
  `python -m app.reqlog compact`) : gzip des heures passées, purge au-delà de la rétention
  (`api_keys.log_retention_days`, migration 0004 ; NULL → `REQUEST_LOG_RETENTION_DAYS`) ; champ
  « Rétention des logs » sur la clé — *tests : test_reqlog (compaction gzip, purge rétention par
  clé + défaut global), test_admin (champ rendu, valeur).*
- [x] **Origines vues + recherche + WHOIS** sur la page d'une clé (`usage.origins_seen`,
  `app/whois.py` RDAP + court-circuit local, `GET /admin/whois`) — *tests : test_whois (local,
  invalide, RDAP mocké, HTTP error), test_admin (route login/loopback, origins_seen, page),
  E2E « origines vues : liste + recherche + WHOIS modale » ; vision : captures 12 + page origines.*

## Idées ultérieures (non planifiées)

- [ ] Changement du mot de passe admin depuis l'UI.
- [ ] Rotation de clé (regénérer en conservant label/origines/quota).
- [ ] Export CSV de l'usage ; rétention/rotation des `usage_events` (le journal est actuellement
  conservé intégralement, sans purge).
- [ ] Quota par fenêtre glissante distribuée si multi-instance (non requis ici).
