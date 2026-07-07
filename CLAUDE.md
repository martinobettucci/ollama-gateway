# CLAUDE.md

Lu au début de chaque session. Conventions de travail **durables** du responsable
(martino.bettucci@gmail.com). À respecter sans avoir à les redemander.

La section « Conventions génériques » est **transportable telle quelle dans tout projet**
du responsable ; la section « Spécifique à ce repo » est le seul bloc propre au projet.

## Conventions génériques (transportables — toujours valables)

### Stack & structure

- **Langages.** Python pour l'IA / le ML et les services ; **React + Vite** pour les UI.
- **Tout dockerisé**, avec **profils dev / staging / prod** : un `docker-compose` par profil
  et des lanceurs **`runDev` / `runStaging` / `runProd`**.
- **Dev = fully self-contained & fully self-seeded** : aucun service externe requis ; la base
  est recréée et peuplée à chaque run → **tout test E2E est automatisable** de bout en bout.
- **Staging / prod** : des **`.env` dédiés**, chaque variable **commentée** (rôle + valeur attendue).

### UI / UX (règle dure)

- **Charte P2Enjoy SAS obligatoire** dans toute génération d'interface :
  bleu `#23468C` (primaire) · vert `#238C33` (succès) · jaune `#D9CF4A` (accent) ·
  rouge `#F24141` (danger) · noir `#0D0D0D` (encre). Thème clair, cartes `rounded-xl`,
  nav en pilules, codage par catégorie avec les 4 couleurs — référence : p2enjoy.studio.
- Chaque projet exporte son **`docs/DESIGN_SYSTEM.md`** (tokens, composition, IA) et
  tout travail d'UI passe par un **vrai skill UI/UX** (ex. `ui-ux-pro-max`), jamais un
  thème générique « AI slop ». Icônes vectorielles (lucide), jamais d'emoji-icônes.
- **Architecture d'information type Netlify** pour les outils de gestion : l'objet métier
  de premier niveau (projet/principal) est le citoyen de première classe ; les
  environnements sont des **contextes d'override** — tout existe partout par défaut,
  on ne définit que des surcharges.

### Documentation

- **Docs toujours à jour** : `CHANGELOG.md` (journal des changements) et `README.md` à la racine
  de tout projet. Tâche exploratoire ⇒ tenir un **journal de réflexion dans `/docs`**. Toujours
  écrire/maintenir un **DAT** (dossier d'architecture technique) dans `/docs`, avec les
  **instructions de lancement dev** et la **description des données seeds**.
- **CHANGELOG à deux chapitres `[Non publié]` / `[Publié]` (règle dure).** Le `CHANGELOG.md` porte
  DEUX chapitres : **`## [Non publié]`** en tête (tampon des changements pas encore déployés) puis
  **`## [Publié]`** (ce qui tourne en prod). **Toute nouvelle entrée s'ajoute TOUJOURS sous
  `[Non publié]`** — c'est là que va le codeur (humain ou IA). **À CHAQUE déploiement en production,
  après avoir vérifié que la prod tourne bien le dernier code, on DÉPLACE l'intégralité du contenu
  de `[Non publié]` sous `[Publié]`** (en tête de `[Publié]`, avec une ligne `### Déployé en
  production — <date> (migrations ≤ <n>)`), **puis on laisse `[Non publié]` VIDE** avec le
  placeholder « _Rien à publier pour le moment…_ ». On ne déclare jamais « Publié » quelque chose
  qui n'est pas réellement déployé et vérifié en prod.
- **`docs/manual.md` = doc PUBLIC du fonctionnement de l'app, toujours synchrone (règle dure).**
  Explication pédagogique + schémas Mermaid du fonctionnement. **Tout changement de comportement
  du backend doit mettre à jour ce doc dans le MÊME chunk de travail.** Destiné à être publié
  dans l'UI à côté du changelog ⇒ mêmes règles que le CHANGELOG : zéro secret, zéro hôte/IP/clé,
  aucune topologie d'infrastructure réelle — noms de variables d'env autorisés, valeurs et
  topologie jamais.

### Exécution & vérification

- **Démarrer le daemon Docker** au début de chaque session (cf. `.claude/hooks/session-start.sh`).
- **Vérification en vision, pas seulement les TU.** Pour toute modification, produire des
  **screenshots JPEG** (et, si pertinent, une **vidéo `.webm`** via Playwright) puis **les
  observer en mode vision** pour s'assurer de la bonne exécution — ne pas se fier aux seuls
  tests unitaires.
- **`git pull` avant de tester / clore** une session : d'autres devs peuvent travailler sur la branche.
- **INTERDICTION ABSOLUE de brancher (règle dure, aucune exception).** Ne **JAMAIS** créer de
  branche, de worktree, ni travailler ailleurs que dans **le code courant et la branche courante**.
  Pas de `git branch`, pas de `git checkout -b`, pas de `git worktree`, pas d'isolation
  `worktree` pour les sous-agents. Si plusieurs agents/devs travaillent en parallèle et que ça
  crée des conflits : **on fait avec** — on les résout sur place dans la branche courante.
  Toute forme de branching finit en merge cauchemardesque ; c'est interdit, point final.
- **Commits** : messages en français, un commit par chunk cohérent et **vérifié** ; **push
  systématique** après chaque commit (étapes intermédiaires comprises).
- **Pas de délégation** : pas de sous-agents ; une seule tâche à la fois, séquentiellement.
- **Definition of Done (stricte — jamais de complaisance).** Ne **jamais** marquer une tâche
  « terminée » qu'on vient juste de commencer. Une tâche n'est *done* **que** prouvée par :
  **tests unitaires + tests automatisés (API/intégration) + E2E Playwright verts**, **plus**
  vérification **en vision**. Tant que la preuve n'est pas faite, garder le statut **« en cours »**
  (`[~]`). On ne déclare pas fini ce qui n'est pas testé de bout en bout.
- **Règle « chaque tâche a SES tests » (non négociable).** **TOUTE** unité de backlog doit posséder
  **son propre jeu de tests dédiés : au minimum 1 test unitaire ET 1 test E2E Playwright** qui lui
  sont spécifiques (en plus, si pertinent, d'un test API/intégration). Pas de tâche `[x]` sans ses
  tests nommément rattachés. Une tâche dont le code existe mais dont les tests propres manquent reste
  `[~]`. Quand un comportement n'est pas observable en E2E (ex. interaction avec le daemon Docker),
  rendre la tâche testable par un chemin déterministe (données seedées, endpoint dédié, conteneur
  jetable) afin que la couverture unit + E2E reste réelle, jamais simulée ou contournée.

### Discipline du backlog lors d'une modification ou reprise

- **Réouverture obligatoire.** Toute unité de backlog déjà marquée `[x]` doit repasser `[~]` dès que
  son contrat, ses critères d'acceptation, son comportement, son implémentation, une dépendance qui
  affecte sa preuve, ou ses tests sont modifiés. Une baseline historiquement livrée ne permet pas de
  conserver `[x]` pendant que la nouvelle version reste à réaliser ou à revalider.
- **Réouvrir avant de travailler.** Le passage `[x]` → `[~]` se fait dès l'identification du changement,
  pas à la fin de la reprise. Si l'unité appartient au DoD d'une phase déclarée atteinte, réouvrir aussi
  le statut global de la phase.
- **Audit obligatoire à chaque reprise.** Avant de poursuivre une tâche existante, inspecter au minimum
  l'état local (`git status --short`, `git diff`, `git diff --cached`) et l'historique pertinent
  (`git log`, `git log -p`, `git blame` sur le backlog et les fichiers concernés) afin d'identifier :
  le commit qui avait justifié `[x]`, les modifications intervenues depuis, les changements locaux
  non commités, et les preuves/tests devenus invalides ou incomplets.
- **Ne jamais supposer le repo propre.** Les changements locaux peuvent appartenir à un autre
  intervenant. Les préserver, les comprendre et les inclure dans l'audit ; ne pas reset/revert pour
  retrouver artificiellement l'ancien état terminé.
- **Justification écrite dans le backlog.** Sur l'item rouvert, noter brièvement ce qui reste livré,
  ce qui a changé depuis la clôture et ce qui manque pour revenir à `[x]`. L'historique Git/local est
  la preuve de cette justification, pas la mémoire de la conversation.
- **Pas de réouverture cosmétique.** Une correction purement rédactionnelle ou de format sans impact
  sur le contrat, le code, les dépendances ni les preuves peut rester `[x]`. Dès qu'il existe un doute
  raisonnable sur la validité de la preuve antérieure, appliquer le marquage conservateur `[~]`.
- **Nouvelle clôture complète.** Une unité rouverte ne revient à `[x]` qu'après validation du contrat
  actuel selon la DoD stricte : tests unitaires, API/intégration, E2E et vision pertinents, plus docs
  synchronisées. Ne jamais réutiliser les seules preuves de l'ancienne version.

## Spécifique à ce repo (ollama-gateway)

ollama-gateway = passerelle d'authentification devant un Ollama local : clés API par client
(hachées, secret affiché une seule fois), restriction d'origine (IP/CIDR), quotas (plafond
mensuel de tokens + rate-limit req/min), journalisation d'usage, panel d'admin web LAN-only
(Jinja, rendu serveur), TLS public terminé par Caddy (ACME DNS-01 Scaleway).

### Garde-fous critiques

- **Le proxy est la seule surface publique** (via Caddy). L'admin (`app/admin.py`) est
  **LAN-only** : il n'est jamais routé par Caddy ni forwardé vers Internet.
- **Secrets hachés au repos.** Clés API hachées (sha-256) dans SQLite, secret affiché
  **une seule fois** à la création ; mot de passe admin en pbkdf2. La clé cliente est
  **strippée** avant l'amont. Aucun secret en clair dans les logs, réponses, docs, repo.
- **Surface publique = surface documentaire.** `CHANGELOG.md` et `docs/manual.md` sont
  publiables : zéro secret, zéro hôte/IP réel, zéro topologie d'infrastructure (noms de
  variables d'env autorisés, valeurs jamais). Les détails d'infra restent dans `docs/DAT.md`.
- **UI sans build front (écart assumé).** L'admin est en Jinja2 rendu serveur — écart à la
  convention React + Vite, justifié dans `docs/DESIGN_SYSTEM.md` § 6. La charte P2Enjoy
  s'applique intégralement (tokens dans `app/templates/base.html`, icônes lucide via la
  macro `app/templates/_icons.html`).
- **Manuel utilisateur intégré, synchrone avec captures (règle dure).** `docs/manual.md` est
  affiché dans le panel via la modale « Manuel » (`GET /admin/manual`, images servies depuis
  `app/static/manual/`). Le manuel illustre **chaque fonctionnalité par une capture réelle**
  de l'application. À **tout** changement d'UI ou de comportement : mettre à jour le texte du
  manuel ET régénérer les captures dans le même chunk (`cd e2e && npm test && npm run
  sync-manual`), puis vérifier en vision. Un manuel ou des captures périmés = tâche non finie.
- **Prod = `network_mode: host`** (Ollama écoute en loopback natif hors Docker) ; le proxy
  binde loopback, l'admin binde l'IP LAN. Ne jamais publier l'admin sur autre chose.

### Lancer en dev

```bash
./runDev          # teardown + build + up (proxy + admin + faux Ollama), base recréée et re-seedée
# Admin : http://localhost:8788/admin (mdp: adminpass) · Proxy : http://localhost:8787/_proxy_health
# Tests : .venv/bin/python -m pytest -q
# E2E   : cd e2e && npx playwright test   (captures .jpg + vidéos .webm dans e2e/output/)
```

### Carte du repo

- `docs/DAT.md` — architecture technique (stack, services, lancement, seeds, déploiement).
- `docs/DESIGN_SYSTEM.md` — design system (charte P2Enjoy, tokens, composition, écarts).
- `docs/JOURNAL.md` — journal chronologique des décisions.
- `docs/BACKLOG.md` — backlog phasé (DoD par phase ; marquage `[ ]`/`[~]`/`[x]`).
- `docs/manual.md` — doc publique du fonctionnement (synchrone avec le code, règle dure).
- `app/` (FastAPI : `proxy.py`, `admin.py`, `keys.py`, `servers.py`, `quotas.py`, `usage.py`,
  `crypto.py`, `templates/`) · `db/migrations/` (SQL idempotent, concurrent-safe via `flock`)
  · `devfixtures/` (faux Ollama) · `tests/` (pytest) · `e2e/` (Playwright, serveurs uvicorn
  locaux + base dédiée re-seedée à chaque run).
- **Serveurs d'exécution** : `servers.py` (registre local+distants, sonde, `ensure_default`),
  jeton distant chiffré (`crypto.py`, Fernet/`P2E_MASTER_KEY`), une clé ↦ un serveur
  (`api_keys.server_id`), allowlist de modèles par clé (`key_models`) appliquée par le proxy
  quelle que soit l'API (403 + filtrage `/api/tags`·`/v1/models`).
- `Caddyfile`, `Dockerfile.caddy` — edge TLS ; `runDev`/`runStaging`/`runProd` + un
  `docker-compose` par profil.
