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
- [x] **Build des images sur la Jetson (aarch64)** — gateway + Caddy buildés OK ; `dns.providers.scaleway`
  présent dans le binaire. *Note : le plugin scaleway v0.2.2 impose Caddy 2.11 + `GOTOOLCHAIN=auto`.*
- [x] **Smoke non-disruptif sur la Jetson** : proxy (port libre) → **vrai Ollama** avec la clé Gram
  → 200 / 16 modèles ; sans clé → 401 ; health 200. Sans toucher nginx/11435/Gram. Nettoyé.
- [~] **Cutover prod Jetson** : retrait nginx, `runProd`, cert DNS-01, bascule Gram http→https,
  preuves live — bloqué sur `SCW_SECRET_KEY` + fenêtre de cutover (cf. DAT §6). Non commencé.
- [~] **Cutover Gram** `OLLAMA_BASE_URL` http→https — à coordonner après bascule prod.

## Idées ultérieures (non planifiées)

- [ ] Changement du mot de passe admin depuis l'UI.
- [ ] Rotation de clé (regénérer en conservant label/origines/quota).
- [ ] Export CSV de l'usage ; rétention/rotation des `usage_events`.
- [ ] Quota par fenêtre glissante distribuée si multi-instance (non requis ici).
