# Changelog — ollama-gateway

Deux chapitres : **`[Non publié]`** (tampon des changements pas encore déployés en prod) puis
**`[Publié]`** (ce qui tourne réellement en production). Toute nouvelle entrée va sous `[Non publié]`.
Surface publique ⇒ **zéro secret** (clés, tokens, hôtes/IP internes).

## [Non publié]

- **Le gabarit VS Code contient enfin la clé et les vraies caractéristiques des modèles.** Le bloc
  de configuration proposé à la création (ou à la réémission) d'une clé demandait jusqu'ici de
  ressaisir la clé à la main, via un renvoi vers une invite de l'éditeur : il porte désormais le
  **secret réel**, complet et prêt à coller — c'est le seul moment où il est affiché.
  Deux défauts allaient avec, corrigés en même temps :

  - **La liste de modèles était systématiquement vide.** Le gabarit annonçait être valorisé avec
    les modèles autorisés de la clé, mais la page ne les lui transmettait jamais : le bloc sortait
    donc toujours sans aucun modèle, inutilisable tel quel.
  - **Les caractéristiques étaient inventées.** L'appel d'outils était annoncé comme toujours
    disponible et l'entrée image comme jamais disponible, pour tous les modèles sans distinction.
    Elles sont maintenant **demandées au serveur d'exécution** modèle par modèle : appel d'outils,
    entrée image et fenêtre de contexte réels. Deux modèles de la même passerelle donnent donc des
    lignes différentes.

  Le gabarit devient par ailleurs un **bloc à part**, avec sa **propre zone copiable** et son
  **propre bouton de copie** : les variables d'environnement ne disparaissent plus quand on
  l'affiche, et chacun des deux se copie séparément — l'un est un jeu de variables pour un shell,
  l'autre un JSON à coller dans les réglages de l'éditeur. Le type d'API annoncé est aligné sur la
  voie que l'éditeur emprunte réellement.

  Le gabarit gagne aussi les **tailles maximales d'entrée et de sortie**, absentes jusqu'ici et
  calculées pour que ce qui est annoncé passe réellement : la fenêtre réelle du modèle est ramenée
  au plafond de contexte de la clé, une part est réservée à la réponse, et la marge du garde-fou
  d'entrée est déduite — un client qui remplit la fenêtre annoncée ne se fera pas refuser sa
  requête. Si le serveur d'exécution est injoignable ou n'annonce rien, la modale le **dit** et
  produit des valeurs prudentes (ni outils, ni entrée image) plutôt que des valeurs inventées.
  Le secret n'est jamais reservi par une adresse interrogeable : il ne transite que par l'affichage
  unique de la modale. Fonctionnalité livrée à l'origine sans aucun test ; elle en a désormais
  vingt-deux (dix-neuf automatisés, trois de bout en bout), plus le manuel et ses captures.

## [Publié]

### Déployé en production — 2026-08-18 (migrations ≤ 0013)

Déploiement effectué et vérifié en production : `git pull`, reconstruction de l'image applicative
et recréation des services proxy + admin ; l'edge TLS n'était pas concerné et n'a pas été
reconstruit. Aucune migration à appliquer (base déjà à jour), données préservées.

Le **contrôle de cible** (changement de comportement) a été validé AVANT bascule contre la
configuration réelle : l'hôte effectivement emprunté par le trafic des 30 derniers jours correspond
à la cible rattachée à chaque clé — aucune requête légitime observée n'est refusée. Contre-épreuve
faite : un hôte étranger est bien refusé.

Preuves live : proxy `ok`, TLS public `200`, inférence non authentifiée `401`, admin `303`,
vue temps réel de nouveau fonctionnelle (plus d'erreur serveur), aucune erreur dans les journaux.

- **Correction — la vue « temps réel » du tableau de bord ne fonctionnait pas du tout.** Le panneau
  interrogeait le serveur toutes les 30 s et recevait une **erreur** à chaque fois : la requête
  s'appuyait sur une donnée inexistante, et un second défaut indépendant l'aurait fait échouer même
  une fois la première corrigée. Le graphique restait donc vide en permanence. Corrigé, et avec lui
  trois défauts qui l'auraient laissé inutilisable : le **nom des clés** n'était jamais transmis
  (infobulles et légende affichaient « undefined »), les **tranches horaires** n'étaient pas
  calées sur 15 minutes comme annoncé, et le **filtre par modèle** ne pouvait jamais correspondre
  (il comparait un nom de modèle à un type). La fonctionnalité était livrée sans aucun test : elle
  en a désormais seize.

- **Entrée LAN en clair, optionnelle (désactivée par défaut).** Il est désormais possible de servir
  le trafic **local** directement, sans le faire ressortir par l'entrée publique — l'aller-retour
  par l'extérieur est inutile, dépend du DNS public et échoue souvent (le retour « en épingle »
  n'est pas toujours supporté). L'écoute se fait sur une **adresse de réseau local explicite** ;
  sans configuration, elle retombe sur une écoute locale inerte. Même surface que l'entrée
  publique (mêmes chemins servis, même borne de taille), l'entrée publique restant chiffrée.
  ⚠ Cette entrée est **en clair** : la clé API circule non chiffrée sur le réseau local — à
  réserver à un réseau de confiance, de préférence avec une restriction d'origine sur la clé.
  Comme il s'agit d'une **passerelle distincte**, une clé qui l'emprunte doit avoir sa propre cible.

- **Une clé n'est plus utilisable que par SA passerelle (changement de comportement).** La cible
  rattachée à une clé n'était qu'un libellé documentaire (elle servait à générer les variables
  d'environnement) : n'importe quelle URL menant à la passerelle servait n'importe quelle clé.
  Désormais la passerelle **compare l'hôte et le port réellement empruntés** à l'URL de la cible de
  la clé et **refuse la requête (`403`)** en cas d'écart — une clé émise pour une entrée ne peut
  plus être rejouée à travers une autre, même si les deux mènent au même serveur d'exécution.
  À noter : **le port compte** (`…example` et `…example:8443` sont deux passerelles distinctes),
  de même qu'un accès par nom de domaine *vs* par adresse IP. Si un client doit entrer par
  plusieurs URL, créer **une cible par URL**. Aucune contrainte n'est appliquée tant que la cible
  d'une clé n'est pas configurée : une installation neuve n'est jamais verrouillée.

- **Correction — libellés absents sur le bouton « copier » d'une cible et sur toute la vue temps
  réel.** Ces deux écrans affichaient l'identifiant technique du libellé au lieu du texte (par ex.
  « tgt.copy »), dans **toutes** les langues : les textes correspondants n'avaient jamais été
  ajoutés aux catalogues. Onze libellés ajoutés dans les 24 langues. Un contrôle automatique
  vérifie désormais que tout libellé demandé par une page existe réellement — ce type d'oubli ne
  peut plus passer inaperçu.

### Déployé en production — 2026-08-17 (migrations ≤ 0013)

Déploiement effectué et vérifié en production : `git pull` sur le clone, reconstruction de l'image
applicative (proxy + admin) et recréation des deux services ; l'edge TLS n'était pas concerné par ces
changements et n'a pas été reconstruit. Données préservées (clés/serveurs/cibles intactes, clé maître
inchangée), aucune migration à appliquer (base déjà à jour). Balayage de sécurité pré-déploiement
**vert** sur l'environnement de développement (secrets, CVE des dépendances, SAST, suite de tests).
Preuves live : proxy `ok`, admin `303` (redirection de connexion), TLS public `200`, requête
d'inférence non authentifiée refusée `401`, et versions attendues constatées **dans le conteneur en
cours d'exécution**.

- **Sécurité — mise à jour de `cryptography` (CVE).** La version épinglée était affectée par une
  vulnérabilité connue (avis PYSEC-2026-3552) ; passage à la version corrigée. Le chiffrement au
  repos des jetons de serveurs distants (Fernet) a été revérifié après la montée de version
  (aller-retour chiffrement/déchiffrement, suite de tests complète verte). Aucune rupture d'API.

- **Correction — libellé « VS Code » manquant dans 23 langues.** La case à cocher « VS Code » de la
  modale de génération de clé n'existait qu'en français : les 23 autres langues de l'UE affichaient
  le texte français par repli. Traduction ajoutée partout, la règle de complétude clé-à-clé des
  catalogues est de nouveau respectée.

- **Point de terminaison « VS Code » à la création d'une clé.** La modale de configuration client
  propose une case **VS Code** qui génère un bloc de configuration prêt à coller, valorisé avec les
  vraies données de la clé (modèles autorisés, URL de la cible, libellé).

- **Bouton « copier » sur chaque URL de cible.** Chaque cible publique gagne une copie
  presse-papier directe, avec retour visuel.

- **Pastilles de taille de contexte distinctes.** Les 22 paliers de contexte ont désormais chacun
  leur couleur, au lieu d'une teinte unique : la taille se lit d'un coup d'œil dans les tableaux.

- **Vue temps réel au tableau de bord.** Nouveau visuel des **2 dernières heures** par tranches de
  15 minutes : histogramme empilé par clé et par **type de modèle** (texte / image / vision),
  filtres par clé et par modèle, rafraîchissement automatique.

- **Correction — navigation inutilisable sur mobile.** Avec sept entrées, la barre de navigation
  mesurait ~850 px et **forçait la page entière à déborder** (875 px de large sur un écran de
  360 px) : **quatre entrées — Logs, Manuel, Exporter et Déconnexion — étaient hors écran, donc
  totalement inaccessibles** depuis un téléphone, et le bandeau occupait 154 px de haut. Sous
  900 px, la barre se **replie** désormais derrière un bouton et les entrées deviennent une **pile
  verticale pleine largeur** : plus aucun débordement horizontal, cibles tactiles d'au moins 44 px,
  icône **et** libellé conservés, entrée courante toujours signalée, et la **déconnexion** est
  visuellement détachée des entrées de navigation. Le bandeau retombe à 64 px. Au-dessus de 900 px,
  la rangée de pilules d'origine est inchangée. Accessible au clavier (bouton `aria-expanded` /
  `aria-controls`, **Échap** referme et rend le focus) ; sans JavaScript, le bouton est masqué et la
  pile reste dépliée — rien n'est jamais hors d'atteinte.

- **Statistique des tailles de contexte réellement utilisées (par clé et par serveur).** L'échelle
  des plafonds devient une **liste de paliers** (2k · 4k · 8k · 12k · 24k · 36k · 48k · 64k · 72k ·
  96k · 108k · 112k · 128k · 144k · 180k · 224k · 256k · 384k · 512k · 640k · 768k · 1M) et chaque
  requête est **classée dans le plus petit palier qui la contient** (27 734 tokens → **36k**, car
  ils ne tiennent pas dans 24k ; 2 096 tokens → **4k**). La **page d'une clé** et le **monitoring
  d'un serveur** affichent désormais un **camembert** des tailles utilisées + un tableau
  **nombre de requêtes / tokens / dernier usage par palier**. On voit ainsi, parmi les tailles
  disponibles, lesquelles servent réellement — et on ajuste le plafond de chaque clé au plus juste.
  Le classement s'appuie sur les **compteurs réels de l'amont** (prompt + complétion) quand ils sont
  disponibles, sinon sur l'estimation d'entrée ; une requête refusée pour dépassement apparaît au
  palier qu'elle aurait nécessité (signal direct pour re-dimensionner).

- **Limite de contexte par clé (garde-fou anti-saturation de l'amont).** Chaque clé porte
  désormais un **plafond de contexte** — valeur **obligatoire** (jamais vide), choisie parmi les
  **paliers** de l'échelle (2k → 1M), **défaut 112k** — réglable dans le panel (création et édition) et affiché sur la
  ligne de la clé. Deux effets complémentaires :
  - **Refus en entrée** : le proxy **compte les tokens** du corps de la requête (tokenizer
    `tiktoken`) et **refuse (413) avant d'appeler l'amont** si le total dépasse le plafond. La
    réponse détaille l'estimation, la valeur majorée et le plafond. On échoue en quelques
    millisecondes au lieu de laisser une requête démesurée saturer le serveur d'exécution
    (prefill interminable → délai d'attente, ou échec d'allocation mémoire).
  - **Contrainte à l'amont** : le plafond est **injecté** dans la requête (`options.num_ctx`,
    Ollama natif) pour que le serveur n'alloue pas un contexte plus grand que nécessaire. Si le
    client demande déjà **moins**, sa valeur est conservée (le plafond est un maximum, pas une
    consigne). Les APIs OpenAI/Anthropic n'ayant pas d'équivalent standard par requête, la limite
    y est appliquée par le refus d'entrée seul.
  Le comptage est **majoré de 15 %** avant comparaison : `tiktoken` n'est pas le tokenizer exact
  des modèles servis, cette marge évite qu'un écart de tokenisation laisse passer une requête qui
  déborderait réellement. Les images (base64) ne sont pas comptées comme du texte. Le tokenizer
  fonctionne **hors-ligne** (fichier BPE embarqué dans l'image au build, aucun appel réseau au
  runtime) et, s'il était indisponible, replie sur une estimation plutôt que d'échouer. Réglable
  aussi en configuration déclarative (`max_context_tokens: 112k`), et repris dans l'export.

- **Réémission d'une clé (« Réémettre »).** Chaque clé du tableau de bord gagne un bouton
  **Réémettre** qui **génère un nouveau secret pour le même compte** : l'ancien secret est
  **invalidé immédiatement**, mais tout le reste est conservé — même clé/identité, label, origines,
  modèles, API, quotas, plafonds de vie, serveur/cible, et **tout l'historique d'usage**. Le nouveau
  secret est présenté **une seule fois** via la même modale que la création (variables
  d'environnement prêtes à coller). Utile quand un secret a fuité ou a été perdu, sans avoir à
  recréer et reconfigurer la clé de zéro.
- **Correction — bouton « Copier les variables » inopérant sur l'admin en HTTP (LAN).** En contexte
  **non sécurisé** (l'admin est servi en clair sur le LAN), `navigator.clipboard` est indisponible ;
  le repli `execCommand` échouait car sa zone de texte temporaire était ajoutée **hors** de la
  fenêtre modale, rendue **inerte** par `showModal()`. La zone est désormais insérée **dans** la
  modale (calque supérieur) → la copie fonctionne aussi en HTTP.

### Déployé en production — 2026-07-20 (migrations ≤ 0011)

Bascule effectuée et vérifiée en prod (WebUI conservée, mode UI classique — `GATEWAY_CONFIG` non
activé) : `git pull` sur le clone puis rebuild `docker-compose.prod.yml` (proxy + admin + Caddy),
données préservées (clés/serveurs/cibles intactes, `P2E_MASTER_KEY` inchangée), migrations 0010/0011
appliquées sur la base existante (colonnes additives). Preuves live : proxy `ok`, admin `200`, TLS
public `200`.

- **Mode déclaratif — phase 3 : export de la configuration.** Le panel gagne un bouton
  **« Exporter »** (et une commande `python -m app.reconcile export`) qui produit l'état courant
  (serveurs/cibles/clés) au **format YAML déclaratif** — l'inverse du mode headless : on configure à
  la souris, on exporte, on versionne. **Sans aucun secret** : les clés sont exportées **sans
  `value`** (une clé sera générée à l'import) ; les jetons de serveur distant (chiffrés) et la config
  SMTP/livraison (non persistée) sont à réintroduire manuellement. Ré-importable sur une base neuve
  pour recréer l'infrastructure. Route `GET /admin/config.yaml` (LAN-only, garde de session).

- **Mode déclaratif — phase 2 : livraison du secret des clés générées.** Une clé déclarative
  **générée** (sans `value`) voit son secret **poussé** vers les canaux configurés, une seule fois,
  dans le même passage de réconciliation : **e-mail** (SMTP configuré en YAML, secrets par `${NOM}`,
  TLS `none`/`starttls`/`tls`) et/ou **webhook** (`POST` avec **presets** `slack`/`discord`/`generic`
  ou **template libre** ; jetons `#OllamaKey`/`#OllamaUrl`/`#OllamaLabel`). Le message porte les
  **variables d'environnement valorisées** prêtes à coller. Idempotent (`secret_delivered_at`) :
  une clé déjà livrée ne l'est pas deux fois ; livraison best-effort (un canal en échec n'interrompt
  pas les autres, l'échec est rapporté). En dev, mail catcher **Inbucket** optionnel (profil
  compose `mail`) ; les tests E2E utilisent un puits SMTP intégré (aucun service externe).

- **Mode déclaratif (headless / « GitOps ») — phase 1 : réconciliation.** La passerelle peut
  désormais se déployer **sans WebUI**, configurée par un **fichier YAML** versionnable. Quand la
  variable d'environnement `GATEWAY_CONFIG` pointe vers un fichier (le drapeau vit dans
  l'**environnement**, jamais dans le YAML — sinon couplage circulaire), l'entrypoint **réconcilie**
  au démarrage l'état (serveurs d'exécution, cibles publiques, clés API) sur ce fichier, à la
  manière des migrations. Points clés : **aucun secret en clair** — les valeurs sensibles s'écrivent
  `${NOM}` et sont **interpolées depuis l'environnement** ; **identité stable** des clés via
  `external_ref` (le champ `name`) pour reconnaître une clé déjà créée ; **élagage conservateur** —
  une clé retirée du fichier est **désactivée** par défaut, et seulement **supprimée** si
  `prune: true` (les clés créées par l'UI ne sont jamais touchées) ; **liste de modèles statique**
  par serveur (sans sonde). Nouveau lanceur `runProdHeadless` + `docker-compose.headless.yml` (proxy
  + Caddy, **sans service admin**) et modèle `gateway.example.yaml`. La **livraison** du secret
  d'une clé générée (webhook/email) arrive en phase 2 ; en phase 1, on importe des clés au secret
  connu via `value: ${NOM}`.

- **En-têtes d'état de quota (style OpenAI/Groq).** Les réponses du proxy portent désormais, quand
  la clé a un rate-limit ou un plafond mensuel, `x-ratelimit-limit/remaining/reset-requests` et
  `…-tokens` ; le 429 ajoute `Retry-After`. Les clients bien élevés — surtout les **boucles
  d'agents** — peuvent ainsi se rythmer et décider d'attendre ou de s'arrêter proprement **avant**
  l'appel qui échouerait, ce qui évite les tempêtes de retry. Coût serveur négligeable (l'état est
  déjà calculé pour l'application des quotas) ; aucune en-tête pour une clé sans plafond.

- **Préparation open-source (source-available).** Ajout d'une **LICENSE** : usage libre et gratuit
  (y compris en entreprise) tant que l'ensemble des instances d'une entité sert **≤ 1 milliard de
  tokens/mois** ; au-delà, **licence commerciale** (somme libératoire unique de **29 € HT par
  installation**, usage illimité — contact@p2enjoy.studio). **Aucun contrôle ni télémétrie dans le
  code** : le respect du seuil est **sur l'honneur** (fair-use). Attribution/licence à conserver.
  Résumé dans le README. Ajout d'une **CI GitHub Actions** (tests + CVE + SAST + secrets, en écho à
  la gate locale). **Nettoyage** des ports/topologie réels des exemples, locales et commentaires
  (valeurs génériques). Revue de sécurité des dernières features (graphes/horizons, gestion des
  modèles par serveur) : aucune découverte.

- **Gestion des modèles par serveur + traçage de l'usage par modèle.** Le panel **Serveurs** gagne
  un bloc **« Modèles du serveur »** permettant de **télécharger** (`pull`) ou **supprimer**
  (`delete`) un modèle sur un serveur d'exécution donné, en **commande d'administration LAN-only**
  envoyée directement à l'amont (jeton distant déchiffré côté serveur, jamais côté navigateur) ;
  la liste des modèles est re-sondée après l'action. Le **monitoring d'un serveur** trace en plus,
  pour **chaque modèle réellement invoqué**, ses requêtes/tokens/erreurs et son **premier & dernier
  usage** (table « Usage par modèle », triée du plus récemment utilisé au plus ancien).
  **Garde-fou (règle dure, déjà en place et désormais couvert par des tests dédiés)** : le **proxy
  public refuse (403) toute commande de gestion** (`pull`/`push`/`delete`/`create`/`copy`/`blobs`)
  pour **n'importe quelle clé cliente** — seule la console peut piloter le catalogue amont. Couvert
  par tests unitaires (blocage proxy, `pull`/`delete` amont, agrégats par modèle) et E2E Playwright
  (télécharger → voir → supprimer un modèle ; refus proxy vérifié). Traductions ajoutées aux
  **24 locales**.
- **Durcissement de sécurité (audit pré-open-source).** Série de correctifs issus d'un audit complet
  (SAST + revue manuelle), chacun couvert par ses tests dédiés (`tests/test_security_fixes.py`) :
  - **Dépendances à jour** : purge des CVE connues des dépendances épinglées (`pip-audit` propre).
  - **Endpoints de gestion du catalogue non proxifiés** : `pull`/`push`/`delete`/`create`/`copy`/
    `blobs` renvoient désormais **403** pour toute clé — la passerelle est un proxy d'**inférence**,
    pas d'administration d'Ollama (ces chemins échappaient à l'allowlist de modèles).
  - **Bind admin fail-closed en prod** : le rôle admin **refuse de démarrer** si son adresse d'écoute
    est absente ou « toutes interfaces » (jamais exposé hors LAN par mégarde).
  - **Rate-limit résistant à la concurrence** : les requêtes en vol (streaming) comptent dans le
    débit par clé, plus seulement les requêtes déjà journalisées.
  - **Validation de l'URL amont d'un serveur** : schéma `http(s)` requis et plage link-local
    (métadonnées) refusée (les cibles loopback/LAN restent autorisées).
  - **Hachage du mot de passe admin renforcé** (pbkdf2 : nombre de tours relevé ; rétro-compatible).
  - **En-têtes de sécurité** : HSTS + `X-Content-Type-Options` côté public (Caddy) ; CSP +
    `X-Frame-Options`/`Referrer-Policy` côté panel ; borne de taille de corps au niveau de l'edge.
  - **Cookie de session `Secure` optionnel** (`ADMIN_COOKIE_SECURE`) pour un admin derrière TLS.
  - **Confidentialité des logs de contenu** : `REQUEST_LOG_BODIES=0` conserve les métadonnées des
    requêtes sans écrire le **corps** (prompts) sur disque (les en-têtes secrets restent masqués).
  - **Image de base épinglée par digest** (intégrité/reproductibilité de la supply-chain).
  - **Gate de sécurité avant déploiement** : `./runProd` lance un **balayage complet**
    (`scripts/security-sweep.sh` : secrets, CVE, SAST, tests) et **refuse de déployer** en cas de
    découverte ; contournement explicite et tracé via `ALLOW_INSECURE_DEPLOY=1`.
- **Visionneuse du contenu des requêtes (dans le panel).** Depuis la console de **Logs**, un
  bouton **Contenu des requêtes** ouvre une page où l'on choisit une **clé** puis une **heure**
  (fichier) et où l'on **filtre le contenu façon grep** (recherche insensible à la casse sur
  toutes les lignes). Chaque entrée se déplie sur la requête complète (méthode, chemin, en-têtes
  sanitisés, corps) ; le fichier brut est **téléchargeable** ; les fichiers compactés (gzip) sont
  lus de façon transparente. Lecture **LAN-only** avec noms de fichiers validés (défense
  anti-traversal) ; les secrets restent masqués (jamais de clé en clair). Nécessite l'admin
  configuré avec le même `REQUEST_LOG_DIR` que le proxy.
- **Internationalisation (i18n) du panel — 24 langues de l'UE.** L'admin est désormais entièrement
  traduisible via un **fichier YAML par langue** (`app/locales/<code>.yaml`), le français étant la
  source de référence. Les 24 langues officielles de l'Union européenne sont fournies (bg, cs, da,
  de, el, en, es, et, fi, fr, ga, hr, hu, it, lt, lv, mt, nl, pl, pt, ro, sk, sl, sv). Un **sélecteur
  de langue discret** est calé **en bas à droite du pied de page** (replié : drapeau seul de la langue
  courante ; déplié : drapeau + nom natif par langue — drapeaux en **SVG vectoriel**, jamais d'emoji),
  visible même déconnecté ; le choix est mémorisé en session. À défaut, la langue est **négociée**
  depuis l'en-tête `Accept-Language` du navigateur,
  avec repli sur le français puis sur la clé technique (l'interface ne casse jamais). Le sous-ensemble
  proposé peut être restreint via `SUPPORTED_LANGS`. Les libellés injectés côté JavaScript (sondes,
  échecs, WHOIS…) sont eux aussi traduits. Placeholders (`{param}`) et identifiants techniques (noms
  de variables d'env, chemins d'API) sont préservés à l'identique dans toutes les langues.

- **Pied de page d'attribution.** Toutes les pages du panel (login compris) affichent désormais un
  pied de page « Made proudly with AI by **P2Enjoy** with ♥ », où *P2Enjoy* renvoie vers
  `https://p2enjoy.studio` (nouvel onglet, `rel="noopener noreferrer"`). Cœur en icône vectorielle
  (charte, pas d'emoji-icône).

- **Sécurité — CSRF same-origin & anti-brute-force du login admin.** Toute requête mutante vers
  `/admin/*` dont le navigateur fournit un `Origin`/`Referer` d'un **autre hôte** est refusée
  (403), en complément du cookie de session `SameSite=Lax`. Le login admin applique un
  **verrouillage temporaire** après plusieurs échecs consécutifs depuis une même IP.

- **Sécurité — conteneur non-root & borne de taille de requête.** L'image applicative tourne
  désormais sous un **utilisateur non privilégié** (défense en profondeur). Le proxy **refuse
  (413)** un corps dont la taille déclarée dépasse `MAX_REQUEST_BYTES` (défaut 100 Mio, `0` =
  illimité), pour limiter la pression mémoire (le corps est bufferisé afin d'appliquer la
  restriction de modèle). Caddy peut aussi borner en amont.

- **Sécurité — démarrage prod « fail-closed » sur les secrets.** En production, la passerelle
  **refuse de démarrer** si `ADMIN_SESSION_SECRET` ou `P2E_MASTER_KEY` sont absents ou laissés à
  leur valeur de développement (non secrète). Empêche qu'une prod mal configurée signe ses
  sessions admin avec un secret connu (forge de cookie) ou chiffre les jetons distants avec une
  clé prévisible. Sans effet en dev/staging self-contained.

- **Sécurité — `X-Forwarded-For` résistant à l'usurpation.** L'IP source réelle est désormais
  lue à la **droite** de la chaîne `X-Forwarded-For` (l'entrée ajoutée par l'edge de confiance),
  en sautant les proxys de confiance. Un client externe ne peut plus forger une IP à gauche du
  header pour **usurper une origine autorisée** (allowlist par clé) ni **échapper à un ban**.

- **Génération d'images (Ollama & OpenAI) — capacité et modèles séparés.** Nouvelle capacité de
  **génération d'images**, distincte du texte, avec **cases à cocher dédiées** par voie : *Image via
  Ollama* (modèles du namespace `x/…` sur `POST /api/generate`) et *Image via OpenAI*
  (`POST /v1/images/generations`). Les **modèles d'image** (`x/…`) forment une **allowlist séparée**
  de celle des modèles texte (le proxy gate la requête selon la nature — image vs texte). Le bouton
  **« Essayer maintenant »** d'une clé où l'image est activée présente désormais **deux onglets,
  Texte et Image** ; l'onglet Image permet de choisir le modèle et la voie (Ollama/OpenAI), de
  saisir un prompt et de **joindre une image d'entrée** (image-to-image) — l'image produite
  s'affiche dans le panel. Aucun schéma n'est validé : la passerelle reste un relais transparent.
- **Monitoring par serveur d'exécution (consommation & erreurs par clé, graphiques).** Chaque
  serveur dispose d'une page **Monitor** : totaux (requêtes, tokens, erreurs, clés), **répartition
  des statuts** (camembert), **séries journalières** (requêtes & tokens / jour, 30 j), **top clés**
  (barres tokens & requêtes) et un **tableau consommation par clé** (requêtes, tokens, erreurs,
  dernier usage). Graphiques **SVG rendus serveur** à la charte P2Enjoy (aucun build front ni CDN).
  L'attribution est **réelle** (repli inclus) via l'enregistrement du serveur ayant traité.
- **Serveur de repli (fallback) transparent par clé.** Une clé peut désigner un **serveur de
  repli** : si l'amont primaire répond en **erreur serveur (5xx)** ou est **injoignable**, le proxy
  **rejoue la même requête** vers le repli, de façon transparente pour le client. L'événement
  d'usage est attribué au **serveur ayant réellement traité** (repli inclus).
- **Recherche & filtres des clés (tableau de bord).** Barre de recherche instantanée (label ou
  préfixe) + filtres par **serveur**, **famille d'API** et **état** (active/désactivée), appliqués
  côté navigateur sur la liste des clés.
- **Expiration & plafonds de VIE d'une clé (« essai à coût plafonné »).** Nouveaux réglages par
  clé, **distincts du rate-limit et du plafond mensuel** (qui se réinitialisent) : **plafond absolu
  de tokens** et **de requêtes** cumulés sur toute la vie de la clé, **date/heure d'expiration**, et
  **expiration par inactivité** (refus après N jours sans usage). Une fois un seuil franchi, le
  proxy refuse la clé (429) avec le motif correspondant.
- **Cibles publiques (ingress) rattachées par clé.** Nouvel onglet **Cibles** : gestion des URL
  **publiques** de la passerelle telles que vues par les clients (ex. `https://…:port`). Chaque
  clé pointe vers une cible ; la **génération des variables d'environnement** (post-création)
  utilise l'**URL de la cible rattachée** (repli sur `PUBLIC_BASE_URL`). Une cible **ne change pas
  le routage** (l'amont reste le serveur d'exécution) — c'est purement l'URL côté client. Cible
  par défaut indélébile, seedée depuis `PUBLIC_BASE_URL` ; suppression bloquée si des clés y sont
  rattachées.
- **Compatibilité d'API : matrice par serveur + allowlist par clé.** Chaque serveur d'exécution
  peut être testé (« Tester la compatibilité ») : la passerelle **rejoue un catalogue d'endpoints**
  des trois familles (Ollama natif `/api/*`, OpenAI-compatible `/v1/*`, Anthropic Messages
  `/v1/messages`) et **stocke une matrice** d'**accessibilité des chemins** (servi vs 404),
  affichée sur la page Serveurs. Le test vérifie uniquement l'**accès au chemin**, **sans valider
  les schémas de réponse**. Côté clé, comme pour les modèles, des **cases à cocher d'API
  autorisées** : cochées = allowlist appliquée par le proxy (allow/forbid de **chemin**) ;
  **aucune cochée = toutes les API autorisées**. Les endpoints de listing
  (`/api/tags`, `/v1/models`) restent toujours servis. Voir `docs/COMPAT_REPORT.md`.
- **Contenu complet des requêtes archivé sur fichiers (hors base).** Chaque requête
  authentifiée est écrite en clair (secrets `Authorization`/`x-api-key` **retirés**) dans un
  **dossier par clé**, un **fichier JSONL par heure** — jamais en base. La **rétention est
  réglable par clé** (champ « Rétention des logs » ; vide = défaut global `REQUEST_LOG_RETENTION_DAYS`).
  Un cron `python -m app.reqlog compact` **compacte** (gzip) les heures passées et **purge** au-delà
  de la rétention. Activé seulement si `REQUEST_LOG_DIR` est configuré.
- **Panel d'une clé : origines vues + recherche + WHOIS.** La page d'une clé liste les **IP
  uniques** qui l'ont utilisée (nombre de requêtes, dernière apparition), avec une **recherche**
  instantanée et un bouton **WHOIS** par origine (résolution RDAP ; les IP privées/locales sont
  signalées sans interrogation publique).
- **Console de logs & bannissement d'origines.** Nouvelle page **Logs** : journal complet des
  requêtes (une ligne par requête, autorisée ou refusée, conservé intégralement — jamais purgé)
  avec horodatage, origine, clé, méthode, chemin, modèle, statut, tokens et durée. Chaque ligne
  permet de **bannir l'IP en un clic** ; on peut aussi bannir/lever une IP ou un **CIDR** à la
  main. Une origine bannie est **refusée (403) par le proxy avant toute vérification de clé**
  (blocage réseau global, distinct des allowlists d'origine par clé).
- **Bouton « Essayer maintenant » enrichi.** La fenêtre de chat de test permet maintenant de
  **choisir le modèle** (parmi les modèles autorisés/détectés) **et l'API cliente** à tester :
  Ollama (`/api/chat`), OpenAI Chat Completions (`/v1/chat/completions`), OpenAI Responses
  (`/v1/responses`), Anthropic Messages (`/v1/messages`). La réponse indique le modèle et l'API
  utilisés ; le relais reste côté admin (LAN-only) et respecte l'allowlist de la clé.
- **Bouton « Essayer maintenant » sur une clé.** La page d'une clé propose une fenêtre de
  **chat de test** : le message est relayé (côté admin, LAN-only) vers le serveur rattaché à la
  clé, et la réponse du modèle s'affiche. Permet de vérifier en un clic que la configuration
  répond réellement, sans quitter le panel ni exposer le secret.
- **Layout plein viewport (règle dure).** Le panel occupe désormais **100 % de la largeur et
  de la hauteur de l'écran** (plus de colonne centrée) : tableau des clés et formulaire côte à
  côte sur grand écran, page Serveurs en grille de cartes, écran de connexion en split
  hero/formulaire pleine hauteur. **Les fenêtres modales (manuel, configuration client, chat de
  test) s'affichent en plein écran**, avec une barre de titre et un bouton **Fermer** bien
  visible (fermeture aussi par la touche Échap).
- **Modale « configurer le client » à la création d'une clé.** Elle génère les **variables
  d'environnement prêtes à copier** pour la machine cliente selon les API cochées — Ollama
  (`OLLAMA_HOST`, `OLLAMA_API_KEY`), OpenAI (`OPENAI_BASE_URL`, `OPENAI_API_KEY`), Anthropic
  (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) — avec bouton de copie en un clic. L'URL de base
  vient de la nouvelle variable d'env `PUBLIC_BASE_URL` de la passerelle.
- **Le proxy accepte la clé en en-tête `x-api-key`** (comportement du SDK Anthropic configuré
  via `ANTHROPIC_API_KEY`), en plus de `Authorization: Bearer` ; dans les deux cas l'en-tête
  est retiré avant l'appel amont.
- **Serveurs d'exécution (« executors ») multi-Ollama.** La passerelle route désormais vers
  plusieurs serveurs Ollama : le serveur **local** (créé automatiquement, indélébile) et des
  **serveurs distants** ajoutés dans l'admin (nom, URL, jeton Bearer optionnel **chiffré au
  repos**). Bouton **Tester** : sonde la disponibilité et liste les modèles détectés (en ligne /
  hors ligne). Chaque clé est **rattachée à exactement un serveur**.
- **Restriction des modèles par clé, agnostique de l'API.** Une clé peut être limitée à une liste
  de modèles autorisés sur son serveur : les formulaires de création et d'édition **sondent en
  direct le serveur choisi** et présentent ses modèles disponibles en **cases à cocher** (re-sonde
  à chaque changement de serveur ; repli en saisie libre si le serveur est injoignable ; allowlist
  = cases cochées + saisie libre, vide = tous). La restriction s'applique quelle que soit l'API du
  client (Ollama natif, OpenAI
  Chat/Responses, Anthropic Messages) : requête vers un modèle non autorisé → 403 ; les listes de
  modèles (`/api/tags`, `/v1/models`) sont filtrées à l'allowlist. Serveur rattaché indisponible → 503.
- **Manuel & captures** mis à jour (page Serveurs, clé restreinte) ; migration idempotente et
  **concurrent-safe** (verrou fichier ; `busy_timeout` avant WAL) pour le démarrage parallèle des
  rôles proxy/admin.
- **Panel d'admin restylé selon la charte graphique P2Enjoy** : thème clair, cartes blanches
  arrondies avec codage couleur par catégorie (bleu = clés, vert = usage, jaune = tokens,
  rouge = erreurs), navigation en pilules, icônes vectorielles lucide, écrans de connexion et
  d'initialisation avec bandeau dégradé. Accessibilité renforcée (focus clavier visible,
  contrastes AA, états vides explicites, `prefers-reduced-motion`).
- **Tests E2E déterministes** : la base dédiée aux tests est supprimée puis re-seedée à chaque
  run (plus de résidus entre exécutions) ; capture de l'écran de connexion ajoutée aux
  références visuelles.
- **Documentation** : nouveau manuel public (`docs/manual.md`, schémas Mermaid), journal des
  décisions (`docs/JOURNAL.md`), design system adapté au projet (`docs/DESIGN_SYSTEM.md`),
  retrait des hôtes/domaines réels des documents publiables.
- **Manuel utilisateur intégré au panel** : bouton « Manuel » dans la navigation ouvrant une
  modale qui affiche le manuel (markdown rendu côté serveur) illustré d'une **capture d'écran
  réelle par fonctionnalité** (connexion, tableau de bord, création de clé, détail/édition,
  usage). Les captures sont régénérées automatiquement par les tests E2E et synchronisées
  dans l'application ; règle de repo : manuel + captures mis à jour à chaque évolution.
- **`runDev` affiche désormais clairement le mot de passe admin de dev** dans son récapitulatif
  de fin de lancement.

### Déployé en production — 2026-07-06 (migrations ≤ 0001)

Bascule effectuée et vérifiée en prod : reverse-proxy nginx mono-clé retiré (sauvegardé),
**Caddy termine le TLS du domaine public** (cert Let's Encrypt via DNS-01 Scaleway), la clé
historique du client existant a été migrée (avec son origine), et l'agent client bascule sur
la nouvelle chaîne HTTPS. Preuves live : chaîne HTTPS externe 200, chat streaming + embed réels
via l'agent (l'embed qui échouait en 403 avec l'ancien nginx fonctionne désormais), usage
journalisé (tokens comptés).

- **Passerelle complète de gestion de clés Ollama** (première version).
  - Proxy d'inférence : auth par clé `Authorization: Bearer`, restriction d'origine par clé
    (IP/CIDR), quotas (plafond mensuel de tokens + rate-limit req/min), journalisation d'usage
    par requête, streaming intégral (NDJSON/SSE) avec strip de la clé avant l'amont, proxy de
    **tous** les endpoints (`/api/*`, `/v1/*`) et `/_proxy_health`.
  - Panel d'admin web LAN-only (Jinja) : login mot de passe, CRUD des clés (création avec secret
    affiché une seule fois, activation/désactivation, suppression, édition origines/quotas),
    dashboard d'usage (totaux + détail par clé + dernières erreurs).
  - Stockage **SQLite** (WAL) : `api_keys` (clé hachée), `key_origins`, `key_quotas`,
    `usage_events` (append-only), `admin_auth`. Migrations idempotentes.
  - Dockerisation dev/staging/prod + lanceurs ; dev self-contained/self-seeded (faux upstream).
  - **Caddy** avec module DNS Scaleway (Caddy 2.11) : TLS par challenge DNS-01
    (`secret_key` + `organization_id` + `dns_ttl` requis ; `auto_https disable_redirects`).
  - Import d'une clé existante par valeur (migration) via `python -m app.bootstrap import-key`.
  - Tests : 31 unitaires/intégration (pytest) + 3 E2E Playwright (admin UI + proxy), vérifiés
    en vision.
