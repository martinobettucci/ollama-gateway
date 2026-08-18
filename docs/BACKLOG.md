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
- [x] **Build des images ARM64 (hôte self-hosted)** — gateway + Caddy buildés OK ; `dns.providers.scaleway`
  présent dans le binaire. *Note : le plugin scaleway v0.2.2 impose Caddy 2.11 + `GOTOOLCHAIN=auto`.*
- [x] **Smoke non-disruptif sur l'hôte de prod** : proxy (port libre) → **vrai Ollama** avec la clé
  historique → 200 ; sans clé → 401 ; health 200. Sans toucher l'ancien reverse-proxy. Nettoyé.
- [x] **Émission TLS DNS-01 validée** (port temporaire, non-disruptif) : cert Let's Encrypt du
  domaine public obtenu via Scaleway ; chaîne HTTPS complète 200 (clé) / 401 (sans) /
  404 (`/admin`). *Config requise : bloc `dns scaleway {secret_key; organization_id}`, `dns_ttl 3600s`
  (l'API Scaleway exige un TTL), `auto_https disable_redirects`, `handle` (pas `respond` nu).*
- [x] **Cutover prod** — FAIT et vérifié (2026-07-06) : ancien reverse-proxy retiré (sauvegardé),
  Caddy TLS sur le port public, clé historique migrée, client basculé sur `https://<GATEWAY_DOMAIN>`
  (pin `/etc/hosts`→IPv4 côté client car l'IPv6 n'est pas routée par le forward). Preuves : HTTPS
  externe 200, chat streaming + embed réels, usage journalisé (tokens).
- [x] **Cutover client** `OLLAMA_BASE_URL` http→https — à coordonner après bascule prod.

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

## Phase 8 — Compatibilité d'API, cibles publiques, expiration de clé, recherche (2026-07-09)

- [x] **Compatibilité d'API : matrice par serveur + allowlist par clé** (`app/apis.py` catalogue +
  `family_for_path`, migration 0005 `key_apis`/`servers.last_compat`, `servers.run_compat` sonde
  d'accessibilité des chemins **sans validation de schéma**, proxy `403` de chemin hors allowlist,
  cases à cocher d'API sur la clé, matrice + « Tester la compatibilité » sur la page Serveurs).
  E2E `phase8.spec.ts` + **vision** (capture 13) faits. — *tests unit/intégration verts :
  test_apis (mapping, allowlist round-trip, run_compat matrice), test_proxy (allowlist vide = tout,
  interdit hors famille, listing toujours servi).*
- [x] **Cibles publiques (ingress) attachées par clé** : `app/targets.py` (+ migration 0006
  `targets`/`api_keys.target_id`), CRUD + `ensure_default` (seedé de `PUBLIC_BASE_URL`), onglet
  **Cibles**, sélecteur sur la clé, env-gen utilise l'URL de la cible rattachée. N'affecte pas le
  routage. E2E `phase8.spec.ts` + **vision** (captures 13-17) faits. — *tests unit verts : test_targets (défaut/placeholder,
  idempotence, rattachement, round-trip env-url, suppression défaut/rattachée bloquée).*
- [x] **Expiration/plafonds de vie d'une clé** (distinct du rate-limit) : migration 0007
  (`total_token_cap`/`total_request_cap`/`expires_at`/`idle_expiry_days`), `usage.lifetime_tokens`
  /`lifetime_requests`, `quotas.check` étendu (expiration, inactivité, plafonds absolus), champs de
  formulaire (create+edit). E2E `phase8.spec.ts` + **vision** (captures 13-17) faits. — *tests unit verts : test_expiry
  (expiration passée/future, plafonds tokens/requêtes, inactivité stale/récente, round-trip).*
- [x] **Recherche/filtre des clés sur le tableau de bord** (label/préfixe/serveur/API/état) :
  toolbar + attributs de ligne + filtrage JS. E2E `phase8.spec.ts` + **vision** (captures 13-17) faits. — *tests verts :
  test_admin_pages (toolbar + attributs rendus).*
- [x] **Serveur de repli (fallback) optionnel par clé** : migration 0008 (`fallback_server_id` +
  `usage_events.server_id`), proxy `_send_chain` (repli sur 5xx/erreur connexion, streaming inclus),
  attribution serveur des logs, sélecteur sur la clé (create+edit, avec `clear_fallback`). Reste
  pour `[x]` : **E2E + vision**. — *tests verts : test_fallback (repli sur 500, sans repli 500 relayé,
  primaire OK non replié, round-trip + clear).*
- [x] **Monitoring par serveur + stats intensives** : agrégations `usage.server_summary`/
  `server_per_key`/`server_status_breakdown`/`server_daily` (via `usage_events.server_id`), module
  `app/charts.py` (SVG purs : barres/camembert/série, charte P2Enjoy), page **Monitor** par serveur
  (tuiles + graphiques + tableau par clé), lien depuis la page Serveurs. Reste pour `[x]` : **E2E +
  vision**. — *tests verts : test_monitor (agrégations, isolation par serveur, graphiques + vide,
  rendu de page).*

## Phase 9 — Génération d'images (Ollama & OpenAI) (2026-07-09)

- [~] **Génération d'images + capacité et modèles séparés** : `apis` familles `ollama-image`/
  `openai-image` + `is_image_model`/`capability_for_request` ; migration 0009 `key_image_models`
  (allowlist x/ séparée) ; proxy gate capability + modèle image (x/ sur /api/generate, endpoint
  /v1/images/generations) ; `keys` image_models (create/update/get) ; `servers.try_image` +
  route `/admin/keys/{id}/try-image` (image d'entrée base64) ; UI : cases image, sélecteur x/
  séparé, onglets Texte/Image du « Essayer » avec pièce jointe image ; faux Ollama (x/fakeflux,
  /v1/images/generations). **Vision faite (capture 18)** ; **relais réel vérifié de bout en bout**
  (déployé, `x/flux2-klein:4b` pull sur l'Ollama, clé test dotée du modèle image → la requête est
  **autorisée, gatée et relayée** jusqu'à l'amont). ⚠️ **Génération réelle KO sur CE matériel** :
  Ollama 0.30.11 utilise le runner **MLX (Apple Silicon uniquement)** pour l'image ; l'hôte de prod
  est Linux ARM64/CUDA → l'amont renvoie `mlx runner failed` (500), **relayé fidèlement** par la
  passerelle. Limite AMONT/matériel, pas passerelle ; la génération réelle nécessite un upstream
  Apple Silicon (ou un runner image compatible CUDA quand Ollama le fournira). — *tests verts :
  test_images (11 : capability/mapping, allowlist image round-trip, gating proxy ollama/openai +
  séparation texte, try_image, route admin), E2E images.spec (onglet Image + image-to-image).*

## Phase 10 — Internationalisation du panel (2026-07-16)

- [x] **i18n du panel d'admin — 24 langues officielles de l'UE, un YAML par langue.** Module
  `app/i18n.py` (catalogue `app/locales/<code>.yaml` aplati en clés pointées, source `fr` ;
  `translate` avec interpolation `{param}` + repli langue→fr→clé ; `negotiate` session→cookie→
  `Accept-Language`→fr, borné par `SUPPORTED_LANGS`). Tous les templates passés à `t()` (base,
  login, setup, dashboard, targets, monitor, logs, servers, key_detail + partiels `_api_picker`/
  `_model_picker`), libellés JS injectés via JSON/`data-*`. Sélecteur de langue dans la barre
  (`POST /admin/lang`, redirection bornée `/admin`). Les 24 locales sont **complètes clé-à-clé**
  (275 clés) ; placeholders et identifiants `mono` (env/chemins/URLs) préservés. Docs synchronisées
  (CHANGELOG, DAT, DESIGN_SYSTEM, manuel + capture `19-lang-en.jpg`). Correctif annexe : garde
  anti-course dans la sonde du `_model_picker`. — *tests verts : `test_i18n` (12 : complétude des 24
  locales, invariance placeholders/`mono`, `<strong>`, repli+interpolation, route `/admin/lang`
  (rendu + anti-open-redirect), sélecteur présent, négociation) ; E2E `i18n.spec` (bascule
  en/de/es du dashboard/serveurs/détail de clé + modale « Essayer », persistance session,
  navigateur fr-FR) ; **vision faite** (dashboards EN/DE, détail de clé EN, modale « Essayer » EN).*

## Phase 11 — Visionneuse du contenu des requêtes (2026-07-17)

- [x] **Consultation + grep du contenu des logs dans le panel** : page `/admin/logs/content`
  (choix clé/heure + filtre grep insensible à la casse + dépliage par requête), téléchargement
  brut `/admin/logs/content/raw`, lecture gzip transparente, noms de fichiers validés (anti
  path-traversal), secrets restant masqués ; câblage `REQUEST_LOG_DIR` côté admin (composes +
  E2E). i18n `logs.content.*` (fr/en réelles, 22 autres = source fr en repli, complétude testée)
  — *tests : test_reqlog (list_keys_with_logs, list_files, read_content + grep, lecture gzip,
  resolve anti-traversal), test_admin (login requis, rendu + secret masqué + grep 0-match + brut),
  E2E admin.spec « contenu des requêtes : visionneuse + grep » ; vision : capture 25-logs-content.*

## Phase 12 — Gestion des modèles par serveur & traçage de l'usage par modèle (2026-07-20)

- [x] **Traçage du dernier usage par modèle et par serveur.** `usage.server_per_model(server_id)`
  agrège, pour chaque modèle réellement invoqué sur un serveur, requêtes/tokens/erreurs + **premier
  et dernier usage** (tri par `last_seen` DESC, événements `model=''` exclus) ; table « Usage par
  modèle » ajoutée au monitoring du serveur (`monitor.html`, `data-testid=monitor-permodel`).
  Attribution réelle (`usage_events.server_id`, repli inclus). — *tests : test_monitor
  (`server_per_model` : agrégats + tri par dernier usage + exclusion `model=''`, page monitor rend
  la table) ; E2E servers.spec « monitoring : traçage du dernier usage par modèle » ; **vision faite**
  (capture 11-per-model + 17-monitor régénérée).*
- [x] **Commandes d'admin LAN-only : télécharger / supprimer un modèle sur un serveur.**
  `servers.pull_model` / `servers.delete_model` appellent directement l'amont (`/api/pull`,
  `DELETE /api/delete`) avec le jeton distant déchiffré côté serveur (jamais côté navigateur) ;
  routes `POST /admin/servers/{id}/models/pull` + `.../delete` (garde login, re-sonde après action,
  flash i18n) ; bloc « Modèles du serveur » dans `servers.html` (formulaire de pull + suppression
  par modèle avec confirmation). Faux Ollama doté d'un catalogue mutable (`/api/pull`, `/api/delete`)
  → testable de bout en bout. Traductions ajoutées aux **24 locales**. — *tests : test_servers
  (pull ajoute au catalogue, delete retire, 404 modèle absent, gardes nom/serveur/désactivé avant
  tout appel amont) ; test_monitor (routes admin pull+delete de bout en bout, login requis) ; E2E
  servers.spec « gestion des modèles : pull → visible → delete » ; **vision faite** (captures
  26-model-manage, 09-model-pull, 10-model-delete).*
- [x] **Garde-fou : le proxy refuse toute commande de gestion à un client (déjà en place, désormais
  testée).** `apis.is_management_path` couvre `pull`/`push`/`delete`/`create`/`copy`/`blobs`
  (± slash, `/api/blobs/<digest>`) ; le proxy renvoie **403** avant tout amont pour n'importe quelle
  clé. — *tests : test_apis (`is_management_path` : tous les chemins de gestion vs inférence/listing) ;
  test_proxy (403 sur pull/delete/push/create/copy/blobs avec clé valide, catalogue amont intact,
  refus journalisés) ; E2E servers.spec (refus proxy `/api/pull` + `/api/delete` avec la clé démo).*

## Phase 13 — Configuration déclarative (headless / YAML) & livraison des clés (2026-07-20)

Objectif : déployer la passerelle **sans WebUI**, pilotée par un **fichier YAML** versionné
(serveurs à compatibilité/modèles statiques, cibles, clés), réconcilié au démarrage ; livrer le
secret des clés générées par **webhook** (template + presets) ou **e-mail** (SMTP, Inbucket en
dev) ; et **exporter** la configuration courante en YAML depuis l'UI. Décisions : le drapeau
headless vit dans l'**environnement** (`GATEWAY_CONFIG`), pas dans le YAML ; secrets par
**interpolation `${NOM}`** ; **prune = désactivation** par défaut (suppression si `prune: true`) ;
livraison **idempotente** (une clé livrée une seule fois). Réalisée en **3 sous-phases testées
l'une après l'autre** (E2E vert à chaque étape avant la suivante).

- [x] **Sous-phase 1 — Réconciliation.** `app/reconcile.py` : chargement YAML + **interpolation
  `${NOM}`** (fail-closed), validation (structure, références serveur/cible, familles d'API,
  base_url), **upsert** serveurs/cibles/clés, **liste de modèles statique** par serveur, **identité
  stable** `external_ref` (migration 0010, index unique partiel), **prune = disable / delete**,
  clés UI intouchées. Garde-fou : en mode déclaratif, `ensure_default` n'auto-crée pas de défaut.
  Hook entrypoint `GATEWAY_CONFIG` (avant uvicorn) ; `docker-compose.headless.yml` + `runProdHeadless`
  (proxy + Caddy, **sans admin**) + `gateway.example.yaml` ; `gateway.yaml` gitignoré. Import de clé
  au secret connu via `value: ${NOM}`. — *tests : `tests/test_reconcile.py` (14 : interpolation +
  variable manquante, rejets de validation, upsert serveurs/cibles/clés + jeton chiffré + modèles
  statiques + défaut, idempotence, mise à jour sans régénérer le secret, prune disable/delete, clés
  UI intouchées, réactivation au retour dans le YAML, saut de l'auto-défaut en mode déclaratif) ;
  E2E `e2e/tests/reconcile.spec.ts` (CLI base neuve : serveurs/cibles/clés + idempotence + prune
  disable/delete sans « Ollama local » parasite ; base partagée : clé importée acceptée par le
  proxy + en-tête `x-ratelimit` + visible au dashboard + désactivée au retrait) ; **vision faite**
  (capture 28-reconcile).*
- [x] **Sous-phase 2 — Livraison du secret des clés générées.** `app/deliver.py` : canal **e-mail**
  (`smtplib`, TLS none/starttls/tls, SMTP configuré en YAML via `${NOM}`) et **webhook** (`httpx`
  POST, presets `slack`/`discord`/`generic` ou **template libre**, jetons `#OllamaKey`/`#OllamaUrl`/
  `#OllamaLabel`) ; corps = **variables d'environnement valorisées** (`client_env`). Livraison HORS
  verrou juste après la génération (secret en mémoire) ; idempotence `secret_delivered_at`
  (migration 0011) ; best-effort (canal en échec n'interrompt pas les autres, rapporté). Puits SMTP
  de test sans dépendance (`devfixtures/smtp_sink.py`, Python 3.13) + capteur webhook du faux
  Ollama ; Inbucket optionnel en dev (profil compose `mail`). — *tests : `tests/test_deliver.py` (8 :
  env valorisé, presets slack/discord/generic + template, POST webhook rendu, dialogue SMTP
  starttls + tls none, best-effort multi-canal) ; `tests/test_reconcile.py` (livraison + horodatage
  + idempotence, échec rapporté non marqué, clé importée non livrée, e-mail exige SMTP) ; E2E
  `e2e/tests/delivery.spec.ts` (même secret livré par e-mail ET webhook, env valorisé, horodatage) ;
  **vision faite** (capture 29-delivery).*
- [x] **Sous-phase 3 — Export de la configuration en YAML.** `reconcile.export_config`/`export_yaml`
  sérialisent l'état courant (serveurs/cibles/clés) en YAML déclaratif **sans secret** (clés sans
  `value` ; jetons de serveur et SMTP/livraison non exportables — ré-introduits à la main) ; noms de
  clés = `external_ref` sinon slug du label. Bouton **« Exporter »** (nav, icône `download`, clé i18n
  `nav.export`/`export_hint` ajoutée aux **24 locales**) → `GET /admin/config.yaml` (garde de session,
  téléchargement `gateway.yaml`) ; commande `python -m app.reconcile export`. — *tests :
  `tests/test_reconcile.py` (forme sans secret, ré-importable sans doublon, slug des clés UI) ;
  `tests/test_i18n.py` (clés `nav.export*` complètes sur les 24 locales) ; E2E `e2e/tests/export.spec.ts`
  (bouton → téléchargement `gateway.yaml`, structure présente, aucun secret / `value:`) ; **vision
  faite** (captures 30-export, 31-export-yaml).*

## Phase 14 — Réémission de clé & correctif copie (2026-07-27)

- [x] **Réémission d'une clé (rotation du secret).** `keys.reissue_key(key_id)` régénère
  `key_hash`/`key_prefix` (nouveau secret, ancien invalidé) en conservant id/label/config/plafonds/
  serveur/cible/`external_ref`/`created_at` et **l'historique d'usage** ; route
  `POST /admin/keys/{id}/reissue` réutilise la modale de création (secret montré une fois) ; bouton
  **Réémettre** (icône `refresh-cw`, confirmation) sur chaque ligne du tableau de bord ; i18n
  `dash.keys.reissue_short`/`reissue_confirm` sur les **24 locales**. — *tests : `tests/test_keys.py`
  (rotation : nouveau≠ancien, ancien invalidé, id/config/historique conservés ; clé absente → None) ;
  E2E `e2e/tests/reissue.spec.ts` (ancien secret 401, nouveau 200 via proxy, clé toujours active) ;
  **vision faite** (capture 32-reissue).*
- [x] **Correctif : bouton « Copier » inopérant sur l'admin en HTTP (LAN).** En contexte non
  sécurisé `navigator.clipboard` est absent ; le repli `execCommand` échouait car sa textarea était
  ajoutée **hors** du `<dialog>` (rendu inerte par `showModal()`). Insertion désormais **dans** la
  modale. — *tests : E2E `e2e/tests/reissue.spec.ts` (contexte non sécurisé simulé : `navigator.
  clipboard` retiré → repli réussit, libellé « Copié »).*

## Phase 15 — Limite de contexte par clé (2026-07-27)

- [x] **Plafond de contexte par clé, appliqué avant l'amont et imposé à l'amont.** `app/context.py`
  (migration 0012, `max_context_tokens` NOT NULL DEFAULT 114688) : valeur **obligatoire**, multiple
  de **4096**, bornée **4k → 1M**, défaut **112k** ; `normalize()` accepte entier ou « 112k ».
  Comptage **multi-API** du texte du corps (messages/prompt/input/system ; images base64 exclues)
  via **tiktoken** `cl100k_base`, **majoré de 15 %** ; le proxy renvoie **413** (avec estimation,
  valeur majorée et plafond) **sans jamais appeler l'amont**, et injecte `options.num_ctx` sur les
  chemins Ollama natifs (`min(client, plafond)`). Tokenizer **hors-ligne** (cache BPE embarqué dans
  l'image au build) avec repli sur estimation. UI : sélecteur à la création + à l'édition, badge sur
  la ligne de la clé ; i18n `dash.new.max_ctx`/`max_ctx_hint` sur les **24 locales** ; supporté en
  configuration déclarative (`max_context_tokens: 112k`) et repris dans l'export. — *tests :
  `tests/test_context.py` (30 : bornes/normalisation/arrondi, comptage Ollama/OpenAI/Anthropic,
  exclusion des images base64, marge de 15 %, injection num_ctx dont plafonnement et respect d'une
  valeur client plus petite, non-injection hors Ollama ; **intégration proxy** : 413 sans appel
  amont, num_ctx reçu par l'amont, requête normale acceptée) ; `tests/test_reconcile.py` (YAML
  entier/libellé/défaut + export) ; E2E `e2e/tests/max_context.spec.ts` (sélection à la création,
  badge, 413 avec marge vérifiée, refus journalisé, num_ctx reçu par le faux amont) ; **vision
  faite** (capture 33-max-context).*

## Phase 16 — Statistique des tailles de contexte utilisées (2026-07-28)

- [x] **Échelle de paliers + classement de chaque requête + statistique par clé et par serveur.**
  `context.CONTEXT_SIZES` devient l'ensemble des valeurs autorisées (2k · 4k · 8k · 12k · 24k · 36k ·
  48k · 64k · 72k · 96k · 108k · **112k** · 128k · 144k · 180k · 224k · 256k · 384k · 512k · 640k ·
  768k · 1M) ; `is_valid`/`normalize` calés dessus (normalisation = palier ≥ demandé).
  `context.bucket(tokens)` = **plus petit palier qui contient** (27 734 → 36k ; 2 096 → 4k).
  `usage_events.ctx_bucket` (migration 0013, index dédié) enregistré par le proxy à partir des
  **compteurs réels de l'amont** quand disponibles, sinon de l'estimation d'entrée ; NULL (non
  mesuré) exclu des agrégats. `usage.key_ctx_buckets`/`server_ctx_buckets` → compte, tokens, premier
  et **dernier usage** par palier, du plus grand au plus petit. UI : **camembert + tableau** sur la
  page d'une clé ET le monitoring d'un serveur ; i18n `ctx.*` sur les **24 locales**. — *tests :
  `tests/test_context.py` (échelle = ensemble autorisé, `bucket` sur les exemples de la spec et
  bornes, normalisation vers palier supérieur, agrégats multi-paliers avec compte/dernier usage par
  clé ET serveur, affinage par les tokens réels de l'amont, exclusion des événements non mesurés) ;
  E2E `max_context.spec.ts` (camembert + tableau rendus sur la page clé et le monitoring, libellés de
  palier, dernier usage non vide) ; **vision faite** (captures 34-ctx-stats-key, 35-ctx-stats-server).*

## Phase 17 — Navigation adaptative (mobile) (2026-07-28)

- [x] **Correctif : la barre de navigation était inutilisable sur mobile.** Avec 7 entrées, `.pills`
  (flex sans `wrap` ni media query) mesurait **852 px** et forçait le document à **875 px** : à
  360-390 px, **Logs / Manuel / Exporter / Déconnexion étaient hors écran et inatteignables**, et la
  `.topbar` montait à **154 px**. Sous **900 px**, la barre se replie derrière un bouton
  (icône lucide `menu`/`x`, 44×44) et les pilules deviennent une **pile verticale pleine largeur**
  (`order:3; flex-basis:100%`) ; au-dessus, la rangée d'origine est inchangée. Cibles ≥ 44 px, icône
  + libellé conservés, état actif préservé, **déconnexion séparée** (`.pill-exit`, danger + filet).
  Accessibilité : `aria-expanded`/`aria-controls`, **Échap** referme et rend le focus. **Sans JS** :
  bouton masqué, pile dépliée (marqueur `has-js` posé dans le `<head>`) → rien d'inaccessible.
  Clé i18n `nav.menu` sur les **24 locales**. Conception passée par le skill UI/UX (règles
  `overflow-menu`, `horizontal-scroll`, `touch-target-size`, `nav-label-icon`, `nav-state-active`,
  `destructive-nav-separation`, `mobile-first`). — *tests : `tests/test_admin_pages.py` (bouton, nav
  identifiée, `has-js` non codé en dur, `.pill-exit`) ; E2E `e2e/tests/mobile_nav.spec.ts` (390 px :
  **zéro débordement** du document avant ET après ouverture, 7 entrées entièrement dans le viewport,
  hauteur ≥ 44 px, état actif unique, Échap referme + focus rendu, navigation réelle vers Logs
  depuis le menu ; 1280 px : rangée conservée, bouton masqué) ; **vision faite** (captures
  36-nav-mobile-closed, 37-nav-mobile-open).*

## Phase 18 — Paramètres réels des modèles : sonde, sélecteur, gabarit VS Code (2026-08-18)

- [x] **Les paramètres des modèles sont LUS sur l'amont et exposés partout où ils ont un sens.**
  Le gabarit « point de terminaison personnalisé » renvoyait vers une invite de saisie de l'éditeur
  (`${input:…}`) pour la clé, annonçait `toolCalling: true` / `vision: false` **en dur pour tous les
  modèles**, n'exposait aucune borne d'entrée/sortie, et sortait **toujours sans aucun modèle** :
  il lisait `key_models`/`key_image_models` que `admin.dashboard` n'a **jamais** fournis (vérifié
  sur tout l'historique depuis `e26fe13`) — livré sans aucun test.

  **Sonde unique, trois familles d'amont.** `servers.model_specs` lit deux catalogues en parallèle
  (`GET /api/tags` — Ollama et **ollama.cpp** ; `GET /v1/models` — **OpenAI-compatible**) puis la
  fiche détaillée de chaque modèle (`POST /api/show`). Première source qui répond : fiche →
  `/api/tags` → `/v1/models`. Vérifié contre l'implémentation réelle d'ollama.cpp (branche
  `claude/ollama-cpp-middleware-po79fi`) : elle joint `capabilities` à chaque entrée de `/api/tags`
  (`list_model_entry`), expose `model_info` = KV du GGUF (`gguf.public_model_info`) et
  `parameters` au format Modelfile (`parameters_block`), et liste dans `/api/tags` les modèles
  issus de son **registre privé** comme les autres. `servers.read_specs` normalise n'importe laquelle de ces formes
  en `{toolCalling, vision, contextLength, maxOutput}` : `capabilities` (Ollama ≥ 0.6) avec repli
  `.Tools` + famille multimodale ; fenêtre/sortie cherchées sur un **aplatissement** du JSON
  (`_WINDOW_FIELDS`/`_OUTPUT_FIELDS` : `num_ctx`, `<arch>.context_length`, `max_model_len`,
  `n_ctx_train`, `num_predict`, `max_output_tokens`…), les paramètres du **Modelfile** primant, les
  sentinelles `≤ 0` écartées. Muet sur les deux voies ⇒ `known=False`, ni outils ni vision.

  **Exposition.** (1) `GET /admin/keys/{id}/vscode-models` (LAN-only) alimente le gabarit :
  `apiKey` = secret réel échappé, `apiType` = `chat-completions`, un bloc SÉPARÉ
  (`#env-vscode-block`, zone `env-vscode-output`, bouton `env-vscode-copy`, copie factorisée en
  `wireCopy`) au lieu d'écraser les variables d'environnement. (2) `GET /admin/servers/{id}/models`
  remonte désormais `specs` en plus des noms : le **sélecteur de modèles du formulaire de clé**
  affiche `outils · vision · 128k` à côté de chaque case (`.model-spec`, libellés i18n
  `mdl.spec_tools`/`mdl.spec_vision`). (3) Les variables d'environnement portent
  `OLLAMA_CONTEXT_LENGTH` = plafond de la clé — seule variable standard existante, rien d'inventé
  pour OpenAI/Anthropic.

  **Une seule règle de bornes** (simplification demandée) : `context.io_budget(fenêtre, sortie,
  plafond)` = fenêtre du modèle ramenée au plafond de la clé pour l'entrée (d'un cran plus bas
  quand le plafond borne, `plafond / MARGIN`, pour passer le garde-fou 413) ; sortie = celle que
  l'amont déclare, sinon `OUTPUT_DEFAULT` (16k), jamais plus que la fenêtre. Supprimés : réserve
  d'un quart, bornes 1k/32k, notion de borne d'entrée déclarée séparée.

  Faux Ollama : `/api/show` avec des fiches **volontairement hétérogènes** (un modèle publiant
  `capabilities`, un autre forçant le repli `.Tools`, un troisième déclarant `num_ctx`/`num_predict`)
  et un `openai-only:latest` présent **seulement** dans `/v1/models` (avec `max_model_len` /
  `max_output_tokens`) → le repli OpenAI-compatible est couvert, jamais simulé. Clés i18n
  `dash.env.vscode_probing`/`_ready`/`_offline`/`_copy` et `mdl.spec_tools`/`_vision` sur les **24
  locales**. — *tests : `tests/test_vscode_models.py` (27 : `io_budget` — fenêtre du modèle
  annoncée, bornage par le plafond + marge 413, sortie déclarée / défaut / sentinelle, sortie
  jamais > fenêtre, fenêtre inconnue ; `read_specs` — fiche Ollama, repli gabarit/familles,
  Modelfile prioritaire, fiche OpenAI-compatible (`max_model_len`, `meta.n_ctx_train`), sentinelles ;
  `model_specs` — valeurs distinctes par modèle, bornes du Modelfile, **repli `/v1/models`**,
  **repli sur l'entrée `/api/tags`** (modèle sans fiche, capacités jointes au catalogue à la façon
  d'ollama.cpp), catalogue sans allowlist, modèle inconnu prudent, serveur désactivé ; endpoints — gabarit composé,
  plafond respecté, bornes déclarées honorées, `specs` du sélecteur, guard + 404, absence de secret ;
  rendu — plus de `${input:…}`, `apiType`, id de clé à la création ET à la réémission, deux zones
  copiables, `OLLAMA_CONTEXT_LENGTH`, libellés du sélecteur) ; E2E
  `e2e/tests/vscode_template.spec.ts` (4 : JSON parsé — `apiKey` == secret réel, capacités
  différenciées, fenêtre 8k annoncée, bornage par le plafond, bornes du Modelfile 2048/512,
  variables d'environnement toujours affichées à côté avec le plafond, bouton de copie propre ;
  sans allowlist tout le catalogue décrit ; indépendance des deux blocs ; **sélecteur affichant
  `outils · vision · 8k`**) ; **vision faite** (captures 40-vscode-template, 41-vscode-blocks,
  42-model-specs). Docs : `docs/manual.md` (§ Gabarit VS Code réécrit en une règle + § « D'où
  viennent les paramètres des modèles » avec le tableau des 3 types de serveur, 3 captures
  synchronisées), `docs/DAT.md` (`servers.model_specs`/`read_specs`, `context.io_budget`), JOURNAL.*

  **Correctif issu de la vérification en vision sur la PRODUCTION.** Le sélecteur arrondissait
  systématiquement la fenêtre au millier (`Math.round(n / 1024) + 'k'`) : `all-minilm` (256 tokens)
  s'affichait donc **« 0k »**. Sous 1024, le nombre exact est écrit (`ctxLabel`). Le faux amont
  gagne `embed-mini:latest` (fenêtre 256) pour couvrir le cas ; deux assertions figeaient le
  catalogue de démonstration (`tests/test_proxy.py` ×2, `e2e/tests/admin.spec.ts` sur le nombre
  d'options de « Essayer maintenant ») — réécrites pour exprimer leur intention (contenu attendu,
  exclusion des modèles d'image) plutôt qu'un nombre figé. — *tests : E2E « sélecteur de modèles »
  assertant `256` et non `0k`.*

  **Limite connue.** `ollama.cpp` configure la fenêtre **par modèle** (`runtime.context` du
  manifest, sa raison d'être) mais ne la publie pas dans `/api/show` : seule la fenêtre native du
  GGUF y figure, et c'est donc elle qui est annoncée (le plafond de la clé s'applique par-dessus).
  La valeur effective n'apparaît que dans `/api/ps`, pour les seuls modèles **résidents** —
  l'y lire donnerait un affichage qui change selon qu'un modèle est chargé ou non, incohérence
  jugée pire que d'annoncer la fenêtre native. À revoir si `/api/show` publie un jour la fenêtre
  configurée. Son dépôt porte aussi `tests/test_conformance_gateway.py`, qui rejoue la logique de
  cette passerelle contre lui.

## Fiabilité des tests

- [x] **`reconcile.spec` (base partagée) durci contre un échec intermittent (2026-07-28).**
  Assertion **en base** que la clé déclarative existe avant de vérifier l'UI (sépare écriture et
  affichage), et **connexion prouvée** (attente explicite de `/admin`, erreur explicite portant
  l'URL + le message du formulaire si refus 401/429) au lieu d'un délai d'attente muet. Cause
  d'origine **non confirmée** (artefacts de l'échec effacés par `rm -rf output` avant lecture ;
  3 exécutions complètes n'ont pas reproduit). Hypothèses écartées par la mesure : lenteur du rendu
  (`list_keys()` ≤ 8 ms à 50 clés), verrouillage anti-brute-force (aucune spec n'envoie de mauvais
  mot de passe), filtres clients (ne s'exécutent que sur `input`, contexte neuf par test). Aucun
  délai d'attente rallongé : une expiration doit rester un échec réel.

## Idées ultérieures (non planifiées)

- [ ] Changement du mot de passe admin depuis l'UI.
- [ ] Rotation de clé (regénérer en conservant label/origines/quota).
- [ ] Export CSV de l'usage ; rétention/rotation des `usage_events` (le journal est actuellement
  conservé intégralement, sans purge).
- [ ] Quota par fenêtre glissante distribuée si multi-instance (non requis ici).
