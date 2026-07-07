# ollama-gateway — passerelle de gestion de clés Ollama

Passerelle d'authentification devant un ou plusieurs Ollama : **clés API par client**, **restriction
d'origine** (IP/CIDR), **quotas** (plafond mensuel de tokens + rate-limit), **serveurs d'exécution**
(local + distants, une clé ↦ un serveur, restriction de modèles agnostique de l'API),
**journalisation d'usage**, et **panel d'admin web LAN-only**. Le TLS du domaine public est terminé
par **Caddy** (challenge ACME DNS-01 Scaleway — aucun port entrant requis hormis celui déjà forwardé).

Elle remplace l'ancien reverse-proxy nginx mono-clé et proxifie **tous** les endpoints Ollama
(`/api/*`, `/v1/*`), en streaming (NDJSON/SSE), avec strip de la clé cliente avant l'amont.

## Architecture

```
Client externe ──https──► Caddy (TLS DNS-01) ──► proxy (auth/origine/quota/usage) ──► Ollama 127.0.0.1:11434
                                                       │
Admin (LAN) ──http──► admin (login) ── SQLite (WAL) ──┘
```

- **proxy** (`app/proxy.py`) — exposé via Caddy, bind loopback. Valide `Authorization: Bearer <clé>`,
  vérifie l'origine et les quotas, journalise, relaie en streaming, strip la clé.
- **admin** (`app/admin.py`) — bind IP LAN uniquement, login mot de passe, CRUD des clés + dashboard.
- **SQLite** partagé (WAL) entre les deux rôles.

Voir [docs/DAT.md](docs/DAT.md) pour le détail (services, données, lancement, déploiement) et
[docs/manual.md](docs/manual.md) pour le manuel public du fonctionnement.

## Lancer en dev (self-contained, self-seeded)

```bash
./runDev        # faux Ollama + proxy + admin ; SQLite re-seedée à chaque run
# Admin : http://localhost:8788/admin  (mdp: adminpass)
# Proxy : http://localhost:8787/_proxy_health
# Clé de démo : sk-ollama-devdemokey0000000000000000000000000000000000000000000000000
```

Test d'un appel proxifié :
```bash
curl -s http://localhost:8787/api/chat \
  -H "Authorization: Bearer sk-ollama-devdemokey000000000000000000000000000000000000000000000000" \
  -d '{"model":"demo:latest","stream":true}'
```

## Tests

```bash
# Unitaires + intégration (Python)
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m pytest                       # 31 tests

# E2E (Playwright : admin UI + proxy), captures .jpg + vidéo .webm dans e2e/output/
cd e2e && npm install && npm test
```

## Staging / Prod

- `./runStaging` — chaîne complète avec Caddy (`tls internal`) + faux upstream, pour valider le
  routage/TLS localement (`https://localhost:8443/…`, `curl -k`).
- `./runProd` — sur l'hôte de prod : Caddy (DNS-01 Scaleway) + proxy + admin en `network_mode: host`.
  Requiert `.env.prod` (copier `.env.prod.example`). Voir [docs/DAT.md](docs/DAT.md) §Déploiement.

## Sécurité

- La clé cliente est **hachée** (sha-256) en base, jamais stockée en clair ; affichée une seule
  fois à la création.
- L'admin n'est **jamais** exposé par Caddy (seuls `/api/*`, `/v1/*`, `/_proxy_health` le sont) et
  bind sur l'IP LAN uniquement.
- Aucun secret dans le repo : `SCW_SECRET_KEY`, mot de passe admin, clés — tout vit en `.env` /
  base, hors git (cf. `.gitignore`).
