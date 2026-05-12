# FACE.ai — Document de spécification fonctionnelle et technique
## *Portrait automatique de l'espace médiatique*

**Version** : 1.1 — draft  
**Auteur** : Patrick Ostertag  
**Contexte** : Composant satellite de WUDD.ai  
**Date** : Mai 2026

---

## 1. Vision du produit

FACE.ai est une galerie intelligente de portraits associés aux entités de type `PERSON` extraites par le pipeline NER de WUDD.ai. Son objectif est de centraliser, normaliser et comparer visuellement les images de personnalités identifiées dans les articles analysés.

Le système résout deux problèmes distincts :

- **Agrégation** : toutes les photos d'une même personne issues de sources variées sont rassemblées en un seul endroit.
- **Normalisation** : les images sont recadrées et alignées selon les landmarks faciaux pour permettre une comparaison visuelle cohérente (même taille inter-oculaire, même centre, même cadrage).

### 1.5 Posture, conformité, ce que FACE.ai n'est pas

FACE.ai est une **combinaison originale de briques connues** (NER, MediaPipe, ArcFace, Wikidata) **assemblée dans un contexte précis** : veille interne sur le corpus que WUDD.ai a déjà décidé de traiter, avec une dimension artistique assumée (le Flipbook, le composite Galton et l'esthétique forensique-musée font partie de la proposition de valeur, pas d'un habillage).

**Ce que c'est.**
- Un outil de veille interne sur un corpus maîtrisé (les articles passés par WUDD.ai, eux-mêmes filtrés en amont).
- Un objet à dimension artistique : la galerie alphabétique et le mode Flipbook sont des dispositifs scopiques autant qu'analytiques.
- Une extension cohérente de WUDD.ai, exploitée sur le même réseau Tailscale, pour le même utilisateur.

**Ce que ce n'est pas, et ce que la spec doit refuser de devenir.**
- Pas un projet de recherche académique généraliste sur la reconnaissance faciale.
- Pas un outil de surveillance de masse ni de tracking d'individus inconnus.
- Pas un SaaS multi-tenant : il n'y a ni inscription, ni partage public, ni API ouverte.
- Pas un système d'identification temps réel à partir de flux vidéo ou de photos personnelles fournies par un tiers.

**Régime juridique applicable.**
Le traitement d'images de visages identifiables relève du RGPD (UE) et de la nLPD (Suisse, en vigueur depuis 2023) — y compris pour un usage interne et non-commercial. FACE.ai s'inscrit dans le régime de l'**intérêt légitime** (RGPD art. 6.1.f, nLPD art. 31 al. 2 lettre c) parce que :
- Les personnes traitées sont des **personnalités publiques** apparaissant nommément dans des articles de presse déjà publiés.
- Le traitement reste **proportionné** au besoin de veille (volume modéré ~16k–30k entités, pas de dérivation comportementale).
- L'accès est **limité au LAN/Tailscale** de l'opérateur — pas de diffusion publique.

**Conditions de maintien de ce régime.** Si l'un des éléments suivants change, l'analyse juridique est à refaire (et la spec à amender) :
- Élargissement du corpus à des personnes privées non publiques.
- Exposition publique de la galerie ou de l'API.
- Croisement avec des données comportementales (géolocalisation, opinions politiques inférées).
- Mise à disposition de tiers, même gratuite.

Voir aussi §19 — point ouvert sur la documentation conformité (registre des traitements, droits des personnes concernées, durée de conservation).

---

## 2. Périmètre fonctionnel

### 2.1 Modules principaux

| Module | Rôle |
|---|---|
| **Scraper** | Extraction des images et métadonnées depuis les articles WUDD.ai |
| **Base de données** | Stockage des entités, images, métadonnées et résultats d'analyse |
| **Face Processor** | Détection, classification de pose, alignement facial |
| **API** | Backend REST exposant les données à l'interface |
| **Frontend React** | Interface galerie, navigation alphabétique, visualisation |
| **Serveur MCP** | Interface Model Context Protocol pour agents IA (Claude, etc.) |

### 2.2 Fonctionnalités utilisateur

- Navigation alphabétique des entités `PERSON`
- Sélection d'une entité → affichage de toutes ses images
- Filtrage par pose détectée (face / profil gauche / profil droit)
- Visualisation en mode galerie ou en mode comparaison alignée
- Pour chaque image : copier l'URL, télécharger l'original, télécharger le recadré aligné
- Affichage des métadonnées : caption, copyright, article source

---

## 3. Architecture système

```
WUDD.ai
  └── Articles HTML (NER → entités PERSON)
          │
          ▼
     scraper.py
     (BeautifulSoup4 + requests)
          │
          ▼
     database.py
     (SQLite + SQLAlchemy)
          │
          ▼
     face_processor.py
     (MediaPipe + OpenCV)
          │
          ▼
     api.py (FastAPI)
          │
          ▼
     Frontend React
```

### 3.1 Stack technique

**Backend Python**

| Couche | Bibliothèque | Rôle |
|---|---|---|
| Scraping | `requests`, `BeautifulSoup4`, `newspaper3k` | Extraction HTML, images, métadonnées |
| Base de données | `SQLite`, `SQLAlchemy`, `Alembic` | Persistance, migrations |
| Vision | `MediaPipe Face Mesh` | Landmarks 3D, classification de pose |
| Vision | `OpenCV (cv2)` | Transformation géométrique, alignement |
| Vision | `Pillow (PIL)` | Manipulation d'images, export |
| Vision | `DeepFace` *(optionnel)* | Détection robuste multi-backend |
| API | `FastAPI`, `Uvicorn` | Endpoints REST |

**Frontend React**

| Couche | Bibliothèque | Rôle |
|---|---|---|
| Framework | React 18 | Interface |
| Style | Tailwind CSS | Mise en page |
| Requêtes | TanStack Query | Fetch + cache |
| Routing | React Router | Navigation entités |
| Animations | Framer Motion | Transitions galerie |

---

## 4. Modèle de données

### 4.1 Vue d'ensemble

```
entities ──< entity_aliases          (variantes de noms)
entities ──< article_entities >── articles
articles ──< images
images   ──< face_analysis
images   ──  images.duplicate_of     (auto-référence doublons)
```

### 4.2 Table `entities`

```sql
entities (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,          -- forme canonique "Altman, Sam"
  slug          TEXT UNIQUE NOT NULL,   -- "sam-altman"
  first_seen    DATETIME,
  article_count INTEGER DEFAULT 0,      -- dénormalisé, mis à jour par trigger
  image_count   INTEGER DEFAULT 0,      -- dénormalisé
  diversity_score FLOAT DEFAULT 0,      -- calculé en P7
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### 4.3 Table `entity_aliases`

Gère les variantes de noms selon les sources ("Sam Altman", "Samuel H. Altman", "S. Altman").

```sql
entity_aliases (
  id         INTEGER PRIMARY KEY,
  entity_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias      TEXT NOT NULL,             -- variante de nom telle qu'elle apparaît
  source     TEXT,                      -- domaine source (ex. "lemonde.fr")
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(entity_id, alias)
)
```

### 4.4 Table `articles`

Dénormalisé auparavant dans `images` — maintenant table propre pour éviter la duplication quand un article contient plusieurs entités.

```sql
articles (
  id            INTEGER PRIMARY KEY,
  url           TEXT UNIQUE NOT NULL,
  title         TEXT,
  published_at  DATE,                   -- date de publication extraite
  scraped_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  source_domain TEXT,                   -- "lemonde.fr", "reuters.com", etc.
  wudd_article_id TEXT                  -- identifiant côté WUDD.ai si disponible
)
```

### 4.5 Table `article_entities`

Table de jointure many-to-many entre articles et entités.

```sql
article_entities (
  article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  confidence  FLOAT DEFAULT 1.0,        -- score NER WUDD.ai si disponible
  PRIMARY KEY (article_id, entity_id)
)
```

### 4.6 Table `images`

```sql
images (
  id                 INTEGER PRIMARY KEY,
  article_id         INTEGER REFERENCES articles(id) ON DELETE SET NULL,
  entity_id          INTEGER REFERENCES entities(id),  -- entité principale associée
  source_url         TEXT NOT NULL,
  local_path         TEXT,                   -- chemin fichier original
  aligned_path       TEXT,                  -- chemin fichier aligné
  caption            TEXT,
  copyright_text     TEXT,
  alt_text           TEXT,
  width_px           INTEGER,
  height_px          INTEGER,
  -- Statut du pipeline
  scrape_status      TEXT DEFAULT 'pending', -- 'pending'|'downloaded'|'failed'
  http_status        INTEGER,                -- code HTTP du téléchargement
  analysis_status    TEXT DEFAULT 'pending', -- 'pending'|'done'|'failed'|'no_face'
  -- Déduplication (P7)
  embedding          BLOB,                   -- vecteur FaceNet 512d
  is_duplicate       BOOLEAN DEFAULT FALSE,
  duplicate_of       INTEGER REFERENCES images(id),
  -- Association
  association_status TEXT DEFAULT 'auto',    -- 'auto'|'confirmed'|'rejected'|'reassigned'
  scraped_at         DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### 4.7 Table `face_analysis`

```sql
face_analysis (
  id                INTEGER PRIMARY KEY,
  image_id          INTEGER UNIQUE REFERENCES images(id) ON DELETE CASCADE,
  face_detected     BOOLEAN,
  pose              TEXT,           -- 'front' | 'left' | 'right' | 'unknown'
  confidence        FLOAT,          -- score de confiance détection (0–1)
  yaw               FLOAT,          -- rotation horizontale (degrés)
  pitch             FLOAT,          -- inclinaison verticale (degrés)
  roll              FLOAT,          -- rotation dans le plan
  eye_distance_px   INTEGER,        -- écart inter-oculaire en pixels (image originale)
  left_eye_x        FLOAT,
  left_eye_y        FLOAT,
  right_eye_x       FLOAT,
  right_eye_y       FLOAT,
  nose_x            FLOAT,
  nose_y            FLOAT,
  analyzed_at       DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### 4.8 Index recommandés

```sql
CREATE INDEX idx_images_entity     ON images(entity_id);
CREATE INDEX idx_images_article    ON images(article_id);
CREATE INDEX idx_images_status     ON images(scrape_status, analysis_status);
CREATE INDEX idx_images_duplicate  ON images(is_duplicate);
CREATE INDEX idx_face_pose         ON face_analysis(pose, confidence);
CREATE INDEX idx_articles_domain   ON articles(source_domain);
CREATE INDEX idx_articles_date     ON articles(published_at);
CREATE INDEX idx_ae_entity         ON article_entities(entity_id);
CREATE INDEX idx_aliases_alias     ON entity_aliases(alias);
```

### 4.9 Schéma de migration Alembic

Les migrations sont versionnées dans `backend/migrations/`. Ordre d'application :

```
v001_create_entities.py
v002_create_articles.py
v003_create_article_entities.py
v004_create_entity_aliases.py
v005_create_images.py
v006_create_face_analysis.py
v007_add_indexes.py
```

---

## 5. Pipeline de traitement facial

### 5.1 Détection et landmarks

Bibliothèque principale : **MediaPipe Face Mesh** (468 landmarks 3D).  
Fallback : **face_recognition** (dlib, 68 landmarks 2D).

Points clés extraits :
- Centre de l'œil gauche (moyenne landmarks 33, 133)
- Centre de l'œil droit (moyenne landmarks 362, 263)
- Pointe du nez (landmark 1)
- Angles de pose : yaw, pitch, roll (estimation via PnP solver OpenCV)

### 5.2 Classification de pose

```
|yaw| < 15°          → 'front'
yaw ≤ -15°           → 'left'   (profil gauche)
yaw ≥  15°           → 'right'  (profil droit)
```

### 5.3 Algorithme d'alignement

Objectif : toutes les images d'une même personne sont comparables visuellement.

1. **Calcul de la rotation** : angle entre les deux yeux → rotation affine pour horizontaliser
2. **Normalisation de l'échelle** : mise à l'échelle pour que l'écart inter-oculaire = `EYE_DISTANCE_TARGET` (ex. 80 px)
3. **Recadrage centré sur le nez** : fenêtre fixe de `CROP_SIZE × CROP_SIZE` (ex. 300 × 300 px)
4. **Export** : JPEG 90%, sauvegardé dans `aligned_path`

Paramètres configurables dans `config.py` :
```python
EYE_DISTANCE_TARGET = 80    # px
CROP_SIZE = 300             # px (carré)
CROP_OFFSET_Y = 0.35        # position verticale des yeux dans le crop (35% du haut)
```

### 5.4 Règle de purge — la DB ne contient que des portraits valides

FACE.ai n'archive **pas** les échecs. Une image n'entre dans la base que si elle franchit en cascade quatre validations ; tout échec à n'importe laquelle d'entre elles entraîne une suppression silencieuse (pas d'enregistrement DB, pas de fichier sur disque) :

1. **Téléchargement** : HTTP 2xx, taille ≤ 5 MB, bytes effectivement reçus dans la fenêtre de retry. Le scraper télécharge en RAM puis n'écrit le fichier que si l'enregistrement DB est créé.
2. **Lecture par OpenCV** : `cv2.imread()` doit retourner une matrice — un fichier corrompu ou un format non supporté est purgé.
3. **Détection de visage par MediaPipe Face Mesh** : doit trouver un visage, ET l'écart inter-oculaire détecté doit être ≥ 25 px (en-dessous, l'alignement à 80 px target produit un blur excessif et le crop n'a pas de valeur informative).
4. **Confirmation par RetinaFace (InsightFace)** au moment du calcul d'embedding ArcFace (cf. §5.5). MediaPipe Face Mesh accepte des patterns visuels semblables à un visage (logos, icônes d'app, pictogrammes "18+" + main, illustrations) ; RetinaFace est entraîné sur des visages humains réels et rejette ces faux positifs. Si RetinaFace ne trouve pas de visage là où MediaPipe en avait vu un, l'image est purgée par `identity_audit.compute_missing_identities`.

**Pourquoi cette règle.** FACE.ai est un espace de portraits, pas un journal de scraping. Conserver des lignes en `scrape_status='failed'` ou `analysis_status='no_face'` polluerait les requêtes API, gonflerait artificiellement les compteurs, et imposerait un filtre `WHERE` à chaque endpoint de lecture. La purge à l'ingestion garantit que toute ligne `images` est exposable telle quelle.

**Conséquence sur les statuts.** Les colonnes `scrape_status` et `analysis_status` ne peuvent plus contenir que `'downloaded'` et `'done'` respectivement (`'pending'` n'est qu'un état intermédiaire dans une transaction). Les valeurs `'failed'` et `'no_face'` sont conservées dans le schéma pour rétro-compatibilité avec les migrations historiques mais ne sont plus écrites.

**Migration depuis l'état antérieur.** `python face_processor.py --purge-invalid` parcourt les images héritées en `failed`/`no_face` et applique la nouvelle règle.

**Cas non couverts (à raffiner).** Détecter qu'un visage humain est en réalité un dessin, une statue, ou un visage généré par IA dépasse le cadre actuel — MediaPipe n'a pas de classificateur PERSON vs ILLUSTRATION. Si nécessaire, ajouter une étape ML supplémentaire avant l'alignement.

### 5.5 Vérification d'identité — pipeline ArcFace (§11.2 anticipée)

L'association image↔entité produite par le scraper repose sur un matching texte (caption/alt contient le nom). C'est fragile : photos de groupe, légendes ambiguës, articles enchaînant plusieurs personnes. Pour auditer ces associations on calcule un **embedding d'identité** par image (ArcFace 512-dim via InsightFace `buffalo_s`).

Pipeline (4e boucle worker, indépendante du pHash) :

1. **`compute_missing_identities`** : pour chaque image téléchargée sans `identity_embedding`, détection RetinaFace + extraction ArcFace. Skippe silencieusement si aucun visage ou visage non discernable.
2. **`update_centroid`** par entité : centroïde = moyenne L2-renormalisée des embeddings des images **non-`flagged`** (sinon une mauvaise association polluerait la référence).
3. **`audit_entity`** : pour chaque image, distance cosine au centroïde de son entité. Met à jour `images.identity_match_score` et bascule `association_status` : `auto` → `confirmed` (≤ 0.55) ou `flagged` (> 0.55).

**Status `association_status` (énum effectif)**
- `auto` : associé par caption, pas encore audité (centroïde absent ou identité non calculable)
- `confirmed` : audité, distance ≤ 0.55 au centroïde
- `flagged` : audité, distance > 0.55 — caption probablement incorrecte
- `manual` : correction humaine ultérieure (P9, à confirmer dans la spec)

**Stockage** : 2048 octets/image (512 floats×4) → ~60 MB pour 30k images. Centroïde `entities.identity_centroid` : 2048 octets aussi.

**Limite connue**. Le centroïde inclut l'image qu'on évalue, ce qui biaise vers la confirmation pour les entités à 1–2 images. Aucun effet pratique au-delà de 3 images. Pour faire mieux, calculer le centroïde « leave-one-out » par image — coût quadratique, jugé non nécessaire.

**Distinguer ArcFace de pHash**. Les deux ont l'air de répondre à la même question (« deux images se ressemblent-elles ? »), mais en pratique :
- `pHash` < 0.08 → c'est la **même image source** (à la compression près) → marquage `is_duplicate`
- `ArcFace` < 0.55 → c'est la **même personne**, possiblement sous un angle, un contexte, une coiffure différents → marquage `confirmed`
Une photo de groupe avec Sam Altman au fond peut avoir `pHash` distinct des autres ET `ArcFace` distance proche du centroïde Altman — toujours `confirmed` mais jamais `is_duplicate`.

---

## 6. API REST (FastAPI)

### Endpoints

**Entités**

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/entities` | Liste toutes les entités (nom, slug, counts, diversity_score) |
| `GET` | `/entities/{slug}` | Profil complet d'une entité + aliases |
| `GET` | `/entities/{slug}/images` | Images d'une entité, filtrables |
| `GET` | `/entities/{slug}/timeline` | Densité d'apparition par période |
| `GET` | `/entities/search?q=altman` | Recherche full-text sur nom et aliases |

**Images**

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/images/{id}` | Détail d'une image + analyse faciale |
| `PATCH` | `/images/{id}/association` | Corriger l'association image ↔ entité |

**Articles**

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/articles` | Liste des articles scrappés |
| `GET` | `/articles/{id}` | Détail article + entités + images |

**Pipeline**

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/scrape` | Lancer le scraping d'un article WUDD.ai |
| `POST` | `/analyze/{image_id}` | (Re)lancer l'analyse faciale sur une image |
| `GET` | `/queue` | État de la file de traitement (pending/done/failed) |

**Stats**

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/stats` | Statistiques globales du corpus |

### Paramètres de filtrage `/entities/{slug}/images`

```
?pose=front|left|right     filtre par pose détectée
?unique=true               exclure les doublons (is_duplicate=false)
?status=done               filtre par analysis_status
?date_from=2024-01-01      filtre par date article
?date_to=2024-12-31
?limit=20&offset=0         pagination
```

### Format de réponse type `/entities/{slug}/images`

```json
{
  "entity": {
    "id": 1,
    "name": "Altman, Sam",
    "slug": "sam-altman",
    "aliases": ["Sam Altman", "Samuel Altman"],
    "article_count": 14,
    "image_count": 31,
    "diversity_score": 0.74
  },
  "images": [
    {
      "id": 12,
      "source_url": "https://…",
      "aligned_url": "/static/aligned/sam-altman-12.jpg",
      "caption": "Sam Altman au Forum de Davos",
      "copyright": "© World Economic Forum",
      "scrape_status": "downloaded",
      "analysis_status": "done",
      "is_duplicate": false,
      "association_status": "confirmed",
      "article": {
        "id": 7,
        "title": "OpenAI dévoile GPT-5",
        "url": "https://wudd.ai/articles/…",
        "published_at": "2024-03-14",
        "source_domain": "wudd.ai"
      },
      "face": {
        "pose": "front",
        "yaw": -3.2,
        "pitch": 1.1,
        "confidence": 0.97,
        "eye_distance_px": 82
      }
    }
  ],
  "total": 31,
  "filtered": 12
}
```

---

## 7. Interface React

### 7.1 Structure des composants

```
<App>
  ├── <Header />                    — logo FACE.ai, stats globales
  ├── <AlphaNav />                  — barre A–Z, filtre actif
  ├── <EntityList>                  — colonne gauche
  │     └── <EntityRow />           — nom, nb images, miniature
  ├── <GalleryPanel>                — zone principale
  │     ├── <GalleryHeader />       — nom entité, filtres pose, bouton Flipbook
  │     ├── <PoseFilter />          — boutons Face / Profil G. / Profil D.
  │     └── <ImageGrid>
  │           └── <FaceCard />      — image, badge pose, actions
  │                 ├── badge pose
  │                 ├── badge aligné
  │                 ├── image (original ou alignée)
  │                 ├── caption + copyright
  │                 ├── lien article source
  │                 └── actions (copier URL, dl original, dl aligné)
  └── <FlipbookOverlay />           — overlay plein écran (portal React)
        ├── <FlipbookImage />
        ├── <FlipbookNav />
        ├── <FlipbookCounter />
        ├── <FlipbookAutoPlay />
        ├── <FlipbookMeta />
        └── <FlipbookClose />
```

### 7.2 Modes d'affichage

**Mode galerie** (défaut) : grille de `FaceCard` avec image originale, badge pose, métadonnées.

**Mode comparaison alignée** : grille serrée d'images recadrées normalisées, même dimensions, pas de métadonnées — focus sur la comparaison visuelle.  
Disponible uniquement pour les images avec `aligned = true`.

**Mode défilement rapide (Flipbook)** : voir section 7.5.

### 7.3 Actions par image

| Action | Comportement |
|---|---|
| Copier URL | `navigator.clipboard.writeText(source_url)` |
| Télécharger original | `<a download>` sur `source_url` |
| Télécharger recadré | `<a download>` sur `aligned_url` |
| Ouvrir article | Nouvelle onglet sur `article_url` |

### 7.4 Esthétique cible

Inspirée des outils d'analyse forensique et des interfaces de surveillance cinématographiques — dark UI, monospace, grille dense, badges techniques.

- Fond : `#080808` — `#0d0d0d`
- Accents : cyan froid `#4aaeff`, vert scan `#22ff88`
- Typographie : `Space Mono` (interface), `DM Serif Display` (noms d'entités)
- Bordures : `1px solid #1e1e1e`, glow cyan au hover
- Overlay scanlines sur chaque image

### 7.5 Mode défilement rapide — Flipbook

#### Déclenchement

Le mode Flipbook s'active :
- En cliquant sur une `FaceCard` en mode galerie ou comparaison alignée
- Via un bouton dédié `[ ⟷ Flipbook ]` dans le `GalleryHeader`

Il s'ouvre en **overlay plein écran** par-dessus la galerie.

#### Comportement

- Affiche **une seule image à la fois**, recadrée et alignée, en grand format centré
- Le filtre de pose actif détermine le sous-ensemble d'images affiché (ex. : si `front` est sélectionné, seules les images face défilent)
- L'index courant est affiché : `3 / 12`
- La navigation est **instantanée** (pas d'animation de transition — l'effet de mouvement vient de la succession rapide des images)

#### Contrôles

| Interaction | Action |
|---|---|
| `←` clavier | Image précédente |
| `→` clavier | Image suivante |
| Flèche gauche (UI) | Image précédente |
| Flèche droite (UI) | Image suivante |
| `Échap` | Fermer le Flipbook |
| Clic en dehors | Fermer le Flipbook |
| Scroll molette | Navigation (optionnel, v2) |

Les flèches UI sont des chevrons larges positionnés sur les bords gauche et droit de l'overlay, semi-transparents, apparaissant au survol.

#### Lecture automatique (optionnelle)

Un bouton `▶ Auto` déclenche le défilement automatique à vitesse configurable :

```
Vitesses : 0.5 fps | 1 fps | 2 fps | 4 fps
```

Permet de créer un effet d'animation morphologique entre les photos d'une même personne.

#### Informations affichées en Flipbook

Barre basse discrète (fond semi-transparent) :
- Caption de l'image
- Copyright
- Lien vers l'article source
- Actions : copier URL · télécharger original · télécharger recadré

#### Composant React

```
<FlipbookOverlay>
  ├── <FlipbookImage />         — image alignée plein cadre
  ├── <FlipbookNav>             — flèches gauche / droite
  ├── <FlipbookCounter />       — "3 / 12"
  ├── <FlipbookAutoPlay />      — bouton ▶ + sélecteur vitesse
  ├── <FlipbookMeta />          — barre basse caption/actions
  └── <FlipbookClose />         — bouton ✕ + Échap
```

#### Hook dédié

```js
// useFlipbook.js
const { current, total, next, prev, goTo, isOpen, open, close } = useFlipbook(images);

// Gestion clavier via useEffect + addEventListener
// KeyboardEvent: ArrowLeft → prev(), ArrowRight → next(), Escape → close()
```

---

## 8. Intégration avec WUDD.ai

### 8.1 Source des entités PERSON

Les entités sont issues du pipeline NER de WUDD.ai (OntoNotes schema, français). Deux modes d'alimentation :

**Mode push** : WUDD.ai appelle l'endpoint `/scrape` après chaque analyse d'article.  
**Mode pull** : FACE.ai interroge l'API WUDD.ai à intervalles réguliers (cron), récupère les nouveaux articles et scrape les images des entités `PERSON` détectées.

### 8.2 Format d'entrée attendu depuis WUDD.ai

```json
{
  "article_url": "https://wudd.ai/articles/openai-gpt5",
  "article_title": "OpenAI dévoile GPT-5",
  "entities": [
    { "name": "Sam Altman", "type": "PERSON" },
    { "name": "Ilya Sutskever", "type": "PERSON" }
  ]
}
```

Le scraper extrait ensuite toutes les images de la page et tente d'associer chaque image à une entité via :
- L'attribut `alt` de la balise `<img>`
- La `<figcaption>` ou légende associée
- Le score de similarité textuelle entre caption et noms d'entités

---

## 9. Enrichissement Wikimedia

### 9.1 Principe

Lorsqu'une entité PERSON est identifiée par WUDD.ai, FACE.ai tente de l'ancrer dans **Wikidata** pour récupérer un identifiant stable (`Q-number`). Cet identifiant ouvre l'accès à trois sources complémentaires :

```
WUDD.ai (entité PERSON)
        │
        ▼
  Wikidata API          → Q-number, métadonnées structurées
        │
        ├── Wikimedia Commons API  → portraits libres de droits
        └── Wikipédia API         → résumé biographique, liens
```

L'enrichissement est **asynchrone** — déclenché par le service `worker` après création d'une entité, jamais en temps réel. Non bloquant : si Wikidata ne retourne rien, l'entité reste fonctionnelle avec les seules images scrappées.

---

### 9.2 Résolution Wikidata

Objectif : obtenir le `Q-number` d'une entité à partir de son nom WUDD.ai.

**API utilisée : Action API** — `wbsearchentities` n'a pas encore d'équivalent dans la REST API v1.

```
GET https://www.wikidata.org/w/api.php
  ?action=wbsearchentities
  &search=Sam Altman
  &language=fr
  &type=item
  &limit=5
  &format=json
```

**Stratégie de résolution — ordre de précision décroissante :**

1. Correspondance exacte via `wbsearchentities` (`language=fr`, `type=item`, `limit=5`)
2. Désambiguïsation : filtrer sur `instance of` = `human` (P31 = Q5), prendre le score le plus élevé
3. Validation croisée : vérifier que l'alias WUDD.ai figure dans les labels/aliases Wikidata retournés
4. Fallback manuel : si score < 0.8, marquer `wikidata_status = 'unresolved'`, résolution manuelle depuis l'interface

**Champs ajoutés à `entities` :**

```sql
wikidata_id        TEXT UNIQUE,   -- "Q7251"
wikidata_status    TEXT DEFAULT 'pending',
                   -- 'pending' | 'resolved' | 'unresolved' | 'manual'
wikidata_score     FLOAT,         -- confiance de la résolution automatique
wikidata_synced_at DATETIME
```

---

### 9.3 Métadonnées biographiques Wikidata

Une fois le Q-number obtenu, récupérer les données structurées de l'entité.

**API utilisée : Wikibase REST API v1** (stable depuis novembre 2024, couverte par la Stable Interface Policy).

```
GET https://www.wikidata.org/w/rest.php/wikibase/v1/entities/items/{id}
  ?_fields=statements,sitelinks,labels
```

Format de réponse REST v1 — les statements sont une liste d'objets (différent de l'Action API) :
```json
{
  "statements": {
    "P569": [{ "value": { "content": { "time": "+1985-04-22T00:00:00Z" } } }],
    "P27":  [{ "value": { "content": { "id": "Q30" } } }]
  },
  "sitelinks": {
    "frwiki": { "title": "Sam Altman" }
  }
}
```

**Propriétés extraites :**

| Propriété | Code | Type |
|---|---|---|
| Date de naissance | P569 | date ISO 8601 |
| Date de décès | P570 | date ISO 8601 (null si vivant) |
| Lieu de naissance | P19 | Q-number → label FR |
| Lieu de décès | P20 | Q-number → label FR |
| Nationalité(s) | P27 | liste Q-numbers → labels FR |
| Pays de résidence | P551 | Q-number → label FR |
| Profession(s) | P106 | liste Q-numbers → labels FR |
| Employeur actuel | P108 | Q-number → label FR |
| Genre | P21 | Q-number → label FR |
| Langue(s) parlée(s) | P1412 | liste → labels FR |

**Résolution des labels en batch :**
Les Q-numbers des lieux, nationalités, professions sont résolus en labels FR via la REST API v1 (max 50 par requête) :

```
GET https://www.wikidata.org/w/rest.php/wikibase/v1/entities/items
  ?ids=Q30|Q142|Q16|Q17
  &_fields=labels
```

Si le batch dépasse 50 Q-numbers, découper en plusieurs requêtes (`getManyEntities`).

**Champs ajoutés à `entities` :**

```sql
-- Identité civile
birth_date        DATE,
death_date        DATE,              -- null si vivant
age_at_death      INTEGER,          -- calculé si death_date renseignée
birth_place       TEXT,              -- "Chicago, Illinois"
death_place       TEXT,
-- Nationalité et résidence
nationalities     TEXT,              -- JSON array ["américain", "canadien"]
residence         TEXT,
-- Activité
occupations       TEXT,              -- JSON array ["chef d'entreprise", "investisseur"]
employer          TEXT,
-- Biographie Wikipédia (section 9.5)
wiki_summary      TEXT,
wiki_description  TEXT,
wiki_url          TEXT,
wiki_thumbnail    TEXT
```

**Calcul de l'âge :**
- `death_date` null → âge calculé dynamiquement à l'affichage
- `death_date` renseignée → `age_at_death` calculé et stocké

---

### 9.4 Images Wikimedia Commons

**API utilisée : Action API** (recommandée pour les métadonnées de licence — les Structured Data on Commons restent incomplètes pour de nombreux fichiers).

**Source primaire — P18 via REST API v1 :**
```
GET https://www.wikidata.org/w/rest.php/wikibase/v1/entities/items/{id}
  ?_fields=statements
→ statements.P18[0].value.content  →  nom fichier Commons
```

**Résolution fichier + licence via Action API Commons :**
```
GET https://commons.wikimedia.org/w/api.php
  ?action=query
  &titles=File:{nom_fichier}
  &prop=imageinfo
  &iiprop=url|extmetadata|dimensions|mime
  &iimetadataversion=latest
  &format=json
```

Champs extraits de `extmetadata` : `LicenseShortName`, `Artist`, `ImageDescription`, `DateTime`.

Note : depuis T360589, l'URL de miniature retournée par `iiurlwidth` ne correspond plus exactement à la largeur demandée — utiliser l'URL originale et redimensionner côté client.

**Source élargie — recherche Commons :**
```
GET https://commons.wikimedia.org/w/api.php
  ?action=query
  &generator=search
  &gsrsearch=Sam Altman portrait
  &gsrnamespace=6
  &prop=imageinfo
  &iiprop=url|extmetadata|dimensions|mime
  &iimetadataversion=latest
  &gsrlimit=10
  &format=json
```

Filtres : `mime = image/jpeg|image/png`, dimensions ≥ 300×300px, titre n'incluant pas `logo`, `signature`, `map`, `flag`.

Les images Wikimedia sont insérées dans `images` avec :
```sql
source_type        = 'wikimedia'
association_status = 'confirmed'
copyright_text     = LicenseShortName + " · " + Artist
```

---

### 9.5 Enrichissement biographique Wikipédia

**API utilisée : Wikimedia REST API v1** (stable, ≤ 200 req/s).

```
GET https://fr.wikipedia.org/api/rest_v1/page/summary/{title}
→ extract, thumbnail.source, description
```

Le titre Wikipédia est lu depuis les sitelinks de la REST API Wikidata : `sitelinks.frwiki.title`.
Fallback : `enwiki` si `frwiki` absent — stocker le résumé anglais brut sans traduction.

Note : le champ `api_urls` a été supprimé de la réponse — ne pas en dépendre.

---

### 9.6 Interface — fiche d'identité

Dans `GalleryHeader`, sous le nom de l'entité, une fiche compacte en `EB Garamond` :

```
Sam Altman
Chef d'entreprise américain

né le 22 avril 1985 à Chicago, Illinois
nationalité  américaine
réside à     San Francisco
employeur    OpenAI

[→ Wikipédia]  [→ Wikidata Q7251]
```

Règles d'affichage :
- Si `death_date` renseignée : afficher `† date · âge au décès` en `--text-secondary`
- Si `death_date` null : afficher l'âge actuel entre parenthèses `(40 ans)`
- Nationalités multiples : jointure par ` · `
- Professions multiples : les deux premières uniquement, puis `+N`
- Si un champ est absent : ne pas afficher la ligne (pas de "inconnu")

Composant : `<EntityBioCard entity={entity} />` — compact, collapsible si trop long.

---

### 9.7 Module `wikimedia_enricher.py`

```python
class WikimediaEnricher:
    # Action API — wbsearchentities (pas encore dans REST v1)
    def resolve_wikidata(self, name, aliases) -> WikidataMatch | None: ...

    # Wikibase REST API v1 — /entities/items/{id}
    def fetch_biographical_data(self, qid) -> BiographicalData: ...

    # Wikibase REST API v1 — batch /entities/items?ids=
    def resolve_labels_batch(self, qids, lang="fr") -> dict[str, str]: ...

    # Action API Commons — imageinfo + extmetadata
    def fetch_commons_images(self, qid) -> list[CommonsImage]: ...

    # Wikimedia REST API v1 — /page/summary/{title}
    def fetch_wikipedia_summary(self, qid, lang="fr") -> WikiSummary | None: ...

    # Pipeline complet
    def enrich_entity(self, entity_id) -> EnrichmentResult: ...
```

**APIs utilisées par méthode :**

| Méthode | API | Endpoint |
|---|---|---|
| `resolve_wikidata` | Action API | `wikidata.org/w/api.php` · `wbsearchentities` |
| `fetch_biographical_data` | Wikibase REST v1 | `wikidata.org/w/rest.php/wikibase/v1/entities/items/{id}` |
| `resolve_labels_batch` | Wikibase REST v1 | `wikidata.org/w/rest.php/wikibase/v1/entities/items?ids=` |
| `fetch_commons_images` | Action API | `commons.wikimedia.org/w/api.php` · `imageinfo` |
| `fetch_wikipedia_summary` | Wikimedia REST v1 | `fr.wikipedia.org/api/rest_v1/page/summary/{title}` |

**Contraintes d'appel :**
- Rate limit global Wikimedia : 1 req/s en mode séquentiel — utiliser `asyncio` + semaphore pour paralléliser prudemment (max 5 requêtes simultanées)
- User-Agent obligatoire sur toutes les requêtes : `FACE.ai/1.0 (contact@ok-ia.ch)`
- Réponse `429 Too Many Requests` : respecter le header `Retry-After` avant de relancer
- Batch labels : max 50 Q-numbers par requête REST v1 — découper si nécessaire
- Appelé par le service `worker` Docker, jamais en temps réel depuis l'API

---

### 9.6 Interface — panneau d'enrichissement

Dans `EntityRow` et `GalleryHeader` :

```
[Q] Sam Altman                         ← lien Wikidata si résolu
Chef d'entreprise américain (né 1985)  ← wiki_description
```

Badge d'état :
- `●` vert : résolu automatiquement
- `◌` gris : en attente
- `✕` rouge : non résolu → formulaire de résolution manuelle

Les images Wikimedia affichent le badge `[W] COMMONS` avec la licence.

---

### 9.7 Nouveaux endpoints API

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/entities/{slug}/enrich` | Déclencher l'enrichissement Wikimedia |
| `GET` | `/entities/{slug}/wikidata` | Données Wikidata de l'entité |
| `PATCH` | `/entities/{slug}/wikidata` | Résolution manuelle du Q-number |
| `GET` | `/entities/unresolved` | Liste des entités sans Q-number |


---

## 10. Structure du projet (ancienne version — voir §15)

```
face-ai/
├── backend/
│   ├── config.py
│   ├── database.py          # modèles SQLAlchemy
│   ├── scraper.py           # extraction BeautifulSoup
│   ├── face_processor.py    # MediaPipe + OpenCV
│   ├── api.py               # FastAPI
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── AlphaNav.jsx
│   │   │   ├── EntityList.jsx
│   │   │   ├── GalleryPanel.jsx
│   │   │   ├── FaceCard.jsx
│   │   │   └── PoseFilter.jsx
│   │   ├── hooks/
│   │   │   └── useEntities.js
│   │   └── api/
│   │       └── client.js
│   ├── package.json
│   └── tailwind.config.js
├── static/
│   ├── originals/           # images téléchargées
│   └── aligned/             # images recadrées alignées
├── face_ai.db               # base SQLite
└── docker-compose.yml
```

---

## 12. Direction artistique

### 10.1 Positionnement conceptuel

FACE.ai est simultanément un outil de veille et un objet artistique. Ce double statut n'est pas une contradiction — il est le projet.

En arrachant chaque portrait à son contexte narratif (l'article, l'événement, la légende politique ou économique) pour le soumettre au même protocole géométrique d'alignement, FACE.ai produit involontairement ce que les artistes documentaires construisent délibérément : une archive systématique qui révèle quelque chose sur le pouvoir, la visibilité médiatique, et la répétition du visage comme signe.

**Références artistiques et historiques**

- **Alphonse Bertillon** — fiches anthropométriques judiciaires (1880s) : le visage réduit à ses mesures, classé, archivé. FACE.ai accomplit le même geste sur le corpus médiatique contemporain.
- **Francis Galton** — photographies composites (1880s) : superposition de portraits pour dégager le "type". La lecture auto du Flipbook à faible vitesse produit cet effet composite mentalement.
- **August Sander** — *Menschen des 20. Jahrhunderts* : la série révèle le type social par la répétition du portrait. Ici, le type médiatique.
- **Taryn Simon** — *An American Index of the Hidden and Unfamiliar* : systèmes de collecte automatisée qui révèlent ce que l'œil ordinaire ne perçoit pas.
- **Mishka Henner** — œuvres issues de données publiques et agrégées : la beauté de l'archive brute.

**Sous-titre de l'application**

> *Portrait automatique de l'espace médiatique*

Affiché discrètement sous le logo, en italique, corps très petit.

---

### 10.2 Identité visuelle

#### Palette

Deux registres coexistent et créent une tension intentionnelle. Les deux sont des **bases neutres** — elles accueillent la couleur ambiante extraite des images (voir section 10.4) sans la subir.

**Mode galerie (lumière)** — musée, salle d'archives, papier photo vieilli.

```css
--bg-primary:     #f5f2ee   /* blanc cassé chaud, papier photo */
--bg-secondary:   #ede9e3   /* séparations, colonnes */
--text-primary:   #1a1814   /* quasi-noir, encre */
--text-secondary: #8a8278   /* métadonnées, labels */
--accent:         #c8102e   /* rouge fixe — état actif, alertes */
--border:         #d4cfc8   /* bordures légères */

/* Variables dynamiques — injectées par useAmbientColor */
--ambient-hue:    0          /* teinte dominante extraite, 0–360 */
--ambient-sat:    0%         /* saturation réduite */
```

**Mode Flipbook (obscurité)** — chambre noire, table lumineuse, salle de projection.

```css
--fb-bg:          #080808
--fb-text:        #e8e4de
--fb-meta:        #5a5550
--fb-accent:      #c8102e   /* même rouge — continuité */

/* Variables dynamiques — plus intenses en mode sombre */
--ambient-hue:    0
--ambient-sat:    0%
```

Le rouge `#c8102e` est le seul accent chromatique **fixe**. Il n'est jamais remplacé par la couleur ambiante.

---

### 10.4 Couleur ambiante — l'interface qui respire

#### Principe

Lorsqu'une image est sélectionnée ou affichée en Flipbook, ses couleurs dominantes sont extraites et viennent **teinter subtilement l'interface** — fond, bordures, halos — sans jamais compromettre la lisibilité.

L'effet est celui d'un éclairage ambiant : comme si la lumière de la photo se projetait sur les murs de la salle. L'interface ne change pas de nature — elle se colore légèrement, comme du papier photographique sous une lumière colorée.

#### Extraction des couleurs

Bibliothèque : **`Color Thief`** (JS, côté client).

Processus :
1. Échantillonnage de l'image alignée à basse résolution (50×50px suffisent)
2. Extraction de la **palette dominante** (5 couleurs via quantification k-means)
3. Sélection de la couleur la plus **saturée et non-skin-tone** — on écarte les tons chair (hue 0–30°, saturation > 20%) pour éviter que chaque portrait produise un fond orangé
4. Si aucune couleur non-skin-tone n'est trouvée : repli sur la teinte secondaire la plus saturée
5. Conversion en HSL — seule la **teinte (H)** est conservée. Saturation et luminosité sont normalisées selon le mode

#### Application dans l'interface

Les variables CSS `--ambient-hue` et `--ambient-sat` sont injectées dynamiquement sur `:root` via le hook `useAmbientColor`.

**Mode galerie :**
```css
--bg-primary:  hsl(var(--ambient-hue), calc(var(--ambient-sat) * 0.06), 96%);
--bg-secondary: hsl(var(--ambient-hue), calc(var(--ambient-sat) * 0.08), 92%);
--border:      hsl(var(--ambient-hue), calc(var(--ambient-sat) * 0.12), 85%);

/* Halo autour de l'image active */
box-shadow: 0 0 40px hsl(var(--ambient-hue) 40% 70% / 0.15);
```

**Mode Flipbook :**
```css
/* Fond — gradient radial centré sur l'image */
background: radial-gradient(
  ellipse 80% 60% at 50% 50%,
  hsl(var(--ambient-hue) calc(var(--ambient-sat) * 0.3) 8%),
  #080808 70%
);

/* Halo de l'image — plus prononcé dans l'obscurité */
box-shadow: 0 0 80px hsl(var(--ambient-hue) 50% 40% / 0.25);

/* Barre de métadonnées basse */
background: hsl(var(--ambient-hue) calc(var(--ambient-sat) * 0.2) 10% / 0.9);
```

#### Transition entre images

Les variables CSS transitent avec `600ms ease` — la couleur glisse lentement, jamais brutalement. En Flipbook manuel rapide : réduit à `150ms`. En Flipbook auto lent : les `600ms` créent un fondu chromatique en phase avec le fondu des images — l'atmosphère change comme une respiration.

#### Garanties de lisibilité — contrat non négociable

**1. Saturation plafonnée**
La saturation ambiante appliquée ne dépasse jamais 8% en mode lumière, 30% en mode obscurité.

**2. Luminosité ancrée**
La luminosité des fonds n'est jamais modifiée — seule la teinte varie. `hsl(H, S%, L%)` : H varie, L est fixe. Les ratios de contraste texte/fond restent conformes à WCAG AA (≥ 4.5:1).

**3. Contrôle automatique du contraste**
Le hook calcule le ratio après chaque changement. Si le ratio tombe sous 4.5:1, la saturation ambiante est réduite automatiquement jusqu'à conformité — pouvant descendre à 0% si nécessaire.

```js
function clampForContrast(hue, sat, mode) {
  let s = sat;
  while (s > 0) {
    const bg = hslToHex(hue, s * 0.06, mode === 'light' ? 96 : 8);
    const ratio = getContrastRatio(bg, textColor);
    if (ratio >= 4.5) return s;
    s -= 2;
  }
  return 0; // repli sur neutre si nécessaire
}
```

#### Hook React

```js
// useAmbientColor.js
const { ambientHue, ambientSat, isExtracting } = useAmbientColor(imageUrl, {
  mode: 'light' | 'dark',
  excludeSkinTones: true,
  transitionMs: 600,       // réduit à 150 en Flipbook manuel rapide
  contrastTarget: 4.5
});
// Injecte automatiquement les variables CSS sur :root
```

#### Option utilisateur

Toggle discret dans les préférences : `[ ◐ Couleur ambiante ]` — activé par défaut, désactivable.

---

#### Typographie (révisée — interface écran)

L'identité originale Cormorant Garamond / EB Garamond / Space Mono a été
abandonnée au profit de la lisibilité écran et de la cohérence avec les
interfaces système. La signature "esthétique de musée" reste assurée par
`Space Mono` sur les badges techniques et par les filets fins `0.5px`.

| Usage | Police | Graisse | Remarque |
|---|---|---|---|
| Tout texte UI | **système** (`-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`, `Segoe UI`, `Roboto`…) | 400 / 300 selon contexte | Cohérence OS, rendu net à toute taille |
| Noms d'entités | système | 300 + tracking serré (`-0.01em`) | Présence visuelle légère sans sérif |
| Compteurs, badges, footers | `Space Mono` | 400 / 700 | Données techniques en évidence (esthétique forensique-museum) |

**Échelle utilisateur ajustable** : composant `<FontScaler>` dans le header
expose `A− / 100% / A+`. Plage `0.7 → 1.5`. Persisté en `localStorage`.
Implémenté via la CSS variable `--font-scale` qui multiplie le `font-size`
racine — toutes les classes Tailwind `text-*` en `rem` suivent
automatiquement.

L'export JPG (§11.6) garde les polices Cormorant / EB Garamond / Space
Mono (téléchargées dans `/models/fonts/`) car le médium imprimé/diffusé
mérite une typographie distinctive ; le canvas Pillow n'a pas de
problème de rendu screen.

L'export ne suit donc plus exactement l'identité de l'UI — c'est un
choix : l'écran est un médium fluide (tailles variables, multiplicité
d'OS), l'export est un médium figé qui peut se permettre une signature.

#### Grille et espace

- Colonne entités : étroite (240px), quasi-typographique, dense
- Zone galerie : respire, marges généreuses, images avec espace blanc autour
- Flipbook : image occupe 80% de la hauteur d'écran, centré, le reste disparaît
- Séparateurs : filets fins `0.5px`, pas de blocs colorés

#### Overlay landmarks

Sur chaque image alignée, un overlay optionnel affiche les points de landmarks faciaux détectés — yeux, nez, bouche, contour — en traits très fins, gris clair (`rgba(200,200,200,0.25)`), presque invisibles.

Activé par défaut en mode galerie, désactivable. En Flipbook : désactivé par défaut, activable via touche `L`.

Cet élément ancre FACE.ai dans son territoire à mi-chemin entre l'instrument scientifique et l'œuvre graphique. Il rend visible le protocole — le "comment" de la machine.

#### Animation

Lente et intentionnelle. Rien n'est instantané sauf le Flipbook manuel (l'effet vient de la succession).

- Ouverture galerie : fondu des images, décalé de 30ms par carte (`staggerChildren`)
- Changement d'entité : fondu croisé 200ms
- Flipbook manuel : instantané — `0ms`
- Flipbook auto (0.5–1 fps) : crossfade 400ms — effet composite à la Galton
- Flipbook auto (2–4 fps) : instantané — effet cinématographique
- Overlay landmarks : apparition progressive 600ms

---

### 10.3 Détail signature — l'image composite

À vitesse 0.5 fps en lecture auto, le Flipbook applique un **crossfade long** (800ms) entre deux images alignées consécutives. Pendant la transition, les deux visages se superposent visuellement — effet direct des photographies composites de Galton.

Ce n'est pas un filtre ou un traitement : c'est la mécanique d'affichage qui produit l'effet. Le visage "moyen" de la personne telle qu'elle apparaît dans les médias emerge naturellement.

Option à exposer dans l'UI : `[ ◉ Composite ]` — active le crossfade long indépendamment de la vitesse.

---

## 13. Fonctionnalités avancées

### 11.1 Timeline par entité

Les images d'une entité sont classées chronologiquement par date de publication de l'article source. Disponible comme axe de tri alternatif à côté du tri par pose.

En Flipbook chronologique à vitesse lente, l'effet est biographique : on observe l'évolution visuelle d'une personnalité dans le temps — vieillissement, changement de style, contextes successifs (procès, conférence, arrestation, remise de prix).

Ajout en base de données : `images.article_date DATE` (extrait du scraper).

Visualisation complémentaire : **heatmap d'apparition** (voir 11.4).

---

### 11.2 Détection et masquage des doublons

**Problème** : une même photo de presse est fréquemment republiée par plusieurs sources. Sans déduplication, une entité très médiatisée affiche 30 images dont 20 sont identiques.

**Solution** : calcul d'embeddings faciaux via **FaceNet** (ou DeepFace avec backend `Facenet512`). Deux images sont considérées doublons si la distance cosinus de leurs embeddings est inférieure à un seuil configurable (`DUPLICATE_THRESHOLD = 0.3`).

Ajout en base : `images.embedding BLOB`, `images.is_duplicate BOOLEAN`, `images.duplicate_of INTEGER REFERENCES images(id)`.

Dans l'interface :
- Badge `[= DOUBLON]` sur les images identifiées
- Toggle `[ Masquer les doublons ]` dans le `GalleryHeader`
- Par défaut : doublons masqués en mode comparaison alignée, visibles en mode galerie

---

### 11.3 Score de diversité du corpus

Pour chaque entité, calculer et afficher un **indice de diversité** :

```
diversité = f(nb poses distinctes, nb sources distinctes, plage temporelle, nb images uniques)
```

Affiché dans `EntityRow` sous forme d'une barre discrète ou d'un score `●●●○○`.

Utilité : identifier en un coup d'œil les entités bien couvertes (diversité élevée) versus les entités qui apparaissent toujours dans le même contexte, sous le même angle, depuis la même source.

---

### 11.4 Heatmap d'apparition médiatique

Pour chaque entité sélectionnée : un calendrier de type **GitHub contribution graph** montrant la densité d'apparition dans les articles WUDD.ai semaine par semaine.

Chaque cellule est cliquable — clic sur une semaine → filtre les images de la galerie sur cette période.

Composant : `<ActivityHeatmap entityId={id} />` positionné entre le nom de l'entité et la galerie.

---

### 11.5 Comparaison côte-à-côte — Split Screen

Sélectionner deux entités (ou deux périodes de la même entité) et les afficher en split-screen vertical 50/50, chacun avec son propre filtre de pose et son Flipbook indépendant.

Déclenchement : bouton `[ ⊞ Comparer ]` dans le header, puis sélection de la seconde entité dans un drawer latéral.

Les deux Flipbooks peuvent être **synchronisés** : même index courant, navigation simultanée — touche `←` `→` avance les deux en parallèle.

Cas d'usage : comparer l'évolution visuelle de deux rivaux politiques ou technologiques couverts sur la même période.

---

### 11.6 Export fiche personnalité

Générer une **planche composite** exportable au format **JPG** (révision : PDF abandonné, format unique image suffit pour l'usage de veille interne).

- **Format** : JPG quality 92, largeur fixe ~1200 px, hauteur calculée selon le nombre d'images
- **Contenu** :
  - En-tête : nom en `Cormorant Garamond italic` + sous-titre (dates de vie · occupation principale · nationalité, séparés par `·`)
  - Filet horizontal de séparation
  - Grille N×M des meilleures images alignées (uniques, hors `flagged`, triées par date), max 24 images soit 6 lignes × 4 colonnes
  - Pied de page : `FACE.ai · veille interne · {date}` à gauche, nombre de portraits à droite, `Space Mono`
- **Style** : fond `#f8f6f0`, encre `#1a1814`, gris `#8a827c`, filets fins — continuité de l'identité visuelle
- **Endpoint** : `GET /entities/{slug}/export.jpg`, content-type `image/jpeg`, header `Content-Disposition: attachment`

Utilité : dossiers de presse internes, rapports de veille, archives.

Librairie : génération PIL côté backend. Polices téléchargées une fois et cachées dans `/models/fonts/`.

---

### 11.7 Correction manuelle association image ↔ entité

Une image de groupe ou mal captionnée peut être associée à la mauvaise entité par le scraper. Interface de correction :

- Mode `[ ✎ Éditer ]` sur chaque `FaceCard`
- Permet de : réassigner à une autre entité, marquer comme "non pertinent", confirmer l'association
- Statut stocké : `images.association_status ENUM('auto', 'confirmed', 'rejected', 'reassigned')`

---

---

## 14. Serveur MCP — Interface pour agents IA

### 12.1 Positionnement

FACE.ai expose un **serveur MCP** (Model Context Protocol) permettant à un agent IA — Claude, ou tout modèle compatible — d'interroger la base de données de portraits, d'analyser des entités, et de produire des synthèses journalistiques ou biographiques enrichies par le corpus visuel.

Le MCP transforme FACE.ai d'un outil de consultation en un **outil de raisonnement** : l'IA peut naviguer dans l'archive, comparer des entités, détecter des patterns de visibilité médiatique, et formuler des analyses que l'interface seule ne produit pas.

### 12.2 Architecture MCP

```
Claude (ou agent compatible MCP)
        │
        │  stdio / SSE / HTTP
        ▼
  face_ai_mcp_server.py
  (mcp SDK Python)
        │
        ▼
  face_ai DB + API interne
```

Implémentation : bibliothèque officielle **`mcp`** (Anthropic, Python).  
Transport supporté : `stdio` (Claude Desktop / Claude Code), `SSE` (intégration web).

### 12.3 Outils MCP exposés

#### `search_entities`
Recherche d'entités par nom, partiel ou exact.

```python
@mcp.tool()
def search_entities(query: str, limit: int = 10) -> list[dict]:
    """
    Recherche des entités PERSON dans la base FACE.ai.
    Retourne : id, name, slug, article_count, image_count, diversity_score.
    """
```

**Exemple d'usage Claude** :
> *"Quelles personnalités liées à l'IA apparaissent le plus dans FACE.ai ?"*

---

#### `get_entity_profile`
Profil complet d'une entité avec statistiques visuelles.

```python
@mcp.tool()
def get_entity_profile(slug: str) -> dict:
    """
    Retourne le profil complet d'une entité :
    - Métadonnées (nom, nb articles, première apparition)
    - Distribution des poses (% face / profil G. / profil D.)
    - Score de diversité
    - Plage temporelle de couverture
    - Doublons détectés
    - Sources médias distinctes
    """
```

---

#### `get_entity_images`
Liste des images d'une entité avec métadonnées et analyse faciale.

```python
@mcp.tool()
def get_entity_images(
    slug: str,
    pose: str | None = None,        # 'front' | 'left' | 'right'
    unique_only: bool = True,        # exclure les doublons
    date_from: str | None = None,    # YYYY-MM-DD
    date_to: str | None = None,
    limit: int = 20
) -> list[dict]:
    """
    Retourne les images d'une entité filtrées.
    Chaque image inclut : source_url, aligned_url, caption,
    copyright, article_title, article_url, article_date, pose, confidence.
    """
```

---

#### `compare_entities`
Comparaison statistique de deux entités.

```python
@mcp.tool()
def compare_entities(slug_a: str, slug_b: str) -> dict:
    """
    Compare deux entités sur :
    - Volume de couverture (nb images, nb articles)
    - Distribution temporelle (pics de visibilité)
    - Diversité de pose et de sources
    - Contextes d'apparition (titres d'articles)
    Utile pour : rivalités, cooccurrences, évolutions parallèles.
    """
```

**Exemple d'usage Claude** :
> *"Compare la couverture visuelle de Sam Altman et Elon Musk depuis janvier 2025."*

---

#### `get_media_timeline`
Chronologie d'apparition d'une entité.

```python
@mcp.tool()
def get_media_timeline(
    slug: str,
    granularity: str = "week"    # 'day' | 'week' | 'month'
) -> list[dict]:
    """
    Retourne la densité d'apparition par période.
    Chaque entrée : date, image_count, article_count, dominant_source.
    """
```

---

#### `get_corpus_stats`
Vue d'ensemble du corpus FACE.ai.

```python
@mcp.tool()
def get_corpus_stats() -> dict:
    """
    Statistiques globales :
    - Nb total entités, images, articles couverts
    - Top 10 entités par volume
    - Répartition par pose
    - Taux d'alignement réussi
    - Dernière mise à jour
    """
```

---

#### `analyze_visibility_pattern`
Analyse sémantique de la visibilité médiatique d'une entité — outil de haut niveau destiné à Claude.

```python
@mcp.tool()
def analyze_visibility_pattern(slug: str) -> dict:
    """
    Agrège toutes les données disponibles sur une entité
    (timeline, poses, sources, titres d'articles, doublons)
    en un objet structuré prêt pour l'analyse par un LLM.
    Ne fait pas l'analyse — fournit le contexte factuel complet.
    """
```

C'est l'outil pivot : Claude appelle `analyze_visibility_pattern`, reçoit le contexte factuel structuré, et produit ensuite sa propre analyse narrative.

---

### 12.4 Ressources MCP exposées

En complément des outils, le serveur expose des **ressources** consultables directement par Claude.

```
face://entities                          — liste complète des entités
face://entities/{slug}                   — profil d'une entité
face://entities/{slug}/images            — images d'une entité
face://entities/{slug}/timeline          — timeline d'une entité
face://stats                             — statistiques globales
```

### 12.5 Prompts MCP pré-configurés

Des prompts réutilisables sont enregistrés dans le serveur MCP pour des cas d'usage fréquents :

```python
@mcp.prompt()
def portrait_editorial(slug: str) -> str:
    """
    Génère un prompt structuré pour que Claude produise
    un portrait éditorial d'une personnalité à partir
    des données FACE.ai : visibilité, contextes, évolution.
    """

@mcp.prompt()
def media_comparison(slug_a: str, slug_b: str) -> str:
    """
    Prompt de comparaison éditoriale entre deux personnalités.
    """

@mcp.prompt()
def visibility_anomaly_report(slug: str) -> str:
    """
    Demande à Claude d'identifier les pics ou creux anormaux
    de visibilité médiatique et d'en proposer une explication.
    """
```

### 12.6 Configuration Claude Desktop / Claude Code

Fichier `claude_desktop_config.json` à distribuer avec FACE.ai :

```json
{
  "mcpServers": {
    "face-ai": {
      "command": "python",
      "args": ["/chemin/vers/face-ai/backend/face_ai_mcp_server.py"],
      "env": {
        "FACE_AI_DB": "/chemin/vers/face_ai.db",
        "FACE_AI_STATIC": "/chemin/vers/static"
      }
    }
  }
}
```

Une fois connecté, Claude peut interroger FACE.ai naturellement dans toute conversation :
> *"Montre-moi les entités les plus photographiées de face dans FACE.ai."*  
> *"Génère un portrait éditorial de Demis Hassabis basé sur sa couverture médiatique."*  
> *"Y a-t-il eu un pic de visibilité inhabituel pour Sam Altman en novembre 2024 ?"*

### 12.7 Fichier d'implémentation

```
backend/
└── face_ai_mcp_server.py    # serveur MCP complet
    ├── Outils : search_entities, get_entity_profile,
    │            get_entity_images, compare_entities,
    │            get_media_timeline, get_corpus_stats,
    │            analyze_visibility_pattern
    ├── Ressources : face://…
    └── Prompts : portrait_editorial, media_comparison,
                  visibility_anomaly_report
```

Dépendance à ajouter dans `requirements.txt` :
```
mcp>=1.0.0
```

---

## 15. Structure du projet (mise à jour)

```
face-ai/
├── backend/
│   ├── config.py
│   ├── database.py              # modèles SQLAlchemy (entités, images, face_analysis)
│   ├── scraper.py               # extraction BeautifulSoup + association entités
│   ├── face_processor.py        # MediaPipe + OpenCV + alignement
│   ├── embeddings.py            # FaceNet / DeepFace — doublons + diversité
│   ├── export.py                # génération planches PIL
│   ├── api.py                   # FastAPI
│   ├── face_ai_mcp_server.py    # serveur MCP (outils, ressources, prompts)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── AlphaNav.jsx
│   │   │   ├── EntityList.jsx
│   │   │   ├── EntityRow.jsx          # nom + score diversité
│   │   │   ├── GalleryPanel.jsx
│   │   │   ├── GalleryHeader.jsx
│   │   │   ├── FaceCard.jsx
│   │   │   ├── PoseFilter.jsx
│   │   │   ├── FlipbookOverlay.jsx
│   │   │   ├── ActivityHeatmap.jsx    # timeline GitHub-style
│   │   │   ├── SplitScreen.jsx        # comparaison côte-à-côte
│   │   │   └── LandmarkOverlay.jsx    # overlay points faciaux
│   │   ├── hooks/
│   │   │   ├── useEntities.js
│   │   │   ├── useFlipbook.js
│   │   │   ├── useAmbientColor.js     # extraction couleur + injection CSS vars
│   │   │   └── useSplitScreen.js
│   │   ├── api/
│   │   │   └── client.js
│   │   └── styles/
│   │       └── tokens.css             # variables CSS palette + typo
│   ├── package.json
│   └── tailwind.config.js
├── static/
│   ├── originals/
│   ├── aligned/
│   └── exports/                       # planches générées
├── data/
│   └── face_ai.db                     # volume persistant monté
├── docker/
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── nginx.conf
├── docker-compose.yml
└── docker-compose.prod.yml
```

---

## 16. Infrastructure Docker

### 13.1 Principes

FACE.ai est conçu **Docker-first** : aucun composant ne suppose d'installation locale autre que Docker et Docker Compose. L'ensemble du stack — API, traitement facial, frontend compilé, proxy — tourne dans des conteneurs isolés et communicants.

Compatibilité cible : Docker Engine 24+, Compose v2. Déployable sur Mac mini M4 Pro (ARM64) et x86_64.

### 13.2 Services

| Service | Image base | Rôle | Port interne |
|---|---|---|---|
| `api` | `python:3.12-slim` | FastAPI + traitement facial | 8000 |
| `mcp` | `python:3.12-slim` | Serveur MCP (stdio/SSE) | 8001 |
| `frontend` | `node:20-alpine` (build) → `nginx:alpine` (serve) | React compilé | 80 |
| `nginx` | `nginx:alpine` | Reverse proxy, routing, HTTPS | 443 / 80 |
| `worker` | `python:3.12-slim` | Tâches longues : embeddings, scraping batch | — |

### 13.3 `docker-compose.yml` (développement)

```yaml
services:

  api:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    volumes:
      - ./backend:/app
      - ./static:/static
      - ./data:/data
    environment:
      - FACE_AI_DB=/data/face_ai.db
      - FACE_AI_STATIC=/static
      - WUDD_API_URL=${WUDD_API_URL}
      - ENV=development
    ports:
      - "8000:8000"
    command: uvicorn api:app --host 0.0.0.0 --port 8000 --reload
    depends_on:
      - worker

  mcp:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    volumes:
      - ./backend:/app
      - ./data:/data
      - ./static:/static
    environment:
      - FACE_AI_DB=/data/face_ai.db
      - FACE_AI_STATIC=/static
    ports:
      - "8001:8001"
    command: python face_ai_mcp_server.py --transport sse --port 8001

  worker:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    volumes:
      - ./backend:/app
      - ./static:/static
      - ./data:/data
    environment:
      - FACE_AI_DB=/data/face_ai.db
      - FACE_AI_STATIC=/static
    command: python worker.py

  frontend:
    build:
      context: ./frontend
      dockerfile: ../docker/frontend.Dockerfile
      target: dev
    volumes:
      - ./frontend/src:/app/src
    ports:
      - "5173:5173"
    environment:
      - VITE_API_URL=http://localhost:8000
    command: npm run dev

volumes:
  face_ai_data:
```

### 13.4 `docker-compose.prod.yml` (production)

Surcharge pour le déploiement sur Mac mini / serveur :

```yaml
services:

  api:
    command: uvicorn api:app --host 0.0.0.0 --port 8000 --workers 2
    environment:
      - ENV=production
    restart: unless-stopped

  mcp:
    restart: unless-stopped

  worker:
    restart: unless-stopped

  frontend:
    build:
      target: prod           # étape nginx du multi-stage build
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - api
      - frontend
    restart: unless-stopped
```

Lancement prod :
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 13.5 `docker/backend.Dockerfile`

```dockerfile
FROM python:3.12-slim

# Dépendances système pour MediaPipe + OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
```

### 13.6 `docker/frontend.Dockerfile` (multi-stage)

```dockerfile
# — Étape build —
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# — Étape dev —
FROM node:20-alpine AS dev
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
EXPOSE 5173

# — Étape prod (nginx) —
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
```

### 13.7 `docker/nginx.conf`

```nginx
server {
    listen 80;

    # Frontend React
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # API FastAPI
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Serveur MCP (SSE)
    location /mcp/ {
        proxy_pass http://mcp:8001/;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;          # requis pour SSE
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # Fichiers statiques (images)
    location /static/ {
        alias /static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 13.8 Volumes persistants

| Volume | Chemin hôte | Contenu |
|---|---|---|
| `./data` | `/data` dans les conteneurs | `face_ai.db` — base SQLite |
| `./static/originals` | `/static/originals` | Images téléchargées originales |
| `./static/aligned` | `/static/aligned` | Images recadrées alignées |
| `./static/exports` | `/static/exports` | Planches exportées |

Tous les volumes sont montés en bind mount — pas de volumes Docker anonymes — pour faciliter les sauvegardes et l'accès direct depuis l'hôte.

---

### 13.9 Sécurité réseau — LAN / Tailscale

FACE.ai est conçu pour fonctionner exclusivement sur **réseau local ou Tailscale**. Le réseau constitue le périmètre de sécurité — aucune authentification applicative n'est implémentée.

#### Principe

- Aucun port n'est exposé sur l'interface publique (`0.0.0.0`)
- Tous les ports Docker sont liés à `127.0.0.1` (localhost) ou à l'interface Tailscale (`100.x.x.x`)
- L'accès depuis l'extérieur se fait exclusivement via le VPN Tailscale

#### Binding des ports dans `docker-compose.prod.yml`

```yaml
services:
  nginx:
    ports:
      - "127.0.0.1:80:80"      # localhost uniquement
      # ou via Tailscale :
      # - "100.x.x.x:80:80"    # adresse Tailscale du Mac mini
```

En développement, les ports sont liés à `127.0.0.1` par défaut dans `docker-compose.yml`.

#### Accès Tailscale

Sur le Mac mini M4 Pro (serveur) :
```bash
# Vérifier l'adresse Tailscale
tailscale ip -4
# → 100.x.x.x

# L'app est accessible depuis tous les appareils du réseau Tailscale à :
# http://100.x.x.x  (interface)
# http://100.x.x.x:8001/sse  (MCP)
```

Sur les clients (MacBook, iPhone, etc.) : Tailscale actif suffit.

#### Configuration MCP via Tailscale

```json
{
  "mcpServers": {
    "face-ai": {
      "type": "sse",
      "url": "http://100.x.x.x:8001/sse"
    }
  }
}
```

#### Ce qui n'est pas nécessaire

- Pas de JWT, pas de session, pas de login
- Pas de HTTPS (Tailscale chiffre le tunnel)
- Pas de CORS restrictif (tout vient du même réseau de confiance)
- Pas de rate limiting applicatif

#### Ce qui reste vigilant

- Ne jamais exposer les ports sur `0.0.0.0` en production
- Le fichier `.env` contenant `WUDD_API_URL` et autres variables ne doit pas être commité
- Ajouter `.env` et `data/` dans `.gitignore`

---

### 13.10 Configuration MCP pour Claude Desktop (Docker)

Quand le serveur MCP tourne en SSE dans Docker, la configuration Claude Desktop devient :

```json
{
  "mcpServers": {
    "face-ai": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

Pour Claude Code en mode stdio (accès direct au conteneur) :

```json
{
  "mcpServers": {
    "face-ai": {
      "command": "docker",
      "args": ["exec", "-i", "face-ai-mcp-1",
               "python", "face_ai_mcp_server.py", "--transport", "stdio"]
    }
  }
}
```

### 13.10 Commandes courantes

```bash
# Démarrage dev
docker compose up

# Build et démarrage prod
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Logs en temps réel
docker compose logs -f api

# Lancer le scraping manuel d'un article
docker compose exec api python scraper.py --url "https://wudd.ai/articles/…"

# Relancer l'analyse faciale sur toutes les images non traitées
docker compose exec worker python face_processor.py --reprocess-pending

# Sauvegarde de la base
cp ./data/face_ai.db ./data/face_ai.db.bak
```

---

## 17. Plan de tests

### 17.1 Principes

- Framework Python : **pytest** + **pytest-asyncio** pour les coroutines
- Framework React : **Vitest** + **React Testing Library**
- Mocks Wikimedia : fichiers JSON de fixtures — jamais d'appels réseau réels en CI
- Couverture cible : 80% sur le backend (critique), 60% sur le frontend (composants clés)
- Exécution : `docker compose exec api pytest` — les tests tournent dans le conteneur

---

### 17.2 Tests unitaires — backend

#### `face_processor.py` — cœur du système

```python
# test_face_processor.py

def test_pose_classification_front():
    # yaw = -3° → 'front'
    assert classify_pose(yaw=-3.0) == "front"

def test_pose_classification_left():
    # yaw = -25° → 'left'
    assert classify_pose(yaw=-25.0) == "left"

def test_pose_classification_right():
    assert classify_pose(yaw=18.0) == "right"

def test_pose_classification_boundary():
    # exactement ±15° → 'left' ou 'right', pas 'front'
    assert classify_pose(yaw=-15.0) == "left"
    assert classify_pose(yaw=15.0) == "right"

def test_alignment_output_size():
    # L'image alignée doit toujours être CROP_SIZE × CROP_SIZE
    img = load_test_image("fixtures/portrait_front.jpg")
    aligned = align_face(img, landmarks=mock_landmarks())
    assert aligned.size == (CROP_SIZE, CROP_SIZE)

def test_alignment_eye_distance():
    # L'écart inter-oculaire normalisé doit être ≈ EYE_DISTANCE_TARGET ± 2px
    img = load_test_image("fixtures/portrait_front.jpg")
    aligned, meta = align_face_with_meta(img, mock_landmarks())
    assert abs(meta["eye_distance_px"] - EYE_DISTANCE_TARGET) <= 2

def test_no_face_returns_none():
    img = load_test_image("fixtures/landscape_no_face.jpg")
    result = detect_face(img)
    assert result is None

def test_confidence_threshold():
    # Images sous le seuil ne doivent pas être alignées
    result = process_image("fixtures/blurry_portrait.jpg", min_confidence=0.6)
    assert result.analysis_status == "no_face"
```

#### `wikimedia_enricher.py` — avec fixtures JSON

```python
# test_wikimedia_enricher.py

@pytest.fixture
def mock_wikidata_search(requests_mock):
    with open("fixtures/wikidata_search_altman.json") as f:
        requests_mock.get(
            "https://www.wikidata.org/w/api.php",
            json=json.load(f)
        )

def test_resolve_known_entity(mock_wikidata_search):
    match = enricher.resolve_wikidata("Sam Altman", aliases=["Sam Altman"])
    assert match.qid == "Q7251"
    assert match.score >= 0.8

def test_resolve_ambiguous_returns_human():
    # "Macron" → doit retourner Q22686 (Emmanuel Macron, humain)
    # et non Q3038437 (Macron, marque)
    match = enricher.resolve_wikidata("Macron", aliases=["Macron"])
    assert match.qid == "Q22686"

def test_resolve_unknown_returns_unresolved():
    match = enricher.resolve_wikidata("Jean Dupont XYZ123", aliases=[])
    assert match is None or match.score < 0.8

def test_biographical_data_parses_birth_date(mock_wikidata_rest):
    data = enricher.fetch_biographical_data("Q7251")
    assert data.birth_date == date(1985, 4, 22)
    assert data.death_date is None

def test_biographical_data_deceased(mock_wikidata_rest_deceased):
    data = enricher.fetch_biographical_data("Q1339")  # Bach
    assert data.death_date == date(1750, 7, 28)
    assert data.age_at_death == 65

def test_labels_batch_fr(mock_wikidata_labels):
    labels = enricher.resolve_labels_batch(["Q30", "Q142"], lang="fr")
    assert labels["Q30"] == "États-Unis"
    assert labels["Q142"] == "France"

def test_labels_batch_fallback_en(mock_wikidata_labels_no_fr):
    # Si label FR absent → fallback EN
    labels = enricher.resolve_labels_batch(["Q999999"], lang="fr")
    assert labels["Q999999"] != ""  # pas vide, même sans FR

def test_commons_images_filters_skin_tones(mock_commons_api):
    images = enricher.fetch_commons_images("Q7251")
    # Aucune image ne doit avoir mime autre que jpeg/png
    assert all(img.mime in ["image/jpeg", "image/png"] for img in images)
    # Aucune image ne doit contenir "logo" dans le titre
    assert not any("logo" in img.filename.lower() for img in images)

def test_wikipedia_summary_fr(mock_wikipedia_api):
    summary = enricher.fetch_wikipedia_summary("Q7251", lang="fr")
    assert summary.extract != ""
    assert summary.url.startswith("https://fr.wikipedia.org")

def test_wikipedia_summary_fallback_en(mock_wikipedia_no_fr):
    summary = enricher.fetch_wikipedia_summary("Q7251", lang="fr")
    assert summary is not None  # fallback EN retourné
    assert "en.wikipedia.org" in summary.url
```

#### `scraper.py`

```python
def test_extract_images_from_html():
    html = open("fixtures/wudd_article.html").read()
    images = extract_images(html, base_url="https://wudd.ai")
    assert len(images) > 0
    assert all(img.source_url.startswith("http") for img in images)

def test_associate_image_to_entity():
    # Caption "Sam Altman lors du forum" → associé à "Sam Altman"
    img = ImageCandidate(caption="Sam Altman lors du forum de Davos")
    entity = associate_to_entity(img, entities=["Sam Altman", "Elon Musk"])
    assert entity == "Sam Altman"

def test_scraper_timeout(requests_mock):
    requests_mock.get("https://example.com/image.jpg", exc=Timeout)
    result = download_image("https://example.com/image.jpg")
    assert result.scrape_status == "failed"
    assert result.http_status is None

def test_scraper_large_image_rejected(requests_mock):
    # Image > 5 Mo → rejetée
    requests_mock.get("https://example.com/huge.jpg",
                      content=b"x" * (5 * 1024 * 1024 + 1))
    result = download_image("https://example.com/huge.jpg")
    assert result.scrape_status == "failed"
```

---

### 17.3 Tests d'intégration — API FastAPI

```python
# test_api.py — avec TestClient FastAPI et DB SQLite in-memory

@pytest.fixture
def client():
    app.dependency_overrides[get_db] = get_test_db
    return TestClient(app)

def test_get_entities_empty(client):
    r = client.get("/entities")
    assert r.status_code == 200
    assert r.json()["entities"] == []

def test_get_entities_with_data(client, seed_entities):
    r = client.get("/entities")
    assert len(r.json()["entities"]) == 3

def test_get_entity_by_slug(client, seed_entities):
    r = client.get("/entities/sam-altman")
    assert r.status_code == 200
    assert r.json()["name"] == "Altman, Sam"

def test_get_entity_not_found(client):
    r = client.get("/entities/inconnu-xyz")
    assert r.status_code == 404

def test_get_images_filtered_by_pose(client, seed_images):
    r = client.get("/entities/sam-altman/images?pose=front")
    images = r.json()["images"]
    assert all(img["face"]["pose"] == "front" for img in images)

def test_get_images_excludes_duplicates(client, seed_images_with_duplicates):
    r = client.get("/entities/sam-altman/images?unique=true")
    assert all(not img["is_duplicate"] for img in r.json()["images"])

def test_scrape_endpoint_queues_job(client, mock_worker):
    r = client.post("/scrape", json={
        "article_url": "https://wudd.ai/articles/test",
        "article_title": "Test",
        "entities": [{"name": "Sam Altman", "type": "PERSON"}]
    })
    assert r.status_code == 202
    assert "job_id" in r.json()

def test_queue_status(client):
    r = client.get("/queue")
    assert "pending" in r.json()
    assert "done" in r.json()
    assert "failed" in r.json()
```

---

### 17.4 Tests composants — React (Vitest + RTL)

```javascript
// FaceCard.test.jsx
test("affiche le badge pose correct", () => {
  render(<FaceCard image={mockImageFront} />)
  expect(screen.getByText("Face")).toBeInTheDocument()
})

test("affiche le badge COMMONS pour source wikimedia", () => {
  render(<FaceCard image={{ ...mockImage, source_type: "wikimedia" }} />)
  expect(screen.getByText(/COMMONS/)).toBeInTheDocument()
})

test("copier URL appelle clipboard", async () => {
  const mockClipboard = { writeText: vi.fn() }
  Object.assign(navigator, { clipboard: mockClipboard })
  render(<FaceCard image={mockImage} />)
  fireEvent.click(screen.getByTitle("Copier l'URL"))
  expect(mockClipboard.writeText).toHaveBeenCalledWith(mockImage.source_url)
})

// useFlipbook.test.js
test("navigation clavier droite avance l'index", () => {
  const { result } = renderHook(() => useFlipbook(mockImages))
  act(() => result.current.open(0))
  act(() => { fireEvent.keyDown(document, { key: "ArrowRight" }) })
  expect(result.current.current).toBe(1)
})

test("navigation clavier gauche au premier revient au dernier (boucle)", () => {
  const { result } = renderHook(() => useFlipbook(mockImages))
  act(() => result.current.open(0))
  act(() => { fireEvent.keyDown(document, { key: "ArrowLeft" }) })
  expect(result.current.current).toBe(mockImages.length - 1)
})

test("Échap ferme le Flipbook", () => {
  const { result } = renderHook(() => useFlipbook(mockImages))
  act(() => result.current.open(0))
  act(() => { fireEvent.keyDown(document, { key: "Escape" }) })
  expect(result.current.isOpen).toBe(false)
})

// useAmbientColor.test.js
test("saturation ne dépasse jamais 8% en mode lumière", async () => {
  const { result } = renderHook(() =>
    useAmbientColor("fixtures/red_dominant.jpg", { mode: "light" })
  )
  await waitFor(() => !result.current.isExtracting)
  expect(result.current.ambientSat).toBeLessThanOrEqual(8)
})

test("contraste WCAG reste >= 4.5 quelle que soit la couleur", async () => {
  for (const fixture of ["red", "green", "blue", "yellow", "orange"]) {
    const { result } = renderHook(() =>
      useAmbientColor(`fixtures/${fixture}_dominant.jpg`, { mode: "light" })
    )
    await waitFor(() => !result.current.isExtracting)
    const ratio = getContrastRatio(
      hslToHex(result.current.ambientHue, result.current.ambientSat * 0.06, 96),
      "#1a1814"
    )
    expect(ratio).toBeGreaterThanOrEqual(4.5)
  }
})
```

---

### 17.5 Tests de bout en bout — optionnels (P9)

**Outil** : Playwright

Scénarios prioritaires :
- Charger la galerie → sélectionner une entité → vérifier N images affichées
- Ouvrir le Flipbook → naviguer avec les touches clavier → fermer avec Échap
- Filtrer par pose `front` → vérifier que seules les images face sont affichées
- Mode composite → vérifier le crossfade à 0.5 fps

---

### 17.6 Fixtures requises

```
backend/tests/
├── fixtures/
│   ├── portrait_front.jpg          # visage de face, bonne résolution
│   ├── portrait_left.jpg           # profil gauche
│   ├── portrait_right.jpg          # profil droit
│   ├── landscape_no_face.jpg       # image sans visage
│   ├── blurry_portrait.jpg         # visage flou, confidence < 0.6
│   ├── wudd_article.html           # page HTML WUDD.ai de référence
│   ├── wikidata_search_altman.json
│   ├── wikidata_rest_altman.json
│   ├── wikidata_rest_bach.json     # entité décédée
│   ├── wikidata_labels_fr.json
│   ├── wikidata_labels_no_fr.json  # fallback EN
│   ├── commons_imageinfo.json
│   └── wikipedia_summary_fr.json

frontend/src/tests/
└── fixtures/
    ├── mockImage.js
    ├── mockImageFront.js
    ├── mockImages.js               # tableau de 10 images
    └── red_dominant.jpg            # etc. pour useAmbientColor
```

---

### 17.7 Commandes

```bash
# Tests backend (dans le conteneur)
docker compose exec api pytest -v

# Tests backend avec couverture
docker compose exec api pytest --cov=. --cov-report=term-missing

# Tests frontend
docker compose exec frontend npm run test

# Tests frontend avec couverture
docker compose exec frontend npm run coverage

# Tests E2E (optionnel, P9)
docker compose exec frontend npx playwright test
```

---

## 18. Phases de développement

| Phase | Contenu | Priorité |
|---|---|---|
| **P0 — Fondations** | Schéma DB, scraper basique, API `/entities` + `/images` | Must |
| **P1 — Docker** | docker-compose dev + prod, Dockerfiles, nginx, volumes | Must |
| **P2 — Vision** | MediaPipe, classification pose, alignement, overlay landmarks | Must |
| **P3 — Frontend core** | Galerie React, filtres pose, couleur ambiante, identité visuelle | Must |
| **P4 — Flipbook** | Mode défilement rapide, clavier, lecture auto, mode composite | Must |
| **P5 — Intégration** | Connexion WUDD.ai push/pull, sync automatique | Should |
| **P6 — MCP** | Serveur MCP SSE, outils, ressources, prompts, config Claude | Should |
| **P7 — Enrichissement** | Doublons (embeddings), score diversité, timeline, heatmap | Should |
| **P8 — Comparaison** | Split screen synchronisé, export fiche personnalité | Could |
| **P9 — Édition** | Correction manuelle associations, interface de validation | Could |

---

## 19. Points ouverts

**Conformité légale (nLPD CH + RGPD UE)**
- **Régime invoqué** : intérêt légitime (RGPD art. 6.1.f / nLPD art. 31). Conditions et limites détaillées en §1.5.
- **Registre des traitements** : à formaliser. Doit décrire au minimum la finalité (veille interne sur personnalités publiques), les catégories de données (visages + métadonnées biographiques publiques), les sources (articles de presse via WUDD.ai), les destinataires (mono-utilisateur LAN/Tailscale), la durée de conservation, et les mesures techniques (LAN-only, pas d'auth car réseau de confiance, suppression cascade par `_purge_image`).
- **Droit d'opposition / effacement** (RGPD art. 17, 21 / nLPD art. 32) : prévoir un endpoint `DELETE /entities/{slug}` qui purge l'entité, ses images, leurs fichiers et leurs analyses faciales (réutilise la cascade existante). À documenter publiquement même si l'API n'est pas exposée — la doctrine considère qu'un canal de demande doit exister.
- **Durée de conservation** : à définir. Proposition par défaut : tant que l'entité reste référencée par au moins un article WUDD.ai actif. Supprimer si toutes les références amont sont retirées.
- **Logs** : pas de log d'accès individualisé côté utilisateur (mono-utilisateur de toute façon). Logs HTTP standard FastAPI uniquement.
- **Élargissement futur** : tout passage hors du périmètre §1.5 (personnes non-publiques, exposition publique, partage à un tiers, croisement comportemental) requiert une nouvelle analyse d'impact.

**Données & pipeline**
- **Droits d'auteur** : usage interne de veille uniquement. Stocker et afficher systématiquement source et copyright. Aucune redistribution publique.
- **Qualité des images** : seuil de confiance minimal `confidence > 0.6` pour l'affichage en mode aligné.
- **Association image ↔ entité** : lien non univoque pour les photos de groupe. Correction manuelle prévue en P9.
- **Stockage** : politique de rétention à définir (quota, purge, liens morts). Migration SQLite → PostgreSQL si volume > 100k images.
- **Gestion des erreurs scraper** : définir timeout (10s), taille max image (5 Mo), politique de retry (3 tentatives, backoff exponentiel), comportement sur CDN bloquant les bots.
- **Images manquantes** : afficher un placeholder dans l'esthétique FACE.ai (rectangle `--bg-secondary`, icône discrète) — jamais un carré cassé navigateur.

**Entités & Wikidata**
- **Déduplication à l'ingestion** : si WUDD.ai envoie "Macron" et "Emmanuel Macron" dans deux articles distincts, la logique de fusion via `entity_aliases` doit être spécifiée avant implémentation.
- **Fallback langue Wikidata** : si label FR absent → `en` → label brut du Q-number. Formaliser la chaîne dans `wikimedia_enricher.py`.
- **Resynchronisation Wikidata** : deux modes disponibles — rafraîchissement **hebdomadaire automatique** via cron dans le `worker` (vérifier `wikidata_synced_at` > 7 jours) ET **à la demande** via le bouton `[ ↺ Resync ]` dans la fiche entité ou l'endpoint `POST /entities/{slug}/enrich`. Décès et changements d'employeur sont les cas les plus critiques.

**Interface & expérience**
- **Langue** : interface entièrement en français — pas d'i18n pour v1, libellés FR codés en dur.
- **Utilisateurs** : pas de gestion multi-utilisateurs en v1 — application mono-utilisateur sur réseau LAN/Tailscale.
- **Pagination galerie** : défaut 24 images, infinite scroll.
- **Mode lumière / obscurité** : toggle manuel indépendant du mode Flipbook.
- **Accessibilité** : `aria-label` sur les flèches Flipbook et badges ; vérifier le contraste de la couleur ambiante pour les déficiences chromatiques — la fonction `clampForContrast` s'en charge mais à tester explicitement.

**Infrastructure**
- **Performance embeddings** : calcul FaceNet coûteux — lancer via `worker` en tâche de fond, jamais en temps réel.
- **ARM64** : vérifier la compatibilité MediaPipe et dlib à chaque mise à jour de dépendances sur Mac mini M4 Pro.
- **Sécurité** : ne jamais exposer les ports sur `0.0.0.0`. `.env` et `data/` dans `.gitignore`.

---

*Fin du document de spécification v1.1*
