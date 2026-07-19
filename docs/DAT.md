# DAT — ollama-gateway (dossier d'architecture technique)

## 1. But & contexte

Fournir devant un Ollama local (hôte self-hosted, systemd, `127.0.0.1:11434`, sans auth) une
passerelle qui : gère des **clés API par client**, **restreint l'origine** (IP/CIDR par clé),
applique des **quotas** (plafond mensuel de tokens + rate-limit), **journalise l'usage**, et offre
un **panel d'admin web LAN-only**. Le TLS public (domaine `GATEWAY_DOMAIN`) est terminé par
**Caddy** (ACME DNS-01 Scaleway).

Elle remplace un ancien reverse-proxy mono-clé. L'edge TLS écoute sur le port `GATEWAY_TLS_PORT`,
atteignable depuis Internet via un forward NAT du routeur (déploiement adapté à un port non standard).

## 2. Composants

| Rôle | Module | Bind | Exposition |
|------|--------|------|------------|
| proxy d'inférence | `app/proxy.py` | loopback `127.0.0.1:8787` | via Caddy uniquement |
| admin web | `app/admin.py` | IP LAN `:8788` | LAN uniquement (jamais forwardé) |
| TLS/edge | Caddy (`Caddyfile`) | `:${GATEWAY_TLS_PORT}` (cible du forward NAT) | public |
| upstream | Ollama (systemd) | `127.0.0.1:11434` | local uniquement |

Les deux rôles Python partagent une même image (`Dockerfile`) ; le rôle est choisi par
`$GATEWAY_ROLE` dans `entrypoint.sh`. En prod, proxy/admin/Caddy tournent en `network_mode: host`
car Ollama est en loopback natif (hors Docker).

### Modules applicatifs
- `config.py` — configuration par environnement.
- `db.py` — connexions SQLite (WAL, FK), migrations idempotentes (`db/migrations/*.sql`).
- `auth.py` — génération/hachage des clés (sha-256), mot de passe admin (pbkdf2), parsing Bearer.
- `keys.py` — CRUD clés, lookup par hash, contrôle d'origine, auth admin.
- `usage.py` — écriture des événements + agrégats (mensuel, rpm, par jour, globaux).
- `quotas.py` — décision d'autorisation (plafond mensuel + rate-limit).
- `bootstrap.py` — CLI : `init`, `ensure-admin`, `seed-dev`, `import-key`.
- `admin.py` sert aussi le **manuel utilisateur** : `GET /admin/manual` rend `docs/manual.md`
  (lib `markdown`, blocs Mermaid retirés, images remappées) dans une modale ; captures servies
  depuis `app/static/manual/` (montage `/static`), régénérées par l'E2E (`npm run sync-manual`).
  Seul `docs/manual.md` entre dans l'image Docker (`.dockerignore` : `!docs/manual.md`).
- `servers.py` — **serveurs d'exécution** (« executors ») : registre des upstreams Ollama
  (local + distants), CRUD, sonde de disponibilité (`GET {base}/api/tags`), reconciler
  `ensure_default` (crée le serveur local depuis `$OLLAMA_UPSTREAM`, réassigne les clés
  orphelines). Chaque clé pointe un serveur (`api_keys.server_id`) ; allowlist de modèles par
  clé (`key_models`). Le proxy route vers `server.base_url`, applique la restriction de modèle
  (agnostique de l'API : `model` à la racine du corps) et filtre `/api/tags` + `/v1/models`.
- `crypto.py` — **chiffrement réversible au repos** (Fernet, clé dérivée de `$P2E_MASTER_KEY`)
  du jeton Bearer d'un serveur distant. Réversible (à réémettre vers l'amont), contrairement aux
  hachages one-way de `auth.py`.
- `bans.py` — liste de bannissement **globale** d'origines (IP/CIDR), appliquée par le proxy
  avant l'auth ; pilotée depuis la console de logs.
- `reqlog.py` — journal de **contenu** des requêtes **sur fichiers** (hors base), secrets
  masqués ; CLI `compact` (cron) : gzip des heures passées + purge (rétention par clé). **Lecture
  pour la console** : `list_keys_with_logs`/`list_files`/`read_content` (filtre grep, gzip
  transparent) + `resolve` (noms validés, confinement anti-traversal) ; servis par
  `GET /admin/logs/content` (viewer + grep) et `/admin/logs/content/raw` (téléchargement brut).
  Le rôle **admin** doit voir le même `REQUEST_LOG_DIR` que le proxy (volume partagé).
- `whois.py` — résolution **RDAP** d'une IP (bouton WHOIS des origines) ; court-circuit local.
- `i18n.py` — **internationalisation** du panel : un catalogue **YAML par langue**
  (`app/locales/<code>.yaml`), aplati en clés pointées au chargement, source de référence `fr`.
  `translate(key, lang, **params)` interpole les `{param}` (via `str.format_map`, placeholder
  inconnu laissé intact) et **replie** langue absente → `fr` → clé brute. `negotiate(request)`
  choisit la langue par **priorité session → cookie → `Accept-Language` → défaut fr**, bornée à
  l'ensemble activé (`SUPPORTED_LANGS`, vide = les 24 langues UE). Les templates reçoivent `t`,
  `lang` et `languages` via un wrapper de rendu (`admin.render`) ; la route `POST /admin/lang`
  écrit `session['lang']` (redirection bornée à `/admin`, anti-open-redirect). Les libellés
  utilisés en JavaScript (sondes de modèles, essais, WHOIS) sont exposés en JSON/`data-*` puis
  traduits côté client. Aucune dépendance hors **PyYAML**. Les 24 langues officielles de l'UE sont
  fournies et **complètes clé-à-clé** (test dédié `tests/test_i18n.py`).

## 3. Données (SQLite)

- `api_keys(id, label, key_prefix, key_hash UNIQUE, enabled, note, created_at, last_used_at)` —
  la clé n'est jamais stockée en clair (uniquement son sha-256) ; `key_prefix` = début lisible.
- `key_origins(key_id, cidr)` — allowlist d'origine par clé ; aucune ligne ⇒ aucune restriction.
- `key_quotas(key_id, monthly_token_cap, rpm_limit)` — plafonds optionnels (NULL = illimité).
- `servers(id, name, base_url, auth_token_enc, is_default, enabled, last_checked_at, last_online,
  last_models)` — serveurs d'exécution ; `auth_token_enc` = jeton Bearer distant **chiffré**
  (Fernet), jamais en clair ; `last_models` = JSON des modèles détectés au dernier test.
- `api_keys.server_id` (FK `servers`, ON DELETE SET NULL) — serveur rattaché ; `key_models(key_id,
  model)` — allowlist de modèles par clé (aucune ligne = tous autorisés).
- **Compatibilité d'API (migration 0005).** `key_apis(key_id, api)` — allowlist de **familles
  d'API** par clé (`ollama`/`openai`/`anthropic`) ; aucune ligne = toutes autorisées ; appliquée par
  le proxy en **allow/forbid de chemin** (`app/apis.py::family_for_path`, listings exemptés), sans
  validation de schéma. `servers.last_compat`/`last_compat_at` — matrice JSON du dernier test
  d'accessibilité des chemins (`servers.run_compat`, catalogue `apis.CATALOG`).
- **Cibles publiques (migration 0006).** `targets(id, name, base_url, is_default, created_at)` — URL
  publiques vues des clients ; `api_keys.target_id` (FK, ON DELETE SET NULL) — cible rattachée,
  utilisée **uniquement** pour générer les variables d'environnement (n'affecte pas le routage).
  Défaut indélébile seedé de `PUBLIC_BASE_URL` (auto-réparation du placeholder). `app/targets.py`.
- **Expiration / plafonds de vie (migration 0007).** `api_keys.total_token_cap` /
  `total_request_cap` / `expires_at` / `idle_expiry_days` (NULL = aucun) — plafonds **absolus** et
  échéances appliqués par `quotas.check` (distinct du rate-limit et du plafond mensuel).
- **Repli & monitoring (migration 0008).** `api_keys.fallback_server_id` (FK, ON DELETE SET NULL) —
  serveur de repli ; le proxy rejoue la requête vers lui sur 5xx/erreur de connexion du primaire
  (`_send_chain`). `usage_events.server_id` — serveur ayant **réellement** traité (repli inclus),
  base du monitoring par serveur/clé (`usage.server_*`, graphiques SVG `app/charts.py`).
- **Génération d'images (migration 0009).** Capacité séparée du texte, portée par `key_apis`
  (`ollama-image` / `openai-image`). Les modèles d'image (namespace `x/…`) ont une allowlist
  **séparée** `key_image_models(key_id, model)`. Le proxy déduit la capability via
  `apis.capability_for_request(path, model)` : `/v1/images/*` → `openai-image` ; `/api/generate`
  avec modèle `x/…` → `ollama-image` (Ollama génère l'image sur le MÊME chemin que le texte). Le
  gating de modèle est alors fait contre `key_image_models` (et non `key_models`). Relais de test
  `servers.try_image` (onglet « Image » du panel, image d'entrée base64 acceptée).
- `usage_events(...)` — append-only, une ligne par requête (autorisée ou refusée) : clé, IP,
  méthode, chemin, modèle, statut, durée, tokens prompt/complétion, octets in/out, **server_id**.
  **Jamais purgé** ; exposé intégralement par la console de logs (`GET /admin/logs`).
- **Contenu complet des requêtes = HORS BASE** (`app/reqlog.py`) : fichiers `$REQUEST_LOG_DIR/
  key-<id>/<YYYY-MM-DD_HH>.jsonl` (un dossier par clé, un fichier par heure), secrets masqués.
  `api_keys.log_retention_days` (migration 0004, NULL → `REQUEST_LOG_RETENTION_DAYS`) pilote le
  cron `python -m app.reqlog compact` (gzip des heures passées + purge). `''` = désactivé.
- `banned_origins(id, cidr, reason, created_at)` (migration 0003) — liste de bannissement
  **globale** d'origines (IP `/32`·`/128` ou CIDR), appliquée par le proxy **avant l'auth** (403).
  Pilotée depuis la console de logs (`bans.py`). Distincte des `key_origins` (ALLOW par clé).
- `admin_auth(id=1, password_hash)` — mot de passe admin (pbkdf2).
- Migrations idempotentes **et concurrent-safe** (verrou `flock` : proxy/admin migrent en
  parallèle sur le même fichier). `busy_timeout` posé avant `PRAGMA journal_mode=WAL`.

### Seeds
- **dev** (`bootstrap seed-dev`, idempotent) : admin `adminpass` + clé de démo déterministe
  `sk-ollama-devdemokey…` (origines : toutes, sans quota) → E2E reproductibles.
- **prod** : aucun seed automatique de clé. Le mot de passe admin est posé au premier démarrage
  depuis `ADMIN_PASSWORD` (via `ensure-admin`, seulement s'il n'existe pas). La clé historique est
  importée explicitement (cf. §6).

## 4. Chemin d'une requête proxifiée

1. Caddy termine le TLS et route `/api/*|/v1/*|/_proxy_health` vers le proxy (loopback), en posant
   `X-Forwarded-For`.
2. Le proxy détermine l'IP source (XFF si le pair est de confiance — `TRUSTED_PROXY_IPS`).
2b. **Bannissement global** : si l'IP source ∈ `banned_origins` → `403` immédiat (avant l'auth).
3. `401` si clé absente/inconnue/désactivée ; `403` si origine hors allowlist ; `429` si quota ;
   `503` si serveur rattaché désactivé/absent ; `403` si modèle hors allowlist de la clé (le
   `model` est lu à la racine du corps → même gate pour Ollama, OpenAI chat/responses, Anthropic).
4. Sinon : relais streaming vers **le serveur rattaché** (`server.base_url`), **sans** l'en-tête
   `Authorization` client (jeton du serveur distant injecté à la place, déchiffré) ; les listings
   `/api/tags` et `/v1/models` sont filtrés à l'allowlist ; comptage des tokens dans le payload de
   fin (`prompt_eval_count`/`eval_count` ou `usage`) ; journalisation (métadonnées en base **et**,
   si `REQUEST_LOG_DIR` est défini, contenu complet sur fichiers via `reqlog`, secrets masqués).

**Cron de logs** (prod) : planifier `python -m app.reqlog compact` (p. ex. horaire) pour gzip les
heures passées et purger au-delà de la rétention par clé — via crontab hôte ou un service
périodique appelant `docker compose exec admin python -m app.reqlog compact`.

## 5. Lancement

```bash
./runDev        # dev self-contained (faux Ollama + proxy 8787 + admin 8788), base re-seedée
./runStaging    # chaîne TLS complète en local (Caddy tls internal, https://localhost:8443)
./runProd       # hôte self-hosted : Caddy DNS-01 + proxy + admin (host network). Requiert .env.prod
```

Tests : `python -m pytest` ; `cd e2e && npm test` (E2E + captures `e2e/output/`).

## 6. Déploiement (hôte self-hosted) & migration (procédure générique)

Pré-requis : `.env.prod` renseigné (dont `GATEWAY_DOMAIN`, `GATEWAY_TLS_PORT`, `SCW_SECRET_KEY`,
`ADMIN_BIND_IP`, `ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET`, `P2E_MASTER_KEY`, `PUBLIC_BASE_URL` —
URL publique vue des clients, utilisée par la modale de configuration client de l'admin).
**Aucun secret committé.** En prod, la passerelle **refuse de démarrer** si `ADMIN_SESSION_SECRET`
ou `P2E_MASTER_KEY` sont absents ou laissés au défaut dev (cf. `config.check_runtime_secrets`).
`P2E_MASTER_KEY` chiffre les jetons des serveurs distants : la changer rend les jetons stockés
illisibles (il faut les ressaisir).

> **Bascule vers l'utilisateur non-root de l'image :** un volume `/data` préexistant créé sous root
> doit être `chown`é une fois vers l'UID applicatif (`docker compose run --rm --user root proxy
> chown -R app:app /data`) avant de relancer, sinon la base n'est pas inscriptible.

1. **Amener le code** sur l'hôte de prod (clone/rsync du repo).
2. **Importer une clé historique** (pour ne casser aucun client existant) — la valeur vient de
   l'ancien reverse-proxy, passée en env, jamais écrite dans le repo :
   ```bash
   IMPORT_KEY_VALUE=<clé-historique> IMPORT_KEY_LABEL=client \
   IMPORT_KEY_ORIGINS=<cidr-client>,127.0.0.1 \
   GATEWAY_DB_PATH=<volume>/gateway.db python -m app.bootstrap import-key
   ```
3. **Libérer le port `GATEWAY_TLS_PORT`** (et `:80` si occupé) : sauvegarder la conf de l'ancien
   reverse-proxy puis l'arrêter/désactiver.
4. **Démarrer la passerelle** : `./runProd` (Caddy obtient le cert de `GATEWAY_DOMAIN` via DNS-01 ;
   proxy en loopback ; admin sur `ADMIN_BIND_IP:8788`).
5. **Vérifier** : `curl https://<GATEWAY_DOMAIN>:<port-public>/_proxy_health` (TLS valide, 200) ; un
   appel `/api/chat` avec la clé importée ; l'admin en LAN.
6. **Cutover client** : passer `OLLAMA_BASE_URL` (et `OLLAMA_EMBED_BASE_URL`) du client de l'ancienne
   URL vers `https://<GATEWAY_DOMAIN>:<port-public>`, puis vérifier un cycle réel.
   ⚠️ Si le domaine a un enregistrement AAAA **non routé par le forward NAT**, épingler l'IPv4 côté
   client (`/etc/hosts`) pour éviter les timeouts IPv6 ; le cert reste valide (SNI = hostname).
7. **Rollback** : `docker compose stop caddy` + relancer l'ancien reverse-proxy (config sauvegardée)
   + repointer le client sur l'ancienne URL.

## 7. Sécurité / invariants

- Clés hachées en base (sha-256) ; secret montré une seule fois. Mot de passe admin en pbkdf2 +
  sel, comparaison à temps constant. Jetons des serveurs distants chiffrés au repos (Fernet).
- Admin jamais routé par Caddy (seuls les chemins d'inférence le sont) ; bind LAN only.
- `Authorization` / `x-api-key` / `cookie` client strippés avant l'amont ; contenu journalisé
  avec ces en-têtes masqués.
- **IP source résistante à l'usurpation** : le XFF n'est pris en compte que si le pair est de
  confiance (`TRUSTED_PROXY_IPS`), et l'IP réelle est lue à la **droite** de la chaîne (celle
  ajoutée par l'edge), en sautant les proxys de confiance — empêche l'usurpation d'origine et le
  contournement de ban via un `X-Forwarded-For` forgé.
- **Panel admin** : CSRF par **same-origin strict** (contrôle `Origin`/`Referer` sur les méthodes
  mutantes) en plus du cookie `SameSite=Lax` ; **verrouillage temporaire** du login après échecs
  répétés (anti-brute-force).
- **Fail-closed prod** : refus de démarrer si `ADMIN_SESSION_SECRET`/`P2E_MASTER_KEY` absents ou
  laissés au défaut dev (publics), **ou** si le rôle admin a un `ADMIN_HOST` vide/`0.0.0.0`/`::`
  (jamais exposé hors LAN par mégarde). **Conteneur non-root**, **image de base épinglée par
  digest**. Borne de taille de requête (`MAX_REQUEST_BYTES`, 413 au-delà) + `request_body` côté edge.
- **Endpoints de gestion du catalogue** (`pull`/`push`/`delete`/`create`/`copy`/`blobs`) **non
  proxifiés** (403) : la passerelle sert l'inférence, pas l'administration d'Ollama.
- **Rate-limit résistant à la concurrence** : les requêtes en vol (streaming) comptent dans le
  débit par clé (pas seulement les requêtes déjà journalisées).
- **URL amont validée** (schéma `http(s)`, plage link-local/métadonnées refusée) ; défense en
  profondeur contre une SSRF post-auth admin. **En-têtes de sécurité** : HSTS/nosniff (edge) ;
  CSP/`X-Frame-Options`/`Referrer-Policy` (panel).
- **Confidentialité des logs de contenu** : le corps des requêtes (prompts) est journalisé sur
  disque uniquement si `REQUEST_LOG_DIR` est posé ; `REQUEST_LOG_BODIES=0` conserve les
  métadonnées sans écrire les prompts. En-têtes secrets (`Authorization`/`x-api-key`/`cookie`)
  toujours masqués.
- **Gate de sécurité pré-déploiement** (`scripts/security-sweep.sh`, appelé par `./runProd`) :
  balayage secrets + CVE + SAST + tests ; toute découverte STOPPE le déploiement (contournement
  explicite `ALLOW_INSECURE_DEPLOY=1`).
- Secrets hors repo (`.gitignore` : `.env.prod`, `*.db`). Surface publique (CHANGELOG, manuel)
  sans secret, sans hôte/IP réel, sans topologie d'infrastructure.
- TLS obtenu par DNS-01 (sortant) : n'exige aucun port entrant hormis celui déjà forwardé.
