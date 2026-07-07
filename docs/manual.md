# Manuel — Passerelle de clés Ollama

Document **public** : il explique le fonctionnement de l'application, sans détail
d'infrastructure (aucun hôte, aucune IP, aucun secret). Il est synchrone avec le code —
tout changement de comportement du backend met à jour ce manuel dans le même chunk.

## À quoi sert la passerelle ?

Un serveur Ollama n'a pas d'authentification : quiconque peut le joindre peut consommer
du calcul. La passerelle se place devant lui et ajoute :

- des **clés API par client** (`Authorization: Bearer sk-ollama-…`), révocables une à une ;
- une **restriction d'origine** par clé (liste d'IP ou de blocs CIDR autorisés) ;
- des **quotas** : plafond mensuel de tokens et/ou limite de requêtes par minute ;
- une **journalisation d'usage** par requête (compteurs de tokens compris) ;
- un **panel d'admin web** pour gérer tout cela, accessible uniquement depuis le réseau local.

```mermaid
flowchart LR
    C[Client externe] -- HTTPS + clé API --> E[Edge TLS Caddy]
    E --> P[Proxy passerelle]
    P -- clé strippée --> O[Ollama]
    A[Admin - LAN uniquement] --> W[Panel web]
    W --- DB[(SQLite)]
    P --- DB
```

Deux rôles distincts tournent à partir du même code (variable `GATEWAY_ROLE`) :

- le **proxy** — la seule surface exposée publiquement (derrière le TLS) ;
- l'**admin** — jamais exposé à Internet, réservé au réseau local.

## Cycle de vie d'une requête

```mermaid
sequenceDiagram
    participant C as Client
    participant P as Proxy
    participant DB as SQLite
    participant O as Ollama
    C->>P: POST /api/chat (Bearer sk-ollama-…)
    P->>DB: clé connue, active ?
    alt clé absente/inconnue/désactivée
        P-->>C: 401
    else origine non autorisée
        P-->>C: 403
    else quota mensuel ou rate-limit dépassé
        P-->>C: 429
    else OK
        P->>O: requête SANS l'en-tête Authorization
        O-->>P: réponse (streaming NDJSON/SSE intégral)
        P-->>C: réponse relayée telle quelle
        P->>DB: usage journalisé (tokens du chunk final)
    end
```

Points de comportement :

- **Tous** les endpoints Ollama sont proxifiés (`/api/*`, `/v1/*`) ; `/_proxy_health`
  répond sans authentification pour la supervision.
- Le **streaming est intégral** : les chunks sont relayés au fil de l'eau ; le comptage de
  tokens lit le payload final (`eval_count`, `prompt_eval_count`) y compris en streaming.
- La clé du client est **strippée avant l'amont** : Ollama ne la voit jamais.
- Les erreurs (≥ 400) sont journalisées et visibles dans le panel.

## Les clés API

| Propriété | Effet |
|---|---|
| Label | nom lisible (ex. `client-acme`) |
| Secret | affiché **une seule fois** à la création ; seul un hachage est stocké |
| État | une clé désactivée répond immédiatement 401 (réactivable sans changer le secret) |
| Origines | liste d'IP/CIDR (v4/v6) ; vide = toutes les origines |
| Plafond mensuel | budget de tokens par mois calendaire ; dépassé → 429 |
| Rate-limit | requêtes par minute glissante ; dépassé → 429 |

La suppression d'une clé est définitive (l'historique d'usage agrégé reste comptabilisé).

## Le panel d'admin

- **Première utilisation** : l'écran d'initialisation définit le mot de passe admin
  (8 caractères minimum), ensuite écran de connexion classique.
- **Tableau de bord** : totaux (requêtes, 24 h, tokens servis, erreurs), table des clés
  (état, origines, quotas, dernier usage) avec activation/désactivation et suppression
  (confirmation exigée), formulaire de création.
- **Détail d'une clé** : statistiques dédiées, édition (label, quotas, origines, note),
  usage des 30 derniers jours, dernières erreurs.

L'interface applique la charte graphique P2Enjoy (voir `docs/DESIGN_SYSTEM.md`).

## Journal des changements

Voir `CHANGELOG.md` (chapitres *Non publié* / *Publié*), publiable aux mêmes conditions
que ce manuel : zéro secret, zéro hôte réel.
