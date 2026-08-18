# Journal — ollama-gateway

Journal chronologique des décisions (le plus récent en premier). Complète `CHANGELOG.md`
(quoi) par le **pourquoi**.

## 2026-08-18 — Gabarit VS Code : ne rien deviner, tout demander à l'amont

- **Le point de départ était une demande simple, le fond était plus grave.** La demande portait sur
  deux points : mettre le vrai secret dans le gabarit VS Code au lieu du renvoi vers une invite de
  saisie de l'éditeur, et aller chercher les caractéristiques réelles des modèles (outils, vision,
  entrée/sortie max) auprès du serveur. En ouvrant le gabarit, un troisième défaut est apparu : la
  page **ne transmettait jamais** au gabarit les modèles de la clé (`key_models` référencé côté
  gabarit, jamais fourni côté page) — le bloc sortait donc **toujours sans aucun modèle**. La
  fonctionnalité était annoncée au changelog comme « valorisée avec les vraies données de la clé » ;
  elle ne l'était pas. Vérifié dans l'historique : la variable n'a jamais été passée depuis sa
  livraison. C'est la conséquence directe d'une livraison **sans aucun test**.
- **Pourquoi interroger `/api/show` plutôt que déduire du nom du modèle.** Le nom ne dit rien de
  fiable : deux `qwen3` peuvent différer sur la vision, et la fenêtre de contexte varie selon la
  quantification et le GGUF. `POST /api/show` publie `capabilities` et `model_info` — c'est la seule
  source qui décrit **le modèle réellement installé sur ce serveur-là**. On lit la fenêtre sous
  `<arch>.context_length` (le préfixe suit l'architecture du GGUF) sans coder la liste des
  architectures en dur : elle se périmerait à chaque nouvelle famille.
- **Repli assumé pour les amonts anciens, jamais d'invention.** `capabilities` n'existe que depuis
  Ollama 0.6. Sur un amont plus ancien on relit les mêmes indices qu'Ollama utilise lui-même
  (`.Tools` dans le gabarit, projecteur multimodal dans les familles). Si `/api/show` ne répond
  pas du tout, le modèle ressort **prudent** (ni outils ni vision) et la modale **le dit** : un
  éditeur bridé se corrige en deux clics, un éditeur qui promet une capacité absente échoue à
  l'usage sans que l'utilisateur comprenne pourquoi.
- **Simplification demandée : une seule règle, pas quatre.** La première version empilait quatre
  notions (réserve d'un quart, planchers 1k/32k, précédence du déclaré sur l'entrée ET la sortie,
  marge du tokenizer) — illisible pour qui n'a pas le code sous les yeux. Ramené à : *on annonce la
  fenêtre du modèle, sans jamais dépasser ce que la clé autorise*. La sortie reste celle que
  l'amont déclare, sinon 16k. La seule subtilité conservée est la marge du garde-fou 413, parce
  qu'elle évite un refus sur un prompt qu'on venait d'autoriser — elle ne se voit pas dans la règle,
  seulement dans le dernier millier de tokens.
- **Une sonde, trois familles d'amont.** Le gateway peut viser Ollama, ollama.cpp ou un serveur
  seulement OpenAI-compatible. Plutôt que de typer les serveurs (champ à saisir, à maintenir, à se
  tromper), on essaie la fiche native puis on retombe sur la liste des modèles : le type se déduit
  de ce qui répond. Les noms de champs varient beaucoup d'une implémentation à l'autre
  (`num_ctx`, `<arch>.context_length`, `max_model_len`, `meta.n_ctx_train`…) — d'où un
  aplatissement du JSON et une liste ouverte de noms, plutôt qu'un parseur par implémentation.
  **Vérifié sur pièces** : l'implémentation d'ollama.cpp (branche `claude/ollama-cpp-middleware-po79fi`,
  la branche `main` n'ayant que des docs) joint `capabilities` à chaque entrée de `/api/tags`,
  expose le KV du GGUF en `model_info` et les paramètres au format Modelfile — nos trois lectures
  y tombent juste. D'où un ajout : l'entrée de catalogue devient une **source à part entière**,
  entre la fiche détaillée et la liste OpenAI. Elle sauve le cas du modèle fraîchement tiré, que
  la fiche ne décrit pas encore.
- **Ce que ollama.cpp ne dit PAS, et qu'on n'ira pas chercher.** Sa raison d'être est la fenêtre
  configurée **par modèle** (`runtime.context`), mais `/api/show` ne la publie pas : seule la
  fenêtre native du GGUF y figure. La valeur effective n'existe que dans `/api/ps`, et seulement
  pour les modèles **résidents** — la lire donnerait un affichage qui change selon qu'un modèle
  est chargé ou non. Une valeur stable et honnête vaut mieux qu'une valeur exacte par intermittence.
  Le plafond de la clé, lui, s'applique dans tous les cas.
- **Le registre privé n'est pas un cas particulier.** Il sert à *tirer* un modèle ; une fois
  installé, celui-ci figure dans `/api/tags` comme les autres. Rien de spécifique à coder côté
  passerelle : lire le catalogue suffit à le couvrir.
- **Sonder aussi au choix du serveur, dans le formulaire de clé.** Choisir les modèles autorisés
  par leur seul nom revient à choisir à l'aveugle. Le sélecteur affiche désormais ce que le serveur
  dit de chaque modèle ; c'est la même sonde, donc aucune source de vérité supplémentaire.
- **Les bornes annoncées sont calculées pour PASSER, pas pour flatter.** VS Code veut une
  entrée max et une sortie max ; Ollama ne publie qu'une fenêtre totale, et la passerelle impose en
  plus le plafond de contexte de la clé. Trois contraintes, donc, composées dans `context.io_budget`
  — dont la moins évidente : le garde-fou d'entrée compare une estimation **majorée de 15 %** au
  plafond (tiktoken n'est pas le tokenizer des modèles servis). Annoncer le plafond brut en entrée
  aurait produit des refus 413 sur des prompts que la passerelle disait accepter. L'entrée annoncée
  est donc redescendue à `plafond / marge`.
- **Ce que l'amont déclare prime sur ce qu'on déduirait.** `num_ctx` du Modelfile prime sur
  `<arch>.context_length` : la voie visée par le gabarit est OpenAI-compatible, la passerelle n'y
  injecte **pas** `num_ctx`, c'est donc la valeur du Modelfile qui s'applique réellement, pas le
  maximum de l'architecture. Les sentinelles `num_predict: -1`/`-2` ne sont pas des bornes.
- **Le gabarit ne remplace plus les variables d'environnement, il s'y ajoute.** Cocher « VS Code »
  écrasait la zone de sortie commune : on ne pouvait pas voir — ni copier — les deux à la fois,
  alors qu'ils servent deux usages simultanés (un shell côté machine cliente, les réglages de
  l'éditeur). Bloc séparé, zone copiable propre, bouton propre ; la logique de copie (avec son
  repli `execCommand` pour l'admin servi en http) est factorisée plutôt que dupliquée.
  `apiType` aligné sur `chat-completions` d'après le gabarit de référence fourni par le
  responsable : c'est la voie OpenAI-compat que l'éditeur emprunte réellement.
- **Le secret ne devient pas interrogeable pour autant.** L'adresse ajoutée
  (`GET /admin/keys/{id}/vscode-models`) ne renvoie que des métadonnées de modèles ; le secret reste
  strictement dans l'affichage unique de la modale. Un endpoint qui reservirait un secret annulerait
  la garantie « affiché une seule fois ».

## 2026-08-17 — Déploiement prod : le balayage se fait sur DEV, et la DNS de BuildKit est cassée

- **Où tourne le balayage (rappel qui a coûté du temps).** Le balayage de sécurité est un gate
  **pré-déploiement** : il tourne sur la machine de **développement**, et on ne déploie que s'il est
  vert. L'hôte de production n'a donc **pas** de `.venv` ni d'outillage de sécurité — c'est normal,
  pas une anomalie à « réparer ». Lancer `./runProd` *sur la prod* ré-exécute le gate là où il n'a
  pas sa place et le fait échouer faute d'outils. Sur la prod, l'étape de déploiement est la
  reconstruction/recréation des services, pas le balayage. (Ne pas confondre `.venv` — virtualenv
  Python de l'outillage — avec `.env.prod`, le fichier de variables d'environnement : le second est
  bien présent en prod, l'application n'a jamais eu besoin du premier puisqu'elle tourne en Docker.)
- **Découvertes réelles remontées par le gate (et corrigées avant de déployer).** (1) CVE sur
  `cryptography` (avis PYSEC-2026-3552) → montée de version, aller-retour Fernet revérifié ;
  (2) `test_i18n` au rouge : la fonctionnalité « endpoint VS Code » avait ajouté son libellé au seul
  `fr.yaml`, laissant 23 locales incomplètes. Les deux étaient **antérieurs** à la session et
  auraient été déployés en silence si le gate avait été contourné — c'est exactement son intérêt.
- **La DNS de BuildKit est inutilisable sur cet hôte (piège à documenter).** Toute reconstruction
  d'image échouait sur « name resolution » (pip) / « network is unreachable » (xcaddy) alors que
  l'hôte, lui, résout parfaitement. Diagnostic : les conteneurs d'**exécution** résolvent (y compris
  en réseau hôte), seuls les conteneurs de **build** échouent — le bac à sable de BuildKit reçoit un
  résolveur IPv6 qu'il ne peut pas joindre. **Contournement retenu** : construire l'image applicative
  avec `docker build --network=host -t ollama-gateway:prod .`, puis laisser `docker compose up -d`
  consommer l'image (sans `--build`). Rien n'est modifié durablement : ni `daemon.json`, ni le dépôt,
  le réseau hôte n'est utilisé qu'au moment du build.
- **L'edge TLS n'a pas été reconstruit, volontairement.** Ses sources n'ont pas changé depuis la
  construction de son image ; le rebuild global échouait pourtant sur *lui* (xcaddy sans réseau).
  Ne reconstruire que `proxy` + `admin` évite un échec sans rapport avec le changement livré — et
  évite d'interrompre l'edge.
- **Coupure assumée de quelques secondes.** La recréation de `proxy` a produit des `502` à l'edge le
  temps du redémarrage (un client réel a tapé pendant la fenêtre). Vérifié ensuite : plus aucune
  erreur, sondes de bout en bout à `200`. Un déploiement sans coupure demanderait un basculement
  progressif, non mis en place à ce stade.

## 2026-07-28 — Fiabilisation d'un test E2E intermittent (reconcile, base partagée)

- **Ce qui a été observé.** Un échec unique de `reconcile.spec` (« clé importée … visible au
  dashboard ») sur une exécution complète, à **7,5 s** au lieu de ~2 s. Rejoué seul et en suite
  complète : vert. Signature temporelle = ~2 s de test + **5 s** (délai d'attente par défaut d'un
  `toBeVisible`) ⇒ c'est l'assertion sur la ligne du tableau qui a expiré.
- **Honnêteté sur le diagnostic.** Le message d'erreur exact n'a **pas** pu être lu : `npm test`
  commence par `rm -rf output`, ce qui a effacé la trace et la capture de l'échec avant inspection.
  La cause n'est donc **pas prouvée** ; trois exécutions complètes supplémentaires (114 tests) n'ont
  pas reproduit l'incident.
- **Hypothèses écartées par la mesure, pas par l'intuition.** (1) *Lenteur du rendu à mesure que les
  clés s'accumulent* : `keys.list_keys()` mesuré à ≤ 8 ms jusqu'à 50 clés → écarté. (2) *Verrouillage
  anti-brute-force du login* : aucune spec n'envoie de mauvais mot de passe → écarté. (3) *Filtres
  clients masquant la ligne* : le filtre ne s'exécute que sur `input` et chaque test a un contexte
  neuf → écarté.
- **Ce qui a été durci, et pourquoi c'est utile même sans diagnostic certain.** (a) **Assertion en
  base avant l'UI** : on vérifie que la clé existe réellement, ce qui **sépare** « la réconciliation
  n'a rien écrit » de « l'UI ne l'affiche pas ». (b) **Connexion prouvée** : on attend explicitement
  la navigation vers `/admin` et, en cas d'échec, on lève une erreur portant l'URL et le message du
  formulaire — au lieu d'un délai d'attente muet sur la page suivante. Un login refusé (401/429) ne
  peut plus se déguiser en « ligne absente ».
- **Pas de rustine.** Aucun délai d'attente rallongé sur l'assertion de la ligne : avec la
  pré-vérification en base et la connexion prouvée, une expiration signifierait désormais un **vrai**
  défaut d'affichage — il doit échouer.
- **Portée volontairement limitée.** Le même motif de connexion sans attente existe dans d'autres
  specs ; la cause n'étant pas confirmée, on ne réécrit pas dix fichiers pour un bénéfice non prouvé.
  Le motif est documenté ici et sera généralisé si une autre spec se met à clignoter.

## 2026-07-28 — Navigation adaptative : la barre mobile était cassée, pas seulement à l'étroit

- **Mesurer avant de dessiner.** Le diagnostic a chiffré le problème : nav = **852 px**, document
  forcé à **875 px** sur un écran de 360 px, `.topbar` à **154 px**. Conclusion importante : ce
  n'était pas un défaut cosmétique mais une **perte de fonction** — 4 des 7 entrées (dont
  Déconnexion) étaient hors écran et **inatteignables** depuis un téléphone. Le reste de l'app était
  bien responsive, ce qui masquait le problème.
- **Repli, pas défilement horizontal.** Une rangée qui défile latéralement « rentre » aussi, mais
  cache les entrées derrière un geste non découvrable et entre en conflit avec le défilement
  vertical. On replie donc derrière un bouton (motif « overflow menu ») : les 7 entrées deviennent
  une pile verticale pleine largeur, chacune avec **icône + libellé** (une nav en icônes seules
  nuirait à la découvrabilité).
- **Point de rupture déduit de la mesure, pas d'un chiffre rond.** 900 px : juste au-dessus des
  852 px nécessaires à la rangée, pour ne jamais la casser au-delà.
- **La déconnexion se détache.** Action de sortie ≠ entrée de navigation : filet de séparation et
  couleur danger, pour éviter le clic accidentel dans une pile où tout se ressemble.
- **Amélioration progressive assumée.** Le bouton n'apparaît que si JS est disponible (`has-js`
  posé dans le `<head>` avant rendu) ; sans JS, la pile reste dépliée. Un repli piloté par JS qui
  cacherait la navigation en cas d'échec du script serait pire que le bug d'origine.
- **Coût collatéral accepté.** La barre est sur toutes les pages ⇒ **toutes les captures du manuel**
  ont été régénérées dans le même lot (règle dure de synchronisation manuel/captures).

## 2026-07-28 — Tailles de contexte réellement utilisées (dimensionnement par la mesure)

- **Le plafond seul ne dit pas quoi choisir.** On savait limiter, pas **à combien**. D'où le
  classement de chaque requête dans le **plus petit palier qui la contient** : la statistique répond
  directement à « parmi les tailles disponibles, lesquelles servent vraiment ? ».
- **L'échelle devient l'ensemble des valeurs autorisées.** Plutôt qu'« un multiple de 4k », une
  **liste de paliers** correspondant aux fenêtres usuelles des modèles. 112k, absent de la liste
  proposée, y a été **conservé** sur décision du responsable : sinon les 6 clés de prod auraient vu
  leur plafond bouger silencieusement (128k au-dessus, 108k en dessous). Un changement de plafond en
  prod ne doit jamais être un effet de bord d'un changement d'échelle.
- **Le palier vient des compteurs RÉELS quand ils existent.** L'amont renvoie `prompt_eval_count` /
  `eval_count` (ou `usage`) : c'est le contexte effectivement mobilisé, bien plus juste que notre
  estimation d'entrée. On ne garde l'estimation que si l'amont est muet (ou si la requête a été
  refusée avant lui).
- **Les refus comptent — et c'est voulu.** Une requête refusée pour dépassement apparaît au palier
  qu'elle **aurait nécessité** : c'est précisément le signal « ce plafond est trop bas ». Les
  événements sans contexte mesurable (refus d'auth/origine, avant lecture du corps) sont eux exclus
  (`ctx_bucket` NULL) pour ne pas polluer la statistique.
- **Même vue à deux échelles.** Par **clé** (dimensionner son plafond) et par **serveur** (voir la
  charge de contexte que la machine encaisse réellement, toutes clés confondues).

## 2026-07-27 — Limite de contexte par clé (garde-fou anti-saturation)

- **Constat terrain d'abord.** L'analyse des 5xx de la prod a montré deux familles : des **502
  après exactement 3600 s** (le délai amont) avec des prompts jusqu'à **148 Ko**, et des **500
  courts** renvoyés par l'amont (échec d'allocation). Cause commune : l'amont charge les modèles
  avec une fenêtre de **256 k** et se fait engorger. La passerelle relayait correctement — mais
  **subissait**. D'où un garde-fou **côté passerelle**, par clé.
- **Deux leviers, pas un.** (1) **Refuser tôt** : compter les tokens et rendre **413 en quelques
  ms** plutôt que de laisser filer une heure de prefill. (2) **Contraindre l'amont** : injecter
  `options.num_ctx` pour qu'il n'alloue pas 256 k quand 112 k suffisent. Le levier (2) est le plus
  efficace sur la mémoire ; le (1) protège des prompts vraiment démesurés.
- **Plafond = maximum, pas consigne.** Si le client demande `num_ctx` **plus petit**, on garde le
  sien : on ne gonfle jamais un contexte que le client voulait court.
- **tiktoken + marge de 15 %, assumée.** `cl100k_base` n'est pas le tokenizer de Qwen/Gemma ; le
  compte réel peut dépasser l'estimation. On majore donc de 15 % avant comparaison. Alternative
  écartée : embarquer le tokenizer exact de chaque modèle (coût et complexité sans rapport avec le
  besoin, qui est un **garde-fou**, pas une facturation).
- **Hermétisme préservé.** tiktoken télécharge son BPE au premier usage : inacceptable pour une
  passerelle self-hosted. Le fichier (1,7 Mo) est donc **mis en cache dans l'image au build** ;
  au runtime, zéro appel sortant. Et si l'encodage manquait, on **replie sur une estimation**
  plutôt que de casser le proxy — un garde-fou ne doit jamais devenir un point de panne.
- **Valeur obligatoire, bornée, alignée.** Pas de « vide = illimité » ici (ce serait rouvrir le
  problème) : la valeur est toujours définie, multiple de 4 k, de 4 k à 1 M, défaut 112 k.
- **Images non comptées.** Un base64 d'image dans le corps aurait fait exploser l'estimation ; les
  champs binaires sont explicitement exclus du comptage de texte.

## 2026-07-27 — Réémission de clé & correctif du bouton « Copier »

- **Réémettre plutôt que recréer.** Diagnostic terrain : une clé « échouait toujours » simplement
  parce que sa valeur côté client était **tronquée** (56 hex au lieu de 64) → hash introuvable →
  401. Le secret n'étant pas récupérable (haché au repos), il faut **faire tourner** la clé. D'où
  `keys.reissue_key` : nouveau secret sur le **même compte** (id/config/historique conservés,
  ancien secret invalidé), présenté via la modale de création réutilisée. Évite de recréer et de
  tout reconfigurer, et préserve l'usage agrégé.
- **Bug « Copier » = contexte non sécurisé + modale inerte.** `navigator.clipboard` n'existe qu'en
  contexte sécurisé (HTTPS ou localhost) ; l'admin est servi en **HTTP sur le LAN** → API absente.
  Le repli `execCommand` existait mais ajoutait sa textarea à `document.body`, **hors** du `<dialog>`
  ouvert en `showModal()` — or tout ce qui est hors du dialog est **inert**, donc `select()`/
  `execCommand` échouaient en silence. Les tests E2E ne le voyaient pas (ils tournent sur
  `127.0.0.1` = contexte sécurisé, chemin `navigator.clipboard`). Correctif : insérer la textarea
  **dans** la modale ; test E2E dédié qui **retire `navigator.clipboard`** pour forcer et valider le
  repli.

## 2026-07-20 — Configuration déclarative, sous-phase 3 : export

- **Fermer la boucle : configurer à la souris, exporter, versionner.** L'export (`GET
  /admin/config.yaml` + CLI) est l'exact inverse d'`apply` : il sérialise serveurs/cibles/clés en
  YAML déclaratif. Cas d'usage : bâtir en UISur un poste, exporter, committer, déployer en headless.
- **L'export ne peut pas contenir de secret — et c'est cohérent.** Le secret d'une clé n'est pas
  stocké (seulement son hash) → export **sans `value`** ; à la ré-import, la clé est **générée** (et
  livrée). Les jetons de serveur (chiffrés) et la config SMTP/livraison (non persistée, pur YAML) ne
  sont pas dans la base → non exportables, réintroduits à la main. On l'écrit noir sur blanc en tête
  du fichier exporté pour lever toute ambiguïté.
- **Identité des clés à l'export.** `name` = `external_ref` s'il existe, sinon un **slug** du label.
  L'export sert de POINT DE DÉPART pour un déploiement neuf ; ré-appliqué sur la MÊME base, seules
  les clés déjà gérées (external_ref) se mettent à jour sans doublon.
- **Coût i18n assumé.** Le bouton « Exporter » ajoute une entrée de navigation → clé `nav.export`
  (+ `export_hint`) propagée aux **24 locales** (règle dure de complétude i18n). Le changement de
  barre de navigation impose de **régénérer les captures du manuel** dans le même lot.

## 2026-07-20 — Configuration déclarative, sous-phase 2 : livraison du secret

- **Le problème central du provisioning headless : le secret n'est montré qu'une fois.** Sans UI
  pour le copier, une clé *générée* serait inutilisable. On **pousse** donc le secret vers un canal
  choisi par l'opérateur — c'est la vraie valeur du mode déclaratif.
- **Livraison DANS le passage de génération, best-effort.** Le secret n'existe en clair qu'en
  mémoire, à la création. On livre donc immédiatement (hors verrou, car I/O réseau). Pas de
  stockage du secret pour retenter plus tard (contredirait « affiché une seule fois ») : si un canal
  échoue, on le rapporte, et l'opérateur fait **tourner la clé** (prune + remise) pour relivrer.
- **Idempotence par `secret_delivered_at`.** La livraison n'a lieu qu'à la **création** de la clé ;
  aux passages suivants la clé existe déjà (pas de nouveau secret) → aucune relivraison. L'horodatage
  documente l'état et servira à l'export.
- **Webhook : template + presets, pas de magie.** « S'adapter à tout webhook » automatiquement est
  illusoire (Slack ≠ Discord ≠ JSON générique). On fournit des **presets** prêts (`slack`/`discord`/
  `generic`) et un **template libre** avec jetons `#OllamaKey`/`#OllamaUrl`/`#OllamaLabel`. `generic`
  embarque tout le bloc d'environnement valorisé.
- **Secrets SMTP hors YAML.** La config SMTP suit la même règle : `${NOM}` interpolés depuis l'env,
  jamais de mot de passe en clair dans le fichier versionné.
- **Test self-contained plutôt qu'Inbucket en CI.** Python 3.13 a retiré `smtpd`/`asyncore` ; on
  écrit un **puits SMTP minimal** (`devfixtures/smtp_sink.py`, ~50 lignes, zéro dépendance) pour
  l'E2E déterministe, et on garde **Inbucket** comme mail catcher *humain* optionnel en dev (profil
  compose). Le webhook est capté par un endpoint ajouté au faux Ollama.

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
