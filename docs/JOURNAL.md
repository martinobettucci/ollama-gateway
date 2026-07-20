# Journal — ollama-gateway

Journal chronologique des décisions (le plus récent en premier). Complète `CHANGELOG.md`
(quoi) par le **pourquoi**.

## 2026-07-20 — Configuration déclarative (headless / YAML), sous-phase 1 : réconciliation

- **Besoin : déployer sans WebUI, en décrivant l'infra dans un fichier.** On veut un mode « GitOps »
  où serveurs/cibles/clés sont déclarés dans un YAML versionné et réconciliés au démarrage, comme
  les migrations alignent le schéma. Livré **en 3 sous-phases testées l'une après l'autre** (E2E
  vert à chaque étape) : (1) réconciliation, (2) livraison du secret (webhook/e-mail), (3) export.
- **Le drapeau headless vit dans l'ENVIRONNEMENT, pas dans le YAML.** Mettre `webui: false` *dans*
  le fichier serait circulaire : il faudrait lire le fichier pour savoir s'il faut le lire. On
  bascule donc sur la **présence de `GATEWAY_CONFIG`** (variable d'env). Sa présence = mode
  déclaratif ; absente = mode UI classique, YAML ignoré. Résout aussi le « qui gagne ? » (pas de
  dérive UI ↔ fichier).
- **Aucun secret en clair dans le YAML.** Les valeurs sensibles s'écrivent `${NOM}` et sont
  **interpolées depuis l'environnement** au chargement (fail-closed si la variable manque). Le
  fichier reste ainsi commitable ; les secrets restent en `.env`. La règle dure « zéro secret dans
  le dépôt » est préservée.
- **Identité stable via `external_ref`.** Une clé YAML est reconnue par son `name` (colonne
  `external_ref`, index unique partiel) : la réconciliation met à jour la config sans régénérer le
  secret. Les clés créées par l'UI (`external_ref` NULL) sont **hors périmètre** — jamais touchées.
- **Élagage conservateur.** Retirer une clé du fichier la **désactive** (révocation réversible) ;
  suppression seulement si `prune: true`. Un `DELETE` déclaratif silencieux serait un piège.
- **Le reconciler possède le défaut en mode déclaratif.** `servers/targets.ensure_default`
  n'auto-créent plus « Ollama local »/« Passerelle publique » quand `DECLARATIVE` est vrai : sinon
  un défaut parasite entrerait en concurrence avec les serveurs du YAML. Le reconciler pose le
  défaut depuis le fichier (`default: true`, sinon le premier).
- **Livraison différée, mais phase 1 déjà utile.** Sans canal de livraison, une clé *générée* a un
  secret irrécupérable (le CLI le signale). Pour rendre la phase 1 exploitable dès maintenant, on
  supporte l'**import** d'une clé au secret **connu** via `value: ${NOM}` (retrouvable côté client).

## 2026-07-20 — Gestion des modèles par serveur + usage par modèle

- **Deux besoins symétriques : tracer ce qui tourne, et piloter le catalogue — sans jamais ouvrir
  la gestion aux clients.** On veut (1) voir le **dernier usage de chaque modèle par serveur** et
  (2) **télécharger/supprimer** un modèle sur un serveur donné, tout en garantissant qu'un **client
  ne puisse envoyer aucune commande de gestion** à l'amont.
- **Séparation nette des chemins privilégiés.** La gestion (`pull`/`delete`) est une **opération
  d'administration** : elle part de la **console LAN-only** (`app/admin.py` → `servers.pull_model`/
  `delete_model`) et frappe l'amont **en direct** avec le jeton distant déchiffré côté serveur —
  **jamais** via le proxy public. Le **proxy** reste un pur relais d'**inférence** : `apis.
  is_management_path` (déjà en place) refuse **403** `pull`/`push`/`delete`/`create`/`copy`/`blobs`
  pour toute clé, **avant** d'atteindre l'amont. Ce garde-fou existait mais n'était pas testé : on
  ajoute des tests unitaires (`is_management_path` + blocage proxy avec faux Ollama qui *implémente*
  pull/delete → un 403 prouve la garde, pas un 404) et E2E.
- **Pull bloquant (`stream:false`), assumé.** Le panel suit le motif POST→redirect→flash du reste
  de la console ; un gros téléchargement peut tenir la requête ouverte plusieurs minutes (timeout
  amont long). Choix pragmatique cohérent avec « Tester »/« Compat » ; pas de suivi de job asynchrone
  (surdimensionné pour un outil LAN mono-opérateur).
- **Traçage par modèle = attribution réelle.** `usage.server_per_model` réutilise `usage_events.
  server_id` (rempli par le proxy, **repli inclus**) et exclut `model=''` (refus d'auth/quota avant
  lecture du corps). Tri par `last_seen` DESC → « qu'est-ce qui a servi en dernier » se lit d'un
  coup d'œil.
- **Testabilité déterministe.** Le faux Ollama gagne un **catalogue mutable** (`/api/pull` ajoute,
  `/api/delete` retire, réinitialisé entre tests) → le cycle pull→voir→delete est prouvable en E2E
  sans vrai Ollama ni GPU.

## 2026-07-17 — Visionneuse du contenu des requêtes (grep dans le panel)

- **Le contenu était consultable seulement au shell → on l'ouvre dans le panel.** Le journal de
  contenu (fichiers hors base) n'avait pas d'accès UI (seules les métadonnées `usage_events` le
  sont, dans la console de logs). Nouvelle page `/admin/logs/content` : sélection clé/heure +
  **filtre grep** (sous-chaîne insensible à la casse, appliqué **côté serveur** pour lire aussi
  les fichiers **gzip** et éviter d'envoyer tout le fichier au navigateur), rendu déplié par
  requête, et téléchargement brut (`/content/raw`).
- **Grep serveur, pas client.** Les fichiers peuvent être gros et compactés en gzip ; filtrer au
  serveur (streaming ligne à ligne, cap d'affichage à 2000 lignes signalé) évite de charger tout
  le fichier en mémoire navigateur et fonctionne identiquement sur `.jsonl` et `.jsonl.gz`.
- **Sécurité : noms validés + confinement.** `reqlog.resolve` n'accepte que `key-<id>`/
  `unauthenticated` et un nom de fichier horaire strict, et vérifie que le chemin résolu reste
  **sous** la racine (défense anti-traversal, testée). Le contenu est déjà sanitisé à l'écriture
  (secrets masqués) → aucune re-fuite à la lecture.
- **Piège de config : l'ADMIN doit voir le dossier.** Le viewer tourne dans l'app **admin**, qui
  lit `REQUEST_LOG_DIR` ; or seul le **proxy** l'avait en E2E → l'admin affichait « désactivé ».
  Corrigé : `REQUEST_LOG_DIR` câblé aussi côté admin (E2E + rappel composes, où le volume `/data`
  est partagé entre les deux rôles). Détecté **en vision** (capture montrant le message désactivé).
- **i18n pragmatique.** Le test de complétude impose les mêmes clés dans les 24 locales. J'ai
  fourni fr (source) et en réels ; les 22 autres reprennent la **source fr** (politique de repli
  déjà en place) faute de pouvoir produire 24 traductions fiables à la main — clés présentes,
  placeholders et jetons `mono` préservés, tests verts. À traduire ultérieurement.

## 2026-07-16 — Internationalisation du panel (24 langues UE)

- **Un YAML par langue, français source.** Les catalogues vivent dans `app/locales/<code>.yaml`
  (clés imbriquées → aplaties en clés pointées au chargement). Le **français est la source** : toute
  clé absente d'une traduction retombe sur le fr, puis sur la clé brute — l'UI ne casse jamais, même
  traduction partielle. Format YAML (et non JSON/gettext) pour rester **lisible et éditable à la
  main** par un non-développeur, cohérent avec le reste du repo ; seule dépendance ajoutée : PyYAML.
- **Négociation session → cookie → `Accept-Language` → fr.** Le choix explicite (sélecteur, écrit en
  `session['lang']`) prime ; sinon on respecte la langue du navigateur. Conséquence testée : un
  navigateur `en-US` rend le panel en anglais **par défaut** — c'est voulu. Les tests E2E fixent donc
  `locale: 'fr-FR'` (les captures du manuel et les assertions restent en français, langue de réf.).
- **Libellés JS = piège classique.** Les chaînes construites côté client (options de sonde, « Échec »,
  WHOIS…) ne passent pas par Jinja au moment de l'exécution. On les expose une fois dans un bloc
  `<script type="application/json">` (échappé via `tojson`) ou en `data-*`, puis le JS lit ces valeurs.
  Évite tout texte en dur résiduel et garde une seule source de vérité (le YAML).
- **Pièges Jinja rencontrés.** (1) `{% for t in … %}` **masque** la fonction `t()` de traduction →
  variable de boucle renommée (`tg`). (2) Les macros importées sont **isolées du contexte** : import
  avec `with context` pour que `t()`/`languages` y soient visibles.
- **Complétude garantie par test, pas par discipline.** `test_i18n` vérifie que les 24 locales ont
  **exactement** le jeu de clés du fr, et que chaque valeur conserve les mêmes `{placeholders}` et les
  identifiants `<span class=mono>` (noms d'env, chemins, URLs) — une traduction qui casserait une
  variable ou traduirait `OLLAMA_HOST` échoue le CI.
- **Correctif annexe (course de sonde).** En basculant rapidement de serveur, la réponse d'une sonde
  antérieure pouvait re-rendre des cases après qu'une sonde plus récente ait vidé la liste. Garde
  ajoutée dans `refresh()` (`_model_picker`) : on capture le serveur ciblé et on **abandonne** toute
  réponse périmée (sélection changée pendant l'`await`). Rend l'E2E « serveur hors ligne » déterministe.
- **Placement du sélecteur : pied de page, pas la barre (retour responsable).** La 1ʳᵉ version
  glissait le sélecteur dans la topbar via un wrapper `.topbar-right` englobant nav + sélecteur — ce
  qui **reflowait la navigation**. Corrigé : la topbar revient à `marque | nav` (aucun ajout), et le
  sélecteur descend **en bas à droite du pied de page**, discret. Repli = **drapeau seul** (SVG,
  jamais emoji — charte + rendu Windows), dépli = **drapeau + nom natif**. Implémenté en disclosure
  natif `<details>` (ouverture vers le haut, aucun JS) : chaque option est un `<button submit>` de la
  form POST `/admin/lang`. L'E2E pilote donc un vrai menu (ouvrir le disclosure puis cliquer l'option),
  plus un `<select>`.
- **Choix i18n vs conventions du repo.** L'admin reste en Jinja rendu serveur (écart React assumé,
  cf. DESIGN_SYSTEM §6) : l'i18n est donc côté serveur (pas de lib front). Les traductions ont été
  **rédigées à la main** (pas de sous-agent/délégation, conformément aux conventions), une locale par
  fichier, validées par un builder de complétude stricte.

## 2026-07-09 — Contenu des requêtes sur fichiers + origines/WHOIS

- **Contenu complet hors base, par choix explicite.** Le corps des requêtes peut être volumineux
  et sensible ; on ne le met **pas** dans SQLite (la base garde les métadonnées `usage_events`).
  `reqlog.record` écrit un JSONL par heure sous `key-<id>/` : un dossier par clé, rotation
  horaire naturelle. Les en-têtes secrets (`Authorization`, `x-api-key`, `cookie`) sont
  **masqués** avant écriture — garde-fou « zéro clé en clair au repos ». Best-effort : toute
  erreur d'E/S est avalée pour ne jamais faire échouer une requête proxy.
- **Rétention par clé + cron.** `api_keys.log_retention_days` (migration 0004, NULL → défaut
  global). `reqlog.compact_and_purge` gzip les heures **passées** (l'heure courante reste
  ouverte) et purge au-delà de la rétention ; exposé en CLI `python -m app.reqlog compact` pour
  un cron. Testé de façon déterministe en injectant `ts`/`now` (pas d'horloge réelle).
- **WHOIS = RDAP over HTTPS, pas de binaire.** `whois.lookup` interroge `rdap.org/ip/<ip>`
  (RDAP, remplaçant du whois:43) → JSON structuré, aucune dépendance système. Les adresses
  **privées/loopback/réservées** court-circuitent sans réseau → déterministe et testable (l'E2E
  fait un WHOIS sur 127.0.0.1). Le parsing RDAP public est couvert par un client mocké.
- **Piège XFF dev/prod (rappel).** En dev via docker-compose, les origines vues affichent
  l'IP du bridge (172.18.0.1) car le XFF de l'hôte n'est pas de confiance ; en prod
  (`network_mode: host`) c'est l'IP client réelle. L'E2E valide le vrai chemin (uvicorn direct,
  pair 127.0.0.1 de confiance).

## 2026-07-08 (suite 2) — Console de logs, bannissement d'origines, try-me multi-API

- **Bannissement = DENY global avant l'auth (choix d'architecture).** Le bannissement d'origine
  est une nouvelle table `banned_origins` vérifiée **tout en haut du proxy**, avant même le
  contrôle de clé : couper un scanner/abus repéré dans les logs doit fonctionner quelle que soit
  la clé présentée. C'est distinct des `key_origins` (un ALLOW *par clé*) : ici un DENY *global*.
  IP normalisée en hôte (`/32`·`/128`) ou CIDR ; la vérification teste l'appartenance réseau.
- **Console de logs = exposition du journal déjà conservé.** `usage_events` est append-only et
  complet depuis l'origine ; il n'était affiché que par clé (erreurs récentes). La page `/admin/logs`
  expose **tout** le journal (dernières 500 lignes affichées, total indiqué — rien n'est purgé) et
  ajoute le bouton « Bannir » par ligne. Les lignes déjà couvertes par un ban sont marquées
  (`bans.banned_among`, une seule requête pour tout l'écran plutôt qu'une par ligne).
- **Try-me multi-API.** Le relais `chat_once` devient `try_call(server_id, api, model, message)`
  piloté par `TRY_APIS` : chaque API a son chemin, sa fabrique de corps et son extracteur de
  réponse (Ollama `message.content`, OpenAI chat `choices[].message.content`, OpenAI responses
  `output_text`/`output[].content[].text`, Anthropic `content[].text`). Le faux Ollama gagne
  `/v1/responses` et `/v1/messages` pour un E2E déterministe des quatre. Le serveur amont doit
  servir le chemin choisi ; sinon le relais renvoie l'erreur (utile pour tester la config).
- **Piège dev/prod sur l'IP journalisée (documenté, pas un bug).** En dev via docker-compose, le
  proxy voit comme pair la passerelle du bridge Docker (172.18.0.1), pas 127.0.0.1 : le XFF de
  l'hôte n'est donc pas « de confiance » et c'est l'IP du bridge qui est journalisée/bannie. En
  **prod** (`network_mode: host`, Caddy en loopback), le pair est 127.0.0.1 (de confiance) et le
  XFF de Caddy est honoré → l'**IP client réelle** est journalisée et bannissable. L'E2E valide le
  chemin XFF-de-confiance en lançant uvicorn en direct (pair = 127.0.0.1).

## 2026-07-08 (suite) — Modales plein écran + bug de fermeture corrigé

- **Bug : la modale de chat ne se fermait pas.** Root cause trouvée en instrumentant les
  événements du `<dialog>` : à la fermeture (bouton X, Échap, `close()`), l'événement `close`
  se déclenchait bien (`open=false`) mais la modale **restait affichée**. Cause : la règle CSS
  `dialog.chatmod { display:flex }` (posée sur le sélecteur nu) **écrasait** la règle du
  navigateur `dialog:not([open]) { display:none }` → une fois fermée, la modale n'était plus
  modale (ni backdrop, ni capture d'événements) mais restait peinte à l'écran, donnant
  l'impression d'une fenêtre bloquée sans bouton. Les modales manuel/env n'avaient pas de
  `display` forcé, d'où leur bon fonctionnement.
- **Correctif.** Le `display` n'est plus posé que sur `dialog…[open]` : la règle UA reprend la
  main à la fermeture. Règle générale retenue : **ne jamais forcer `display` sur un
  `<dialog>` nu** — toujours scoper à `[open]`.
- **Modales plein écran (règle dure du responsable).** Les trois modales (manuel, configuration
  client, chat) passent en **plein viewport** (100vw × 100dvh, sans marge ni coin arrondi),
  avec une **barre de titre** portant un bouton **Fermer** (X + libellé) bien visible et une
  colonne de contenu lisible centrée. Fermeture par le bouton ou Échap.
- **Trou de test comblé.** L'E2E « essayer maintenant » vérifie désormais la **fermeture
  réelle** (clic Fermer puis Échap → modale masquée) : le test précédent ne faisait que
  screenshoter la modale ouverte, ce qui avait laissé passer le bug.

## 2026-07-08 — « Essayer maintenant » : chat de test d'une clé

- **Relais admin plutôt que navigateur → proxy.** Le bouton « Essayer maintenant » aurait pu
  faire un `fetch` direct du navigateur vers le proxy public avec la clé en Bearer. Écarté :
  (1) le secret n'est affiché **qu'une fois** à la création → indisponible sur la page d'une
  clé existante ; (2) cela aurait exigé d'ouvrir **CORS** sur la seule surface publique
  (garde-fou fort du repo). Choix : un endpoint **admin LAN-only** `POST
  /admin/keys/{id}/try-chat` qui relaie vers le serveur rattaché (jeton distant déchiffré,
  jamais côté navigateur), en **respectant l'allowlist** de la clé (fidèle au proxy : modèle
  hors liste → 403). Rien n'est ajouté à la surface publique.
- **Modèle choisi automatiquement.** Sans modèle explicite : premier de l'allowlist, sinon
  première entrée d'une sonde live du serveur. La réponse renvoie le modèle utilisé (affiché
  au-dessus de la bulle). Appel **non-streamé** (`servers.chat_once`, `stream:false`) : une
  fenêtre de chat n'a pas besoin du streaming, et la réponse unique simplifie l'affichage et
  le test déterministe (le faux Ollama sert déjà `/api/chat` non-streamé).
- **Testabilité.** Le relais passe par `httpx` de `servers`, donc la fixture `probe_via_fake`
  (ASGITransport vers le faux Ollama) couvre aussi `chat_once` en unitaire ; l'E2E exerce la
  fenêtre réelle sur la clé de démo (serveur par défaut → faux Ollama).

## 2026-07-07 (suite 4) — Plein viewport, modale de configuration client, x-api-key

- **Règle dure édictée par le responsable : tout le viewport, toujours.** Le conteneur central
  `max-width:1040px` est supprimé — `main` fait 100 % de la largeur, `body` 100 vh en colonne
  flex. Sur grand écran (≥ 1360 px) le contenu se répartit en deux colonnes (`grid-split` :
  table des clés | formulaire ; édition | usage) et la page Serveurs passe en grille de cartes.
  Le login devient un split hero/formulaire pleine hauteur. Règle mémorisée durablement (elle
  vaut pour tous les projets).
- **Modale « configurer le client ».** À la création d'une clé (seul moment où le secret est
  connu), une modale génère les variables d'env par API cochée. Choix des noms **standard des
  SDK** : `OLLAMA_HOST`/`OLLAMA_API_KEY`, `OPENAI_BASE_URL`/`OPENAI_API_KEY` (base suffixée
  `/v1`), `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`. La base publique vient de
  `PUBLIC_BASE_URL` (nouvelle var, l'admin ne peut pas la deviner : le vhost public est
  terminé par Caddy). Copie via `navigator.clipboard` avec **repli `execCommand`** : l'admin
  LAN est servi en http (contexte non sécurisé, l'API clipboard y est absente).
- **`x-api-key` accepté par le proxy.** Le SDK Anthropic configuré par `ANTHROPIC_API_KEY`
  envoie `x-api-key`, pas un Bearer : sans ce support, les variables générées n'auraient pas
  fonctionné pour Anthropic. L'en-tête est strippé avant l'amont, comme Authorization.
- **Flakiness E2E instructif.** Les checkboxes héritaient du `padding` générique des `input`
  → une case focusée passait de 13 à 31 px et la ligne bougeait pendant le clic (échec
  `check()` de Playwright, reproductible). Correctif CSS : taille fixe `16px`, `padding:0`
  sur `.checks input` — supprime aussi le « saut » visuel pour l'utilisateur.

## 2026-07-07 (suite 3) — Correction : cases de modèles sondées en direct

- **Écart de spec signalé par le responsable.** La 1ʳᵉ version du sélecteur de modèles ne
  peuplait les cases à cocher qu'après un clic manuel sur « Tester » côté page Serveurs (elle
  lisait le dernier résultat persisté) : au premier rendu, l'admin ne voyait qu'une textarea.
  La spec demandait des **cases listant les modèles disponibles** du serveur rattaché.
- **Correctif : sonde LIVE depuis le formulaire.** Nouveau partial `_model_picker.html`
  (macro Jinja partagée création/édition) : au rendu et à chaque changement de serveur, appel
  `GET /admin/servers/{id}/models` (nouvel endpoint qui sonde et persiste), cases cochées selon
  l'allowlist courante, **repli en saisie libre** si le serveur est injoignable — et sans JS la
  textarea porte l'allowlist complète, donc le formulaire reste toujours valide. Côté POST,
  `_collect_models` fusionne cases (`model_check`) + saisie libre, dédupliquées.
- **Leçon (DoD).** L'unité UI avait été close sur la foi du code + une capture, sans vérifier
  le comportement « cases visibles au rattachement » de bout en bout. Rouvert, testé (unitaires
  + E2E dédiés, dont le repli hors ligne), vérifié en vision, reclos.

## 2026-07-07 (suite 2) — Serveurs d'exécution & restriction de modèles

- **De 1 upstream à N serveurs.** Le proxy avait un client httpx unique lié à `$OLLAMA_UPSTREAM` ;
  il utilise désormais un client **sans base_url** et cible l'URL absolue du **serveur rattaché à
  la clé**. Ça rend les tests inchangés (l'ASGITransport injecté ignore l'hôte) tout en permettant
  le routage réel multi-serveurs en prod.
- **Un seul serveur par clé (choix de simplicité demandé).** `api_keys.server_id` (FK), reconciler
  `ensure_default` qui crée le serveur local et réassigne les clés orphelines — rétro-compatible
  avec la prod déjà déployée (la clé historique se rattache au local au boot).
- **Restriction agnostique de l'API (exigence).** Ollama natif, OpenAI Chat/Responses et Anthropic
  Messages mettent tous `model` à la **racine** du corps JSON → un seul point de contrôle suffit,
  quel que soit le chemin. En complément, filtrage des listings `/api/tags` (forme `models/name`)
  et `/v1/models` (forme `data/id`) pour ne montrer que les modèles permis.
- **Secret distant chiffré, pas haché.** Le jeton Bearer d'un serveur distant doit être **réémis**
  vers l'amont → Fernet réversible (`crypto.py`, clé dérivée de `$P2E_MASTER_KEY`), contrairement
  aux clés API/mot de passe admin hachés one-way. Jamais réaffiché ; le champ vide du formulaire
  conserve le jeton existant (`clear_auth` pour l'effacer).
- **Bug de concurrence révélé au démarrage.** Les rôles proxy/admin migrent en parallèle sur le
  même SQLite : (1) `PRAGMA journal_mode=WAL` prenait un verrou d'écriture **avant** `busy_timeout`
  → « database is locked » ; (2) deux runners appliquaient `0002` en même temps → « duplicate
  column ». Corrigé : `busy_timeout` d'abord, et **verrou `flock`** autour de l'application des
  migrations (partagé via le volume). Latent avant cette feature (peu d'écritures au boot).
- **E2E** : le serveur par défaut est seedé depuis `$OLLAMA_UPSTREAM` ; il fallait le pointer sur
  le faux Ollama (11533) dans `global-setup.ts`, sinon il visait `127.0.0.1:11434` (un vrai Ollama
  de la machine dev renvoyait 404).

## 2026-07-07 (suite) — Manuel utilisateur intégré

- **Manuel en modale dans le panel** : `docs/manual.md` (source unique, publiable) est rendu
  côté serveur (`GET /admin/manual`, lib `markdown` — pas de lib JS de rendu côté client,
  cohérent avec le « zéro build front »). Les blocs Mermaid sont retirés au rendu in-app
  (pas de moteur Mermaid embarqué) : les **captures d'écran réelles** illustrent chaque
  fonctionnalité à la place. Chemins d'images doubles : `../app/static/manual/…` pour GitHub,
  remappés vers `/static/manual/…` par la route.
- **Captures = sous-produit des E2E** : les mêmes screenshots Playwright servent de preuve
  vision ET d'illustrations du manuel (`npm run sync-manual` copie `e2e/output/*.jpg` vers
  `app/static/manual/`). Règle dure ajoutée à `CLAUDE.md` : manuel + captures synchrones à
  tout changement.
- **`.dockerignore`** : ré-inclusion ciblée `!docs/manual.md` — le manuel entre dans l'image,
  le DAT (détails d'infra) reste dehors.
- `runDev` affiche désormais le mot de passe admin dev en clair dans son récapitulatif.

## 2026-07-07 — Mise en conformité charte P2Enjoy + règles de repo

- **UI admin restylée intégralement** selon `docs/DESIGN_SYSTEM.md` (charte P2Enjoy SAS) :
  thème clair, cartes blanches `rounded-xl` avec liseré de catégorie (bleu = clés,
  vert = usage/création, jaune = tokens — un seul par vue, rouge = erreurs/danger), nav en
  pilules, icônes lucide SVG inline (macro `app/templates/_icons.html`), héros dégradé
  navy→vert réservé aux écrans login/setup. L'ancien thème sombre générique est supprimé.
- **Écart assumé : l'admin reste en Jinja rendu serveur** (pas de React + Vite) — micro-panel
  LAN-only sans build front, justification consignée dans `DESIGN_SYSTEM.md` § 6. À
  reconsidérer si le panel grossit.
- **E2E : base dédiée supprimée puis re-seedée à chaque run** (`e2e/global-setup.ts`). Les
  runs successifs accumulaient des clés `e2e-client` → violations *strict mode* Playwright.
  Aligne l'E2E sur la règle « dev fully self-seeded ».
- **Sélecteurs E2E** : `.pill.on/.off` → `.badge.on/.off` (nouveau markup des badges d'état).
- **Docs de conformité** : création de `docs/manual.md` (manuel public, Mermaid) et de ce
  journal ; section « Spécifique à ce repo » de `CLAUDE.md` réécrite (elle décrivait un autre
  projet) ; purge des hôtes/domaines réels de `CHANGELOG.md` et `README.md` (surface
  publique = zéro hôte ; les détails d'infra restent dans `docs/DAT.md`).
- **Hook de session** : `.claude/hooks/session-start.sh` (démarrage du daemon Docker).

## 2026-07-06 — Première version + bascule en production

- Passerelle complète (proxy auth/origine/quota/usage + admin LAN + Caddy TLS DNS-01
  Scaleway) construite, testée (31 pytest + 3 E2E) et déployée en production.
- Choix structurants : SQLite WAL partagé entre rôles, clés hachées sha-256 avec secret
  affiché une seule fois, streaming relayé intégralement avec comptage de tokens sur le
  chunk final, rôle (proxy/admin) sélectionné par `GATEWAY_ROLE` dans une image unique.
- Contraintes découvertes : le plugin Caddy DNS Scaleway v0.2.2 exige Caddy 2.11 +
  `GOTOOLCHAIN=auto` ; la config DNS-01 requiert `secret_key` + `organization_id` +
  `dns_ttl`. Voir `docs/DAT.md`.
