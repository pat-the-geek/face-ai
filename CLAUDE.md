# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: post-MVP mature

Pipeline data complet, 1067 entités, ~500 images, 355 tests, 25 migrations. Tous les phases P0→P9 livrées + ROADMAP horizon court / moyen consommé. Voir [ROADMAP.md](ROADMAP.md) pour ce qui reste, [MIGRATION_POSTGRES.md](MIGRATION_POSTGRES.md) pour le plan de scale.

**Source de vérité** : [FACE-ai-specification.md](FACE-ai-specification.md) reste la doc canonique des choix de conception. Quand le code diverge de la spec, c'est documenté ici (cf. sections plus bas — pHash vs FaceNet, ArcFace centroïde, purge §5.4 silencieuse, etc.).

Quand un nouveau chantier est proposé, lire d'abord la section pertinente de la spec puis ce fichier pour les conventions non-obvious adoptées en pratique. Si la spec est silencieuse ou contradictoire avec ce qui existe, surfacer la question au lieu d'inventer.

## What FACE.ai is

A satellite of WUDD.ai. It scrapes images of `PERSON` entities (NER output) from articles, runs facial detection + landmark-based alignment so portraits of the same person are visually comparable, and exposes the result via a React gallery and an MCP server (so Claude can query the corpus).

The pipeline is linear: **WUDD article → scraper → SQLite → face_processor (MediaPipe + OpenCV) → API/MCP → React frontend**. Wikidata/Wikimedia/Wikipedia enrichment runs asynchronously in a separate `worker` service and is non-blocking.

**Posture, à garder explicite quand le scope est questionné.** FACE.ai est un **outil de veille interne sur corpus maîtrisé** (les articles passés par WUDD.ai), avec une **dimension artistique** assumée (Flipbook, composite Galton, esthétique forensique-musée). Ce n'est pas — et la spec doit refuser d'y dériver — un projet de recherche académique généraliste, un outil de surveillance de masse, ni un SaaS. Le ciblage `PERSON` se limite aux personnalités publiques apparaissant dans la presse, ce qui ancre l'usage dans le régime de l'**intérêt légitime** (RGPD art. 6.1.f, nLPD CH art. 31). Toute évolution qui changerait ce périmètre (élargissement à des inconnus, mise en ligne publique, enrichissement comportemental) doit être posée comme une décision séparée, pas glissée incidemment. Voir spec §1.5.

## Architectural conventions to preserve

These are non-obvious choices the spec makes deliberately — don't undo them when implementing:

- **Docker-first.** Every service runs in a container. No "just install Python locally" shortcuts. See spec §16.
- **LAN/Tailscale only.** No app-level auth, no JWT, no HTTPS termination in the app. Network is the perimeter. Bind ports to `127.0.0.1` or the Tailscale interface — never `0.0.0.0`. See spec §13.9.
- **SQLite + SQLAlchemy + Alembic.** Migrations are versioned in `backend/migrations/` in the order listed in spec §4.9. PostgreSQL is only considered above 100k images.
- **Deux pipelines visuels distincts, ne pas les confondre.** (a) `embeddings.py` + `dedup.py` : pHash 64 bits → détecte les **copies redistribuées** (même image source ré-encodée/recadrée). (b) `identity.py` + `identity_audit.py` : ArcFace 512-dim via InsightFace → vérifie **l'identité de la personne**. Seul ArcFace permet de signaler "cette photo n'est pas la personne annoncée par la caption". Distance cosine au **centroïde d'identité** de l'entité, seuil 0.55 → bascule `images.association_status` entre `auto`/`confirmed`/`flagged`. Le centroïde exclut les `flagged` pour ne pas se polluer. Modèle `buffalo_s` (~120 MB, RetinaFace + ArcFace MFN), téléchargé au premier appel dans `/root/.insightface` (à monter en volume si on veut le persister entre containers).
- **Déduplication par pHash, pas FaceNet.** Spec §11.1 prévoit FaceNet 512-dim mais on utilise un perceptual hash DCT 64 bits (8 octets/image, ~240 KB pour 30k images). Suffit pour le besoin réel ("même image redistribuée") et évite d'embarquer PyTorch. Distance Hamming normalisée, seuil dedup `0.08` (≈ 5 bits sur 64). `embeddings.compute_embedding` et `embedding_distance` forment un contrat stable : bascule future vers ArcFace/FaceNet sans toucher `dedup.py`. Score de diversité = moyenne des distances pairwise entre uniques (0 = tous identiques, ~0.4 = couverture variée).
- **La DB ne contient que des portraits valides.** Spec §5.4. Téléchargement raté, fichier illisible, aucun visage détecté, ou écart inter-oculaire < 25 px → suppression silencieuse (pas d'enregistrement DB, pas de fichier sur disque). Pas de statut `failed` ni `no_face` à conserver. Quand la spec ou l'API mentionne ces statuts, c'est de la rétro-compatibilité historique : ils ne sont plus écrits. Migration de l'existant : `python face_processor.py --purge-invalid`. **Corollaire** : `get_corpus_stats.alignment_rate` est ≈ 100 % par construction (seules les images alignées subsistent en DB). Une valeur < 100 % signale une incohérence DB/disque à investiguer via `purge_invalid()`.
- **`face_count` (v025).** `face_analysis.face_count` trace le nombre de visages détectés dans l'image **source** via `mp.FaceDetection` (modèle séparé de FaceMesh, n'affecte pas l'alignement single-face). Permet de distinguer dans `list_flagged_images` (MCP) et l'UI audit P9 deux causes très différentes : (a) `face_count=1` + distance élevée = vraie erreur d'attribution (priorité audit), (b) `face_count>1` + distance élevée = composition multi-personnes (Trump + Murdoch, Altman entouré, etc.) où l'attribution textuelle reste pertinente mais le crop ArcFace a aligné un visage secondaire. Backfill historique : `python face_processor.py --backfill-face-count`.
- **Échelle cible : 16k entités au démarrage, 20–30k à court terme.** Ne jamais retourner la liste complète depuis l'API ; pagination + filtre `?letter=` obligatoires. Index sur `entities.name` (v008). Recherche full-text via SQLite FTS5 en mode standard, table `entities_fts` maintenue par triggers (v009 → v011 — `content=''` contentless ne supporte pas UPDATE/DELETE en triggers, on utilise le mode standard avec ~3 MB de duplication, négligeable). Tokeniseur `unicode61 remove_diacritics 2` pour gérer les accents FR.
- **SQLite foreign keys ne sont PAS activées** par défaut au connect (pas de `PRAGMA foreign_keys=ON` dans `database.py`). Les déclarations `ondelete="CASCADE"` sur les FK sont donc **purement informatives** côté SQL — il faut gérer les cascades manuellement dans le code Python (cf. `DELETE /entities/{slug}` qui supprime explicitement les `article_entities` avant l'entité). Cascades **ORM** par contre actives via `cascade="all, delete-orphan"` côté `relationship()` (ex. `Entity.aliases`, `Image.face_analysis`). À ne pas confondre.
- **Données de démo : convention de préfixe de caption + script de purge.** Toute injection manuelle d'image pour démonstration d'une feature (typiquement : forger un cas `flagged` pour montrer le workflow audit P9) doit utiliser une caption préfixée `[TEST …]`, `[P9 …]`, `[demo …]` ou `[probe …]`. À la fin du tour, lancer `python cleanup_demo_data.py` (ou `--dry-run` pour vérifier d'abord) pour purger ces résidus. Sans ça, on a déjà eu deux fois "une photo de Macron chez Altman" à signaler. Un cleanup manuel via `DELETE /images/{id}` ou via l'UI `/audit` marche aussi.
- **Compteurs dénormalisés maintenus en un seul endroit.** `entities.image_count` / `unique_image_count` / `article_count` / `diversity_score` sont dénormalisés (calcul à la volée prohibitif sur 16k–30k entités). La source de vérité est `entity_stats.recompute_counts(entity_id)` — appelée automatiquement par `dedup.dedup_entity` (cycle worker) et par `scraper.process_article` (après chaque ingestion). Pour rattraper l'historique : `python entity_stats.py --recompute-all`. Si l'UI affiche des compteurs incohérents, c'est ici qu'il faut chercher.
- **Fusion d'entités doublons.** Module `entity_merge.py`. Auto-merge par QID Wikidata via `merge_loop` (worker, poll 2 min) — quand 2 entités s'enrichissent vers le même QID, fusion automatique de la moins fournie dans la plus fournie. Cas typique attrapé : `Vance, J.D.` + `Vance, JD` → Q28935729. Cas non couverts (QIDs différents mais même personne, ex. `Zuckerberg` Q21491489 vs `Zuckerberg, Mark` Q36215) : merge manuel via `POST /entities/{canonical}/merge?source={duplicate}`. **Important :** `scraper.get_or_create_entity` consulte les aliases avant de créer — sinon le doublon serait recréé au prochain pull WUDD du nom court (qui est devenu un alias après fusion).
- **Garde-fou auto-merge (incident 2026-05-11).** `auto_merge_by_qid` refuse la fusion si (a) le canonical grossirait de plus de `MERGE_MAX_GROWTH_RATIO` (1.5 par défaut), ou (b) un des deux scores Wikidata est < `MERGE_MIN_WIKIDATA_SCORE` (1.0 par défaut, soit label exact). Origine : un QID corrompu (Q7407093 attribué à Musk/Zuckerberg/McCartney en plus d'Altman) a déclenché une fusion massive qui a transformé Altman de 30 → 85 images en silence. Les paires bloquées par le garde-fou ressortent via `GET /admin/merge-conflicts` ; la décision humaine reste possible via le merge manuel (`POST /entities/{slug}/merge`) qui n'est PAS soumis au garde-fou. Si le garde-fou bloque légitimement (vrais homonymes Wikidata avec score 0.7), corriger le QID erroné sur l'entité concernée plutôt que désactiver le garde-fou. **Cause racine du bug d'enrichissement non identifiée** (logs perdus) : le garde-fou est défensif et **le resync Wikidata hebdo reste bloqué** tant qu'on n'a pas la trace exacte. Cf. `config.py` + `entity_merge.py`.
- **Favoris (v016).** `entities.is_favorite BOOLEAN`. Endpoints `PUT/DELETE /entities/{slug}/favorite` (idempotents). `GET /entities?favorites_only=true` et `GET /entities/letters?favorites_only=true` filtrent. UI : étoile sur `EntityRow` + `GalleryHeader` (composant `FavoriteToggle` avec optimistic update), toggle global ★/☆ dans `AlphaNav` qui filtre tout l'écran (liste + barre alphabétique). Pas de sémantique imposée — l'utilisateur décide ce que ça veut dire (entités prioritaires, à surveiller, sujets de veille particuliers).
- **Articles are a separate table** (not denormalized into `images`) — same article often references multiple entities; many-to-many via `article_entities`.
- **Entity name variants** live in `entity_aliases`, not as free-text in `entities.name`. Canonical form is `"Last, First"`; slug is the URL identity.
- **Wikimedia enrichment is async, non-blocking, and rate-limited.** Triggered by the `worker` after entity creation, never inline from the API. User-Agent `FACE.ai/1.0 (contact@ok-ia.ch)` required on every Wikimedia request. Max 5 concurrent, respect `Retry-After` on 429. See spec §9.
- **Intégration WUDD.ai en pull, pas en push.** Deux voies complémentaires :
  - **Liste des PERSON entities** via `GET /api/entities/export?type=PERSON&images=true` → 1 portrait Wikimedia/entité (`wudd_sync.py` + worker `wudd_sync_loop` poll 30 min, endpoint manuel `POST /admin/sync-wudd?limit=N`).
  - **Articles mentionnant une PERSON** via `GET /api/entities/articles?value=X&type=PERSON&max_articles=2000&match_mode=aggregate` → ingestion des images **déjà extraites par WUDD** (champ `Images` avec url/alt/dim), pas de re-scraping HTML. `wudd_articles_sync.py` + endpoint `POST /admin/sync-wudd-articles?person=X&limit=N`. **Param de limite WUDD = `max_articles`** (défaut 300, cap 2000), pas `limit` qui est silencieusement ignoré ; on clamp ensuite côté client.
  - **Pull articles par batch quotidien** (`wudd_articles_batch.py` + worker `wudd_articles_batch_loop`) : sélection prioritaire en 3 passes — (1) favoris à refresh hebdo, (2) top mentions jamais traités, (3) refresh entretien après 30 j. Cap de sécurité : `WUDD_BATCH_ENTITIES_PER_CYCLE` × `60min/WUDD_BATCH_CYCLE_MINUTES` entités/jour (défaut 120). Endpoint manuel `POST /admin/sync-wudd-articles-batch?count=N`. Status `GET /admin/wudd-status`. Marqueur `entities.last_articles_synced_at` pour ne pas retraiter immédiatement, `entities.wudd_mentions` cache local pour le tri.
  - L'audit ArcFace post-ingestion fait son boulot sur ces données réelles : associations texte→image fragiles (caption mentionne X mais l'image est d'Y) → bascule en `flagged` à corriger via UI `/audit`.
  - Modules : `wudd_client.py` (HTTP) + `wudd_sync.py` (orchestration entités) + `wudd_articles_sync.py` (orchestration articles).
  - Config env : `WUDD_BASE_URL` (défaut `http://100.72.122.51:5050`), `WUDD_PULL_LIMIT` (défaut 200).
  - Limites observées côté amont : canonicalisation imparfaite (Trump vs Donald Trump = 2 entités séparées), faux matches Wikimedia (John Ternus → Apple Park) — naturellement gérés par §5.4 (purge no_face) et audit ArcFace.
- **Wikidata: Action API for `wbsearchentities`, REST v1 for everything else.** Don't mix these up — the response shapes differ (REST v1 returns statements as a list of objects).
- **Frontend identity (révisée).** Sans-serif système pour tout l'UI (`-apple-system`, `SF Pro Text`, `Segoe UI`…) — l'identité Cormorant/EB Garamond originale a été abandonnée pour la lisibilité écran et la cohérence OS. Space Mono est conservé pour les badges/compteurs/footers techniques. Échelle utilisateur ajustable via `<FontScaler>` (composant header, persistance localStorage, plage 0.7→1.5, implémenté via CSS var `--font-scale` qui multiplie le `font-size` racine). **L'export JPG (§11.6) garde Cormorant/EB Garamond/Space Mono** — distinction écran (fluide, multi-OS) vs export (figé, médium imprimé/diffusé). Deux color modes (light gallery, dark Flipbook) avec accent fixe `#c8102e`. Ambient color extraite des images, contrast-clamped à WCAG AA 4.5:1. Spec §10 mise à jour.
- **Flipbook navigation is instantaneous in manual mode.** The motion effect comes from succession, not transitions. Auto-mode at 0.5 fps uses an 800ms crossfade for the Galton composite effect — this is a feature, not a bug.
- **Language: French only in v1.** No i18n. UI strings are FR, hardcoded.
- **Fusion par centroïde ArcFace.** `centroid_merge.py` complète `auto_merge_by_qid` pour les **homonymes Wikidata** (QIDs distincts mais même personne). Seuils : auto-merge < `CENTROID_AUTO_DISTANCE=0.20`, suggéré jusqu'à `CENTROID_SUGGEST_DISTANCE=0.45`. Exige `CENTROID_MIN_IMAGES=5` images de chaque côté (les centroïdes calculés sur < 5 images sont bruités — observé : Mark Hamill 1 image matchait Trump à d=0.20). Endpoints `/admin/centroid-merge-candidates` (preview) + `/admin/centroid-auto-merge` (manuel, pas de loop worker).
- **Source provider d'images (v023).** `images.source_provider` distingue `wudd` (corpus maîtrisé, défaut), `ddg` (DuckDuckGo picker via bouton 🦆 DDG), `manual`. UI `/audit` filtre par origine et **remonte les non-wudd en haut de queue** (audit renforcé car pas de cross-check texte↔image disponible hors corpus).
- **DDG picker.** Élargit le périmètre §1.5. Désactivé par défaut, activer via env `FACE_AI_ENABLE_DDG=true` côté API. Workflow : `POST /entities/{slug}/search-ddg` preview (lib `ddgs`), `POST /entities/{slug}/ingest-ddg-image` par image cochée dans la modale. Pas de loop auto, validation manuelle obligatoire. Aucun stockage des résultats avant ingestion explicite.
- **Backup auto + restore.** `backup_loop` quotidien dans le worker, snapshot via `sqlite3 .backup` + gzip + rotation 7 daily / 4 weekly / 12 monthly. UI `/admin` avec bouton `↻ Backup maintenant`, restauration avec **bannière persistante "RESTART REQUIS"** (api+worker doivent recharger l'engine SQLAlchemy). Pre-restore snapshot créé automatiquement pour rollback.
- **Observabilité worker (v021).** Table `worker_events` persiste les cycles (success/error) et événements rares (merge_ok, merge_blocked, not_person_purged). Endpoint `/admin/worker-status` (UI AdminPanel) + endpoint Prometheus `/metrics` (LAN-only, pas d'auth). Rotation 7 jours probabiliste pour ne pas faire grossir la table.
- **Pagination UI progressive (pas de virtualization).** 5 tentatives de virtualization échouées avec notre layout grid `fit-content(380px)` (`@tanstack/react-virtual`, `react-window` v2, `react-virtuoso` v4 × 2). `EntityList` rend 200 entités par défaut, étend par tranche de 200 via IntersectionObserver sur sentinel, bouton "tout afficher" pour bypass. À 1067 entités tenable, au-delà de 5k il faudra refondre le shell layout (cf. ROADMAP).
- **Tri par prénom.** Toggle `↕ prénom` dans AlphaNav (persisté en localStorage via `useSortMode`). `/entities` et `/entities/letters` acceptent `?sort_by=first_name` pour que les buckets alphabétiques suivent le tri (51 entités avec un prénom en T au lieu de 4 noms de famille). EntityRow affiche `Timothée Chalamet` en mode prénom au lieu de `Chalamet, Timothée`.
- **Mode dark.** Hook `useColorMode` avec palette dark fixe (HSL 30° tiède, neutre pour ne pas concurrencer les portraits) qui inhibe `useAmbientColor`. Toggle ☀/🌙 dans le header. Le Flipbook reste sombre hardcodé indépendamment (style intégré).
- **Heatmap timeline d'entité.** `GET /entities/{slug}/timeline` retourne `[{date, count}]` par jour sur 365 jours glissants (articles distincts). Composant `EntityTimeline` rend une grille SVG 53×7 cellules. Clic sur cellule active → filtre date sur la galerie (paramètre `?date_from=&date_to=` du endpoint `/entities/{slug}/images`).
- **MCP : `entity_created_at` ≠ `date_range.from`.** Le tool `get_entity_profile` expose deux champs temporels **distincts** : (a) `entity_created_at` = `entities.first_seen` DB = métadonnée système (insertion FACE.ai, peut être tardive si entité créée par unmerge ou seed récent) ; (b) `date_range.from` = `min(Article.published_at)` = couverture éditoriale réelle. **Ne jamais fallback de l'un à l'autre** — c'est sémantiquement faux et a déjà induit en erreur (rapport test MCP 2026-05-12 : Trump `first_seen=2026-05-11` vs `date_range.from=2026-02-19` n'était pas un bug mais le résultat d'un unmerge récent ; le fallback `entity.first_seen or date_min` masquait la sémantique).

## Commands

Stack opérationnelle. Les services tournent en Docker (ARM64 sur Mac mini M4 Pro).

```bash
# Dev
docker compose up

# Prod (Mac mini M4 Pro / ARM64 target)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Backend tests (pytest, run inside the container)
docker compose exec api pytest -v
docker compose exec api pytest --cov=. --cov-report=term-missing
docker compose exec api pytest tests/test_face_processor.py::test_pose_classification_front

# Frontend tests (Vitest)
docker compose exec frontend npm run test
docker compose exec frontend npm run coverage

# Manual scraping of one WUDD article
docker compose exec api python scraper.py --url "https://wudd.ai/articles/…"

# Reprocess images stuck in 'pending' face analysis
docker compose exec worker python face_processor.py --reprocess-pending

# Backup the SQLite DB
cp ./data/face_ai.db ./data/face_ai.db.bak
```

Coverage targets: backend 80%, frontend 60%. Wikimedia tests must use JSON fixtures — never hit the live API in CI.

## File layout (planned, per spec §15)

```
backend/      # FastAPI + face processing + MCP server (all Python)
frontend/     # React + Vite + Tailwind
docker/       # Dockerfiles, nginx.conf
static/       # originals/, aligned/, exports/  — bind-mounted, not Docker volumes
data/         # face_ai.db  — bind-mounted
```

`.env` and `data/` must stay in `.gitignore`.

## Phases

The spec orders work as P0 (DB + scraper + minimal API) → P1 (Docker) → P2 (vision) → P3 (frontend) → P4 (Flipbook) → P5 (WUDD integration) → P6 (MCP) → P7 (dedup + diversity) → P8 (split screen + export) → P9 (manual correction). When asked to "start implementing," default to P0 unless the user specifies otherwise.

## Open questions to surface, not silently resolve

Spec §19 lists known gaps (entity merge logic on ingestion, Wikidata language fallback chain, image-missing placeholder behavior, scraper retry policy). If you hit one of these mid-task, raise it instead of picking an answer.
