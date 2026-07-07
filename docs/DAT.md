# DAT — ollama-gateway (dossier d'architecture technique)

## 1. But & contexte

Fournir devant un Ollama local (hôte self-hosted, systemd, `127.0.0.1:11434`, sans auth) une passerelle qui :
gère des **clés API par client**, **restreint l'origine** (IP/CIDR par clé), applique des **quotas**
(plafond mensuel de tokens + rate-limit), **journalise l'usage**, et offre un **panel d'admin
web LAN-only**. Le TLS public de `llm.example.com` est terminé par **Caddy** (ACME DNS-01 Scaleway).

Elle remplace l'ancien reverse-proxy nginx mono-clé (`/etc/ancien-reverse-proxy`,
écoute `:11435`), atteint depuis Internet par le forward box `21434 → 11435`.

## 2. Composants

| Rôle | Module | Bind | Exposition |
|------|--------|------|------------|
| proxy d'inférence | `app/proxy.py` | loopback `127.0.0.1:8787` | via Caddy uniquement |
| admin web | `app/admin.py` | IP LAN `:8788` | LAN uniquement (jamais forwardé) |
| TLS/edge | Caddy (`Caddyfile`) | `:11435` (cible du forward) | public |
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
- `usage_events(...)` — append-only, une ligne par requête (autorisée ou refusée) : clé, IP,
  méthode, chemin, modèle, statut, durée, tokens prompt/complétion, octets in/out.
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
3. `401` si clé absente/inconnue/désactivée ; `403` si origine hors allowlist ; `429` si quota ;
   `503` si serveur rattaché désactivé/absent ; `403` si modèle hors allowlist de la clé (le
   `model` est lu à la racine du corps → même gate pour Ollama, OpenAI chat/responses, Anthropic).
4. Sinon : relais streaming vers **le serveur rattaché** (`server.base_url`), **sans** l'en-tête
   `Authorization` client (jeton du serveur distant injecté à la place, déchiffré) ; les listings
   `/api/tags` et `/v1/models` sont filtrés à l'allowlist ; comptage des tokens dans le payload de
   fin (`prompt_eval_count`/`eval_count` ou `usage`) ; journalisation.

## 5. Lancement

```bash
./runDev        # dev self-contained (faux Ollama + proxy 8787 + admin 8788), base re-seedée
./runStaging    # chaîne TLS complète en local (Caddy tls internal, https://localhost:8443)
./runProd       # hôte self-hosted : Caddy DNS-01 + proxy + admin (host network). Requiert .env.prod
```

Tests : `python -m pytest` (56) ; `cd e2e && npm test` (6 E2E + captures `e2e/output/`).

## 6. Déploiement hôte self-hosted & migration (procédure)

Pré-requis : `.env.prod` renseigné (dont `SCW_SECRET_KEY`, `ADMIN_BIND_IP`, `ADMIN_PASSWORD`,
`ADMIN_SESSION_SECRET`, `P2E_MASTER_KEY`). **Aucun secret committé.** `P2E_MASTER_KEY` chiffre les
jetons des serveurs distants : la changer rend les jetons stockés illisibles (il faut les ressaisir).

1. **Amener le code** sur la hôte self-hosted (clone/rsync du repo).
2. **Importer la clé historique** (pour ne casser aucun client) — la valeur vient de l'ancien
   vhost nginx, passée en env, jamais écrite dans le repo :
   ```bash
   IMPORT_KEY_VALUE=<clé-historique> IMPORT_KEY_LABEL=client \
   IMPORT_KEY_ORIGINS=203.0.113.10,192.168.0.0/24,127.0.0.1 \
   GATEWAY_DB_PATH=<volume>/gateway.db python -m app.bootstrap import-key
   ```
   (origine `203.0.113.10` = `client.example.com`.)
3. **Libérer `:11435`/`:80`** : sauvegarder puis désactiver le vhost nginx `ancien-proxy`
   (`nginx -T` pour archiver la conf), `systemctl stop/disable nginx`.
4. **Démarrer la passerelle** : `./runProd` (Caddy obtient le cert `llm.example.com` via DNS-01 ;
   proxy en loopback ; admin sur `ADMIN_BIND_IP:8788`).
5. **Vérifier** : `curl https://llm.example.com:21434/_proxy_health` (TLS valide, 200) ; un appel
   `/api/chat` avec la clé importée ; l'admin en LAN.
6. **Cutover client-exemple** : passer `OLLAMA_BASE_URL` (et `OLLAMA_EMBED_BASE_URL`) de client-exemple (prod Scaleway)
   de `http://…:21434` à `https://llm.example.com:21434`, recréer agent+api, vérifier un cycle réel.
   ⚠️ `llm.example.com` a un AAAA (box) **non routé par le forward** → épingler l'IPv4 côté client-exemple
   dans `/etc/hosts` (`198.51.100.1 llm.example.com`) pour éviter les timeouts IPv6 ; le cert reste
   valide (SNI = hostname).
7. **Rollback** : `docker compose stop caddy` sur la hôte self-hosted + `systemctl start nginx` (config
   sauvegardée `~/ancien-proxy.bak`) + repointer client-exemple sur `http://198.51.100.1:21434`
   (`.env.bak`).

## 7. Sécurité / invariants

- Clés hachées en base ; secret montré une seule fois.
- Admin jamais routé par Caddy (seuls les chemins d'inférence le sont) ; bind LAN only.
- `Authorization` client strippé avant l'amont.
- Secrets hors repo (`.gitignore` : `.env.prod`, `*.db`). Surface publique (CHANGELOG) sans secret.
- TLS obtenu par DNS-01 (sortant) : n'exige aucun port entrant hormis celui déjà forwardé.
