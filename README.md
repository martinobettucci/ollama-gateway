<p align="right"><img src="docs/flags/fr.svg" width="20" alt=""> <strong>Français</strong> · <a href="README.en.md"><img src="docs/flags/en.svg" width="20" alt=""> English</a></p>

# ollama-gateway — passerelle de gestion de clés Ollama

> **Interface entièrement traduite dans les 24 langues officielles de l'Union européenne.**

## Showcase

<p align="center">
  <a href="docs/showcase/showcase.webm"><img src="docs/showcase/showcase.gif" alt="Tour guidé de la passerelle" width="760"></a>
  <br><em>Tour guidé — <a href="docs/showcase/showcase.webm">vidéo (webm)</a> · <a href="docs/showcase/showcase.mp4">mp4</a></em>
</p>

Passerelle d'authentification devant un ou plusieurs Ollama : **clés API par client**, **restriction
d'origine** (IP/CIDR), **quotas** (plafond mensuel de tokens + rate-limit), **serveurs d'exécution**
(local + distants, une clé ↦ un serveur, restriction de modèles agnostique de l'API),
**journalisation d'usage**, et **panel d'admin web LAN-only**. Le TLS du domaine public est terminé
par **Caddy** (challenge ACME DNS-01 Scaleway — aucun port entrant requis hormis celui déjà forwardé).

Elle remplace l'ancien reverse-proxy nginx mono-clé et proxifie les endpoints **d'inférence et de
lecture** (`/api/*`, `/v1/*`), en streaming (NDJSON/SSE), avec strip de la clé cliente avant
l'amont. Les endpoints de **gestion du catalogue** (`pull`/`push`/`delete`/`create`/`copy`/`blobs`)
ne sont **jamais** proxifiés (403) — la gestion des modèles se fait depuis la console d'admin.

## Aperçu

| | |
|---|---|
| ![Tableau de bord](app/static/manual/01-dashboard.jpg) | ![Graphes d'usage d'une clé](app/static/manual/27-key-charts.jpg) |
| **Tableau de bord** — clés, quotas, création | **Détail d'une clé** — graphes (horizons, valeurs), usage par modèle |
| ![Serveurs & compatibilité](app/static/manual/06-servers.jpg) | ![Monitoring d'un serveur](app/static/manual/17-monitor.jpg) |
| **Serveurs d'exécution** + matrice de compatibilité d'API | **Monitoring** — consommation, statuts, par clé et par modèle |

## Fonctionnalités

- **Clés API par client** — hachées (sha-256), secret affiché **une seule fois**, révocables.
- **Restriction d'origine** par clé (IP/CIDR, résistante à l'usurpation de `X-Forwarded-For`).
- **Quotas** — plafond mensuel de tokens + rate-limit (req/min), et plafonds/expiration « de vie »
  (essai à coût plafonné).
- **Serveurs d'exécution multiples** — local + distants (jeton chiffré au repos), une clé ↦ un
  serveur, **serveur de repli** automatique sur panne 5xx/connexion.
- **Restriction de modèles et d'API par clé** — agnostique du schéma (Ollama natif, OpenAI,
  Anthropic), filtrage des listings ; **génération d'images** en capacité séparée.
- **Gestion du catalogue** (télécharger / supprimer des modèles) depuis la console — **jamais**
  exposée au client (le proxy refuse `pull`/`delete`/… en 403).
- **Journalisation & monitoring** — usage par requête, **graphes temporels** (horizons
  24 h → 3 mois, échelles d'axes, valeurs par point), **usage par modèle**, visionneuse du contenu
  complet des requêtes (grep), bannissement d'origines.
- **Panel d'admin LAN-only** rendu serveur, **24 langues de l'UE**, charte P2Enjoy.
- **Edge TLS Caddy** (ACME DNS-01, aucun port entrant requis), tout **dockerisé** (dev self-seeded,
  prod `network_mode: host`) avec **gate de sécurité avant déploiement**.

💡 **Manuel en ligne intégré** — pour faciliter la prise en main, le panel embarque un **manuel
illustré** (bouton **« Manuel »** de la navigation) qui explique chaque écran avec une capture
réelle de l'application. Source publique : [docs/manual.md](docs/manual.md).

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
d'usage, mais l'usage à très grande échelle est encadré. Termes exacts : [LICENSE.md](LICENSE.md).

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
