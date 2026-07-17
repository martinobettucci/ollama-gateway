# Design System — ollama-gateway

Référence maîtresse de l'interface d'admin, dérivée de la **charte P2Enjoy SAS** et du site
p2enjoy.studio (validée par le responsable le 2026-07-07). Toute page/composant de
l'app doit s'y conformer ; les écarts se justifient dans ce fichier (voir § 6).

## 1. Palette officielle

| Rôle | Token CSS | Hex | Usage |
|---|---|---|---|
| **Bleu P2Enjoy** (primaire) | `--color-brand` | `#23468C` | CTA, liens, nav active, focus ring, catégorie « clés API » |
| **Vert** (succès) | `--color-success` | `#238C33` | Clés *actives*, confirmations (secret créé), catégorie « usage sain » |
| **Jaune** (accent) | `--color-accent` | `#D9CF4A` | Surlignage ponctuel — tuile « tokens » uniquement (parcimonie) |
| **Rouge** (danger) | `--color-danger` | `#F24141` | Erreurs (≥ 400), suppression/désactivation, clés *désactivées* |
| **Noir** (encre) | `--color-ink` | `#0D0D0D` | Titres, texte fort |

Déclinaisons autorisées (calculées, jamais de hex ad hoc dans les composants) :
`--color-brand-soft` (10 %) pour les fonds de pilule/badge ; `--color-brand-hover` `#1B3670` ;
idem pour success/danger/accent en fonds à 10–22 %.

### Neutres (structure)

| Usage | Hex |
|---|---|
| Fond de page | `#F7F8FA` |
| Surface (cartes, nav) | `#FFFFFF` |
| Bordures / séparateurs | `#E5E7EB` |
| Texte secondaire | `#4B5563` |
| Texte tertiaire / placeholders | `#6B7280` |

**Thème clair uniquement** (aligné sur le site corporate). Pas de dark mode tant que la
charte n'en définit pas un.

## 2. Typographie

- **Police** : pile système (`ui-sans-serif, system-ui, sans-serif`) — identique au site.
- **Titres** : gras (700), couleur encre `#0D0D0D`. H1 26 px, H2 16 px.
- **Corps** : 15 px, `#374151`, interligne 1.55.
- **Données techniques** (préfixes de clé, IP/CIDR, horodatages) : `ui-monospace` 13 px,
  chiffres tabulaires.
- Jamais de texte < 12 px.

## 3. Principes de composition (issus du site studio)

1. **Cartes blanches `rounded-xl`** (14 px), bordure `#E5E7EB` 1 px, ombre douce
   (`0 1px 3px rgb(0 0 0 / .06)`) ; au survol, ombre légèrement renforcée.
2. **Codage par catégorie avec les 4 couleurs** (liseré haut de carte + pastille d'icône) :
   **bleu** = clés API / actions primaires · **vert** = usage, créations, états sains ·
   **jaune** = tokens/quotas (un seul surlignage par vue) · **rouge** = erreurs / danger.
3. **Icônes pastilles** : carré arrondi (10 px) en fond doux de la couleur de catégorie,
   icône de la couleur pleine. Icônes **lucide**, trait 2 px, jamais d'emoji.
4. **Navigation en pilules** : item actif = fond `--color-brand-soft`, texte `--color-brand`,
   icône + libellé toujours ; inactif = texte `#4B5563`, hover fond gris `#F3F4F6`. La barre ne
   contient **que** la marque et la navigation (pas de sélecteur de langue — évite tout reflow).
5. **Sélecteur de langue (i18n)** : discret, calé **en bas à droite du pied de page** (`.langsel`,
   `position:absolute`), présent sur toutes les pages (login compris). Disclosure natif
   (`<details>`/`<summary>`, ouverture vers le haut, sans JS) : replié = **drapeau seul** de la
   langue courante + chevron ; déplié = liste **drapeau + nom natif**, item courant en
   `--color-brand-soft`. Les **drapeaux sont des SVG vectoriels** (`app/templates/_flags.html`),
   **jamais des emoji** (respect de la charte « icônes vectorielles » + rendu identique sur tous les
   OS, Windows compris). Écart assumé au « lucide only » : un drapeau est polychrome par nature.
6. **Boutons** : primaire = fond `#23468C`, texte blanc, `rounded-lg`, hover `#1B3670` ;
   secondaire = bordure `#E5E7EB`, fond blanc, hover fond gris ; destructif = rouge (plein ou
   contour). Hauteur ≥ 40 px, focus ring 2 px `#23468C` avec offset.
7. **Badges/chips `rounded-full`** : fond couleur à 10–15 %, texte couleur pleine + point de
   couleur (état de clé : `active` vert / `désactivée` rouge — jamais la couleur seule).
8. **Le jaune s'utilise avec parcimonie** : un surlignage par vue au maximum (la tuile
   « tokens ») ; il ne porte **jamais** de texte (fond de pastille avec icône encre, ou liseré).
9. **Dégradé navy→vert** : réservé aux zones « héros » (panneau gauche du login/setup) ;
   jamais sur les surfaces de travail.
10. **Plein viewport, toujours (règle dure).** L'app occupe **100 % de la largeur ET de la
   hauteur** de l'écran — aucun conteneur centré à `max-width`. Sur grand écran, le contenu
   se répartit en colonnes (`grid-split` ≥ 1360 px : table | formulaire, édition | usage ;
   `grid-cards` : grilles de cartes auto-remplies). Le login/setup est un split
   hero/formulaire pleine hauteur. Ce qui grandit avec l'écran, c'est le contenu, jamais
   des bandes vides.

## 4. Interactions & états

- Feedback < 100 ms sur tout clic ; transitions 150–250 ms `ease-out` ; respecte
  `prefers-reduced-motion`.
- Toute liste : état vide avec message + action (« Aucune clé — créez la première… »).
- Erreur affichée près du champ en `#F24141`, jamais seulement en couleur (icône + texte,
  `role="alert"`).
- Actions destructives (suppression, désactivation) : confirmation explicite pour la
  suppression, bouton rouge séparé des actions primaires.
- Focus visible au clavier partout (`:focus-visible`) ; contrastes AA (4.5:1).
- Cibles tactiles ≥ 40 px ; `cursor-pointer` sur tout élément cliquable.

## 5. Implémentation

- **Tokens CSS** : déclarés une seule fois dans `app/templates/base.html` (`:root`) — aucun
  hex ad hoc dans les pages.
- **Icônes** : lucide en SVG inline via la macro Jinja `app/templates/_icons.html`
  (`{% from "_icons.html" import icon %}`), taille 14–28 px, `stroke-width` 2,
  `aria-hidden` (le libellé texte accompagne toujours l'icône).
- **Drapeaux** (sélecteur de langue) : SVG inline via la macro `app/templates/_flags.html`
  (`{% from "_flags.html" import flag %}`), `flag(code, size)`, viewBox 30×20, `aria-hidden`
  (le nom natif accompagne le drapeau). Jamais d'emoji-drapeau (rendu incohérent selon l'OS).
- **Captures de référence** : `e2e/output/*.jpg` (+ vidéos `.webm`), observées en vision à
  chaque livraison.

## 6. Écarts justifiés

- **Rendu serveur Jinja2 (pas de React + Vite).** L'admin est un micro-panel LAN-only
  (4 gabarits, formulaires POST → redirect) embarqué dans le service FastAPI et déployé sur
  une cible ARM contrainte : aucun build front, aucune dépendance Node en prod. La convention
  générique « React + Vite pour les UI » est volontairement écartée ici ; elle redevient la
  règle si le panel grossit (graphiques interactifs, temps réel). La charte visuelle,
  elle, s'applique intégralement.
