# DESIGN.md — Système de design FACE.ai

## Palette de tokens

### tokens.css — variables CSS

#### Tokens ambients (mode galerie)

| Token                | Valeur par défaut        | Rôle                                  |
|----------------------|--------------------------|---------------------------------------|
| `--bg-primary`       | `hsl(0 0% 96%)`          | Fond principal (réécrit par ambient)  |
| `--bg-secondary`     | `hsl(0 0% 92%)`          | Fond secondaire, placeholders         |
| `--border`           | `hsl(0 0% 85%)`          | Filets, séparateurs                   |
| `--text-primary`     | `#1a1814`                | Texte principal                       |
| `--text-secondary`   | `#8a8278`                | Texte atténué, métadonnées            |
| `--accent`           | `#c8102e`                | Couleur d'accent unique               |
| `--color-warning`    | `#d97706` / `#f59e0b`    | États douteux ArcFace, alertes        |

#### Tokens immersifs (Flipbook · Lightbox — toujours sombres)

| Token                     | Valeur          | Rôle                                    |
|---------------------------|-----------------|-----------------------------------------|
| `--immersive-bg`          | `#080808`       | Fond principal overlay                  |
| `--immersive-bg-meta`     | `hsl(…/0.9)`    | Barre métadonnées basse (semi-opaque)   |
| `--immersive-text-primary`| `#e8e4de`       | Texte clair tiède                       |
| `--immersive-text-muted`  | `#5a5550`       | Texte atténué sombre                    |
| `--immersive-separator`   | `#3a3530`       | Séparateurs `|` dans la barre contrôles |

#### Palette de marque commune écosystème

| Token                  | Valeur      | Usage                                        |
|------------------------|-------------|----------------------------------------------|
| `--brand-neutral-dark` | `#1a1814`   | Identique à `--text-primary`                 |
| `--brand-neutral-light`| `#f6f2ea`   | Fond chaud clair                             |
| `--brand-accent-cool`  | `#007AFF`   | Famille analytique (face-ai + WUDD.ai)       |
| `--brand-success`      | `#3fb950`   | Actions validées, succès                     |
| `--brand-danger`       | `#FF3B30`   | Erreurs critiques                            |

---

## Règles obligatoires

- **Aucune valeur hex dans un fichier JSX/TSX.** Toute couleur passe par un token CSS via `var(--token)` ou une classe Tailwind mappée.
- **Le violet `#7C3AED` est interdit.** Ce code couleur appartient à Obsidian/Notion et entre en conflit avec l'identité FACE.ai. Si une couleur analytique froide est nécessaire, utiliser `--brand-accent-cool` (`#007AFF`).
- **`tokens.css` est la seule source de vérité.** Ne pas déclarer de couleurs dans `tailwind.config.js` sans correspondance dans `tokens.css`.

---

## Classes CSS utilitaires

| Classe               | Définition dans tokens.css             | Usage                                     |
|----------------------|----------------------------------------|-------------------------------------------|
| `.font-display`      | `font-weight: 300; letter-spacing: -0.01em` | Titres d'entités, noms propres       |
| `.divider`           | `border-color: var(--border)`          | Filets entre sections                     |
| `.ambient-halo`      | `box-shadow` ambient HSL 0.15 opacité  | Halo autour de l'image active (galerie)   |
| `.ambient-halo-dark` | `box-shadow` ambient HSL 0.25 opacité  | Halo Flipbook (fond sombre)               |

---

## Tailwind — classes mappées (syntax canonique)

Préférer les classes Tailwind mappées aux arbitraires `[var(…)]`.

| CSS var              | Classe Tailwind       |
|----------------------|-----------------------|
| `var(--accent)`      | `text-accent` / `bg-accent` / `border-accent` |
| `var(--bg-secondary)`| `bg-bg-secondary`     |
| `var(--bg-primary)`  | `bg-bg`               |
| `var(--text-primary)`| `text-ink`            |
| `var(--text-secondary)`| `text-ink-muted`    |
| `var(--border)`      | `border-border`       |

---

## Convention de nommage des nouveaux tokens

- **Primitif** : `--color-{hue}-{shade}` — ex. `--color-amber-600`
- **Sémantique** : `--color-{role}` — ex. `--color-warning`
- **Composant** : `--{composant}-{propriété}` — ex. `--button-bg`

---

## États visuels standard

| État        | Rendu attendu                                                      |
|-------------|--------------------------------------------------------------------|
| Chargement  | Texte `font-mono` + `text-ink-muted` — ex. `chargement…`          |
| Erreur      | Texte `text-accent font-mono uppercase` — ex. `erreur : message`   |
| Vide        | Texte `font-display text-3xl text-ink-muted` centré               |
| Flagged     | Bordure `border-accent` width 2 + badge `⚠` `text-accent`         |
| Douteux     | Bordure `--color-warning` width 2 + badge `?` `--color-warning`   |

---

## Typographie

- **Interface** : sans-serif système (`-apple-system`, `SF Pro Text`, `Segoe UI`…)  
- **Badges / compteurs / footers** : `Space Mono` (classe `font-mono`)  
- **Noms d'entités / titres** : `.font-display` (poids 300, letter-spacing -0.01em)  
- **Export JPG** : Cormorant Garamond + EB Garamond + Space Mono (médium figé)

Échelle pilotée par `<FontScaler>` via `--font-scale` (plage 0.7 → 1.5, persisté en localStorage).

---

## Icônes

face-ai utilise des **symboles Unicode** (`⌕ ☆ ★ ☀ 🌙 ⌧ ⊕ ◉ ▶ ❚❚`) cohérents avec l'esthétique forensique-musée. Cette approche ne doit **pas** être migrée vers une bibliothèque.

Pour tout **nouvel élément** nécessitant une icône, utiliser **Lucide React** `^1.14.0` (alignement avec WUDD.ai et be.CLEAR).
