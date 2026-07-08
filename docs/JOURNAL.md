# Journal — ollama-gateway

Journal chronologique des décisions (le plus récent en premier). Complète `CHANGELOG.md`
(quoi) par le **pourquoi**.

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
