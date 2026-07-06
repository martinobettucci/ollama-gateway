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
- [x] Caddy + module DNS Scaleway (Dockerfile.caddy) ; Caddyfile prod + staging (`tls internal`).
- [x] Import de clé existante par valeur (migration) — *test_keys (import), CLI bootstrap*.
- [~] **Build des images sur la hôte self-hosted (aarch64)** — à valider `docker compose build` sur la box
  (Docker Desktop indisponible côté dev WSL ; app pur Python → build attendu OK). Reste à exécuter.
- [~] **Déploiement prod hôte self-hosted** : import clé client-exemple, retrait nginx, `runProd`, cert DNS-01, preuves
  live — bloqué sur `SCW_SECRET_KEY` + fenêtre de cutover (cf. DAT §6). Non commencé.
- [~] **Cutover client-exemple** `OLLAMA_BASE_URL` http→https — à coordonner après bascule prod.

## Idées ultérieures (non planifiées)

- [ ] Changement du mot de passe admin depuis l'UI.
- [ ] Rotation de clé (regénérer en conservant label/origines/quota).
- [ ] Export CSV de l'usage ; rétention/rotation des `usage_events`.
- [ ] Quota par fenêtre glissante distribuée si multi-instance (non requis ici).
