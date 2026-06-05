from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field


def _flag(code: str | None) -> str | None:
    """Emoji drapeau depuis un code ISO 3166-1 alpha-2 (None si pas de code)."""
    if not code:
        return None
    from osint_common import country_code_to_flag

    return country_code_to_flag(code)


class FaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pose: str | None
    yaw: float | None
    pitch: float | None
    confidence: float | None
    eye_distance_px: int | None
    # Coords MediaPipe en pixels sur l'image alignée (300×300). Utilisés
    # par `LandmarkOverlay` côté UI (Flipbook, touche L — spec §10).
    left_eye_x: float | None = None
    left_eye_y: float | None = None
    right_eye_x: float | None = None
    right_eye_y: float | None = None
    nose_x: float | None = None
    nose_y: float | None = None
    # v024 : présence du mesh complet (478 points). On expose juste le
    # flag, les coords sont servies via endpoint dédié
    # `GET /images/{id}/landmarks` (payload ~3.7 Ko, à charger à la
    # demande quand l'utilisateur active l'overlay touche L).
    has_full_mesh: bool = False
    # v025 : nombre de visages détectés dans l'image source. Permet à
    # l'UI audit P9 de distinguer flagged "mauvaise identité" vs flagged
    # "composition multi-personnes". Nullable pour les images antérieures
    # à v025 (cf. `face_processor.py --backfill-face-count`).
    face_count: int | None = None
    # v028 : qualité du portrait + attributs estimés depuis le visage.
    # est_age/est_gender sont des **estimations** (B1), expression dérive du
    # mesh (B2). Tous nullables (passes asynchrones / backfill).
    quality_score: float | None = None
    est_age: float | None = None
    est_gender: str | None = None
    expression: str | None = None
    smile_score: float | None = None


class ArticleRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str | None
    url: str
    published_at: date | None
    source_domain: str | None


class ArticleListItem(BaseModel):
    """Entrée dans la liste paginée `GET /articles`.

    Inclut le `entity_count` (dénormalisé à la volée) et le
    `image_count` pour permettre un tri / filtrage côté UI sans
    appeler le détail. Pas d'images embarquées — coût bornable.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    title: str | None
    published_at: date | None
    source_domain: str | None
    entity_count: int = 0
    image_count: int = 0


class ArticleListResponse(BaseModel):
    articles: list[ArticleListItem]
    total: int


class ArticleEntityRef(BaseModel):
    """Entité liée à un article (dans la réponse `GET /articles/{id}`)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    is_favorite: bool = False


class ArticleDetail(BaseModel):
    """Réponse `GET /articles/{id}` — article + entités + images.

    `images: list[ImageOut]` — forward reference (ImageOut défini
    plus bas). `model_rebuild()` après la déclaration de ImageOut.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    title: str | None
    published_at: date | None
    scraped_at: datetime | None = None
    source_domain: str | None
    wudd_article_id: str | None = None
    entities: list[ArticleEntityRef]
    images: list["ImageOut"]


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_url: str
    aligned_url: str | None
    caption: str | None
    copyright: str | None
    scrape_status: str
    analysis_status: str
    is_duplicate: bool
    association_status: str
    identity_match_score: float | None = None
    # v028 (A4) : agence/crédit photo résolu (Getty, Reuters, AFP…). NULL = non résolu.
    photo_agency: str | None = None
    article: ArticleRefOut | None
    face: FaceOut | None


# Résout la forward reference dans ArticleDetail (ImageOut défini ci-dessus)
ArticleDetail.model_rebuild()


class EntityListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    article_count: int
    image_count: int
    unique_image_count: int = 0
    diversity_score: float
    wiki_thumbnail_url: str | None = None
    is_favorite: bool = False
    # Filtre pays (v030). country_flag dérivé du code ISO côté serveur.
    country_code: str | None = None
    country_name: str | None = None

    @computed_field
    @property
    def country_flag(self) -> str | None:
        return _flag(self.country_code)


class EntityMapItem(BaseModel):
    """Entité géolocalisée pour la vue carte (v026). Payload léger : un point."""
    slug: str
    name: str
    latitude: float
    longitude: float
    geo_source: str  # 'city' | 'country'
    thumbnail_url: str | None = None  # portrait corpus aligné, repli wiki_thumbnail_url
    image_count: int = 0
    is_favorite: bool = False
    # Filtre pays (v030) — permet de filtrer/recentrer la carte par pays.
    country_code: str | None = None
    country_name: str | None = None

    @computed_field
    @property
    def country_flag(self) -> str | None:
        return _flag(self.country_code)
    # Description courte pour le tooltip de survol (résumé Wikipédia tronqué,
    # repli sur occupations + nationalité). Tronquée côté serveur pour borner
    # le payload de l'endpoint /entities/map (liste complète des géolocalisés).
    description: str | None = None


class EntityDetail(EntityListItem):
    aliases: list[str]
    first_seen: datetime | None
    updated_at: datetime | None
    wikidata_qid: str | None = None
    wikidata_status: str | None = None
    wiki_summary: str | None = None
    wiki_url: str | None = None
    wiki_thumbnail_url: str | None = None
    birth_date: date | None = None
    death_date: date | None = None
    age_at_death: int | None = None
    # v027/A2 : âge courant calculé depuis birth_date (None si décédé ou inconnu).
    current_age: int | None = None
    birth_place: str | None = None
    death_place: str | None = None
    nationalities: list[str] = []
    occupations: list[str] = []
    employer: str | None = None
    # v027 (bloc A — factuel Wikidata)
    gender: str | None = None
    political_party: list[str] = []
    positions_held: list[str] = []
    awards: list[str] = []
    notable_works: list[str] = []
    # v027 (bloc B — données sensibles RGPD art. 9, décision propriétaire
    # 2026-05-30). Exposées normalement par choix explicite ; cf. CLAUDE.md §1.5.
    ethnic_group: list[str] = []
    religion: list[str] = []
    sexual_orientation: str | None = None
    medical_condition: list[str] = []
    # is_favorite + country_code/name/flag hérités de EntityListItem
    # v030 OSINT — drapeaux compacts pour badges UI ; détail riche via endpoints
    # /entities/{slug}/sanctions, /parliament, /corporate, /offshore + MCP.
    sanctions_status: str | None = None  # 'sanctioned'|'pep'|'clean'|'unknown'
    is_swiss_parliament_member: bool = False
    icij_match: bool = False


class EntitiesResponse(BaseModel):
    entities: list[EntityListItem]
    total: int


class EntityImagesResponse(BaseModel):
    entity: EntityDetail
    images: list[ImageOut]
    total: int
    filtered: int


class SearchResponse(BaseModel):
    results: list[EntityListItem]


# ──────────────────────────────────────────────────────────────────────
# Recherche globale (FTS5 entités + articles + images)
# ──────────────────────────────────────────────────────────────────────


class EntityHit(BaseModel):
    """Résultat de recherche pointant sur une entité."""
    type: Literal["entity"] = "entity"
    slug: str
    name: str
    image_count: int
    article_count: int
    snippet: str | None = None  # extrait HTML autour du match (FTS5 snippet())


class ArticleHit(BaseModel):
    """Résultat pointant sur un article. `entity_slug` = première entité
    associée — permet la navigation depuis le résultat. `entity_name` est
    fournie pour l'affichage."""
    type: Literal["article"] = "article"
    article_id: int
    title: str | None
    url: str
    source_domain: str | None
    published_at: date | None
    entity_slug: str | None = None
    entity_name: str | None = None
    snippet: str | None = None


class ImageHit(BaseModel):
    """Résultat pointant sur une image. Navigation : on renvoie vers
    `/{entity_slug}` qui affichera la galerie de l'entité."""
    type: Literal["image"] = "image"
    image_id: int
    caption: str | None
    aligned_url: str | None
    entity_slug: str | None = None
    entity_name: str | None = None
    snippet: str | None = None


class GlobalSearchResponse(BaseModel):
    """Réponse du `GET /search?q=...`. Chaque liste peut être vide selon
    le scope demandé ou l'absence de hit. `totals` donne le total par
    catégorie (utile pour afficher "3 entités · 12 articles · 0 images")."""
    query: str
    entities: list[EntityHit] = []
    articles: list[ArticleHit] = []
    images: list[ImageHit] = []
    totals: dict[str, int]


PoseFilter = Literal["front", "left", "right"]


class ScrapeEntityIn(BaseModel):
    name: str
    type: str = "PERSON"


class ScrapeRequest(BaseModel):
    article_url: str
    article_title: str | None = None
    entities: list[ScrapeEntityIn]


class ScrapeResultOut(BaseModel):
    article_id: int | None
    status: str
    images_found: int = 0
    images_downloaded: int = 0
    images_ignored: int = 0
    images_failed: int = 0


class AnalyzeResultOut(BaseModel):
    image_id: int
    status: str
    detail: str | None = None


class QueueStatus(BaseModel):
    analysis: dict[str, int]
    scrape: dict[str, int]


class PurgeEntityResult(BaseModel):
    """Réponse au DELETE /entities/{slug} (droit d'opposition, spec §19)."""
    slug: str
    name: str
    images_removed: int
    aliases_removed: int
    article_links_removed: int
    files_removed: int
    orphan_articles: int  # articles devenus sans aucune entité associée


class ImageDeleteResult(BaseModel):
    image_id: int
    files_removed: int
    entity_slug: str


class ImageReassignRequest(BaseModel):
    """Body de PATCH /images/{id} — réassociation manuelle (workflow P9)."""
    target_slug: str


class ImageReassignResult(BaseModel):
    image_id: int
    from_slug: str
    to_slug: str
    new_status: str


class ImageConfirmResult(BaseModel):
    """Réponse au POST /images/{id}/confirm (workflow P9 — sortir une
    image de l'audit en confirmant que l'attribution actuelle est correcte).
    """
    image_id: int
    entity_slug: str
    new_status: str


class ConfirmBatchRequest(BaseModel):
    """Body de POST /images/confirm-batch — validation groupée (workflow P9).

    Cas d'usage : le pipeline crache 30+ flagged d'un coup (ex. composition
    multi-personnes, `face_count>1`) et l'opérateur veut confirmer une
    sélection en un geste plutôt qu'une par une.
    """
    image_ids: list[int]


class ConfirmBatchResult(BaseModel):
    """Réponse au POST /images/confirm-batch.

    `confirmed` = images effectivement passées en `manual` ce coup-ci ;
    `already_manual` = déjà confirmées (noop idempotent) ; `not_found` =
    IDs inconnus (ignorés silencieusement, pas d'erreur globale).
    """
    confirmed: list[int]
    already_manual: list[int]
    not_found: list[int]
    entity_slugs: list[str]


class FlaggedImage(BaseModel):
    """Image dans la queue d'audit. Couvre deux origines :
    - `flagged_by='arcface'` : audit ArcFace automatique (distance > 0.55)
    - `flagged_by='human'` : signalement manuel via `POST /images/{id}/flag`

    `source_provider` distingue les images du corpus WUDD (mécanisme
    d'audit texte↔image disponible) de celles hors corpus (DDG, manual)
    qui ne reposent que sur ArcFace pour la qualification.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    aligned_url: str | None
    caption: str | None
    identity_match_score: float | None
    entity_slug: str
    entity_name: str
    article_title: str | None = None
    flagged_by: Literal["arcface", "human"] = "arcface"
    source_provider: str = "wudd"


class FlaggedListResponse(BaseModel):
    flagged: list[FlaggedImage]
    total: int
