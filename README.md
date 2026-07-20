# ollama-gateway — passerelle de gestion de clés Ollama

Passerelle d'authentification devant un ou plusieurs Ollama : **clés API par client**, **restriction
d'origine** (IP/CIDR), **quotas** (plafond mensuel de tokens + rate-limit), **serveurs d'exécution**
(local + distants, une clé ↦ un serveur, restriction de modèles agnostique de l'API),
**journalisation d'usage**, et **panel d'admin web LAN-only**. Le TLS du domaine public est terminé
par **Caddy** (challenge ACME DNS-01 Scaleway — aucun port entrant requis hormis celui déjà forwardé).

Elle remplace l'ancien reverse-proxy nginx mono-clé et proxifie les endpoints **d'inférence et de
lecture** (`/api/*`, `/v1/*`), en streaming (NDJSON/SSE), avec strip de la clé cliente avant
l'amont. Les endpoints de **gestion du catalogue** (`pull`/`push`/`delete`/`create`/`copy`/`blobs`)
ne sont **jamais** proxifiés (403) — la gestion des modèles se fait depuis la console d'admin.

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
python -m pytest                       # suite unitaire + intégration

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
- **Fail-closed en prod** : refus de démarrer si un secret critique est absent/par défaut, ou si le
  rôle admin se lierait à « toutes interfaces ». Clés hautement aléatoires, jetons distants chiffrés
  au repos (Fernet), CSRF same-origin + anti-brute-force du login, en-têtes de sécurité (HSTS/CSP),
  conteneur non-root, image de base épinglée par digest.
- **Gate de sécurité avant tout déploiement** : `./runProd` lance `scripts/security-sweep.sh`
  (secrets, CVE des dépendances, SAST, suite de tests) et **refuse de déployer** en cas de découverte.

## Licence

**Ollama Gateway est _source-available_, pas OSI-open-source** : le code est ouvert et libre
d'usage, mais l'usage à très grande échelle est encadré. Termes exacts : [LICENSE](LICENSE).

- ✅ **Gratuit** — utilisez, modifiez, distribuez et auto-hébergez, y compris en entreprise, **tant
  que l'ensemble de vos instances (agrégées par entité) sert ≤ 1 milliard de tokens par mois**.
- 💼 **Au-delà du seuil** — licence commerciale requise : **somme libératoire unique de 29 € HT par
  installation**, usage ensuite **illimité** (ex. 3 instances → 87 € HT). Écrivez à
  **contact@p2enjoy.studio**, objet « Licence Ollama Gateway ».
- 🔒 **Paternité** — conservez le fichier `LICENSE` et l'attribution à l'auteur : cloner le dépôt
  pour retirer la licence n'est pas autorisé.
- 🤝 **Sur l'honneur** — **le logiciel ne vous surveille pas** : aucun comptage à distance, aucune
  télémétrie, aucun bridage. Le respect du seuil repose entièrement sur votre bonne foi. Si vous le
  dépassez, jouez le jeu — c'est ce qui garde le projet ouvert pour tout le monde.

© 2026 Martino Bettucci — P2Enjoy SAS.
