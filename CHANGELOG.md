# Changelog — ollama-gateway

Deux chapitres : **`[Non publié]`** (tampon des changements pas encore déployés en prod) puis
**`[Publié]`** (ce qui tourne réellement en production). Toute nouvelle entrée va sous `[Non publié]`.
Surface publique ⇒ **zéro secret** (clés, tokens, hôtes/IP internes).

## [Non publié]

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

## [Publié]

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
