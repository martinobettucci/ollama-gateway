# Journal — ollama-gateway

Journal chronologique des décisions (le plus récent en premier). Complète `CHANGELOG.md`
(quoi) par le **pourquoi**.

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
