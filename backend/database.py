from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func

from config import DATABASE_URL

Base = declarative_base()


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    slug = Column(Text, unique=True, nullable=False)
    first_seen = Column(DateTime)
    article_count = Column(Integer, server_default="0")
    image_count = Column(Integer, server_default="0")
    unique_image_count = Column(Integer, server_default="0")  # v015 — exclut is_duplicate
    diversity_score = Column(Float, server_default="0")
    is_favorite = Column(Boolean, server_default="0")  # v016 — filtrage rapide
    updated_at = Column(DateTime, server_default=func.current_timestamp())

    # Enrichissement Wikidata + Wikipedia (spec §9, ajouté en v012)
    wikidata_qid = Column(Text)
    wikidata_status = Column(Text, server_default="pending")
    wikidata_score = Column(Float)
    wikidata_synced_at = Column(DateTime)
    wiki_summary = Column(Text)
    wiki_url = Column(Text)
    wiki_thumbnail_url = Column(Text)

    # Données biographiques Wikidata (v013, spec §9.3)
    birth_date = Column(Date)
    death_date = Column(Date)
    birth_place = Column(Text)
    death_place = Column(Text)
    nationalities = Column(Text)  # pipe-separated FR labels
    occupations = Column(Text)
    employer = Column(Text)

    # Enrichissement Wikidata factuel étendu (v027, bloc A — intérêt légitime)
    gender = Column(Text)  # P21, label unique ("homme"/"femme"/…)
    political_party = Column(Text)  # P102, pipe-separated
    positions_held = Column(Text)  # P39, pipe-separated
    awards = Column(Text)  # P166, pipe-separated
    notable_works = Column(Text)  # P800, pipe-separated

    # Attributs Wikidata sensibles — RGPD art. 9 (v027, bloc B).
    # DÉCISION PROPRIÉTAIRE 2026-05-30 (Patrick Ostertag) : stockés et exposés
    # normalement, en connaissance du fait que ces catégories sortent du régime
    # d'intérêt légitime art. 6.1.f sur lequel CLAUDE.md §1.5 ancrait le projet.
    # Atténuation déterminante : périmètre limité à des PERSONNALITÉS PUBLIQUES
    # et valeurs EXCLUSIVEMENT publiques reprises telles quelles de Wikidata
    # (aucune inférence, aucune source privée) — cadre proche de l'art. 9.2.e
    # (données manifestement rendues publiques). Revue de conformité art. 9
    # recommandée avant diffusion élargie. Cf. CLAUDE.md pour le détail.
    ethnic_group = Column(Text)  # P172, pipe-separated
    religion = Column(Text)  # P140, pipe-separated
    sexual_orientation = Column(Text)  # P91, label unique
    medical_condition = Column(Text)  # P1050, pipe-separated

    # Position géographique pour la vue carte (v026)
    latitude = Column(Float)
    longitude = Column(Float)
    geo_source = Column(Text)  # 'city' (P625 lieu de naissance) | 'country' (centroïde nationalité)

    # Centroïde d'identité ArcFace (v014, spec §11.2)
    identity_centroid = Column(LargeBinary)  # 2048 octets (512 floats L2-norm)
    identity_count = Column(Integer, server_default="0")

    # Pull WUDD articles par batch (v017, roadmap court terme)
    last_articles_synced_at = Column(DateTime)
    wudd_mentions = Column(Integer, server_default="0")

    aliases = relationship(
        "EntityAlias", back_populates="entity", cascade="all, delete-orphan"
    )
    article_links = relationship("ArticleEntity", back_populates="entity")
    images = relationship("Image", back_populates="entity")


class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id = Column(Integer, primary_key=True)
    entity_id = Column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    alias = Column(Text, nullable=False)
    source = Column(Text)
    created_at = Column(DateTime, server_default=func.current_timestamp())

    entity = relationship("Entity", back_populates="aliases")

    __table_args__ = (UniqueConstraint("entity_id", "alias", name="uq_entity_alias"),)


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    url = Column(Text, unique=True, nullable=False)
    title = Column(Text)
    published_at = Column(Date)
    scraped_at = Column(DateTime, server_default=func.current_timestamp())
    source_domain = Column(Text)
    wudd_article_id = Column(Text)

    entity_links = relationship(
        "ArticleEntity", back_populates="article", cascade="all, delete-orphan"
    )
    images = relationship("Image", back_populates="article")


class ArticleEntity(Base):
    __tablename__ = "article_entities"

    article_id = Column(
        Integer,
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id = Column(
        Integer,
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence = Column(Float, server_default="1.0")

    article = relationship("Article", back_populates="entity_links")
    entity = relationship("Entity", back_populates="article_links")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"))
    entity_id = Column(Integer, ForeignKey("entities.id"))
    source_url = Column(Text, nullable=False)
    local_path = Column(Text)
    aligned_path = Column(Text)
    caption = Column(Text)
    copyright_text = Column(Text)
    alt_text = Column(Text)
    width_px = Column(Integer)
    height_px = Column(Integer)

    scrape_status = Column(Text, server_default="pending")
    http_status = Column(Integer)
    analysis_status = Column(Text, server_default="pending")
    # v023 : trace de provenance pour distinguer corpus WUDD vs hors-corpus
    source_provider = Column(Text, server_default="wudd")
    # v028 : agence/crédit photo résolu depuis copyright_text/source_url/caption
    # (Getty, Reuters, AFP, Keystone, Wikimedia…). NULL = non résolu.
    photo_agency = Column(Text)

    embedding = Column(LargeBinary)
    is_duplicate = Column(Boolean, server_default="0")
    duplicate_of = Column(Integer, ForeignKey("images.id"))

    # Identité ArcFace (v014)
    identity_embedding = Column(LargeBinary)  # 2048 octets (512 floats)
    identity_match_score = Column(Float)  # cosine distance au centroïde de l'entité

    association_status = Column(Text, server_default="auto")
    scraped_at = Column(DateTime, server_default=func.current_timestamp())

    article = relationship("Article", back_populates="images")
    entity = relationship("Entity", back_populates="images")
    face_analysis = relationship(
        "FaceAnalysis",
        back_populates="image",
        uselist=False,
        cascade="all, delete-orphan",
    )


class FaceAnalysis(Base):
    __tablename__ = "face_analysis"

    id = Column(Integer, primary_key=True)
    image_id = Column(
        Integer,
        ForeignKey("images.id", ondelete="CASCADE"),
        unique=True,
    )
    face_detected = Column(Boolean)
    pose = Column(Text)
    confidence = Column(Float)
    yaw = Column(Float)
    pitch = Column(Float)
    roll = Column(Float)
    eye_distance_px = Column(Integer)
    left_eye_x = Column(Float)
    left_eye_y = Column(Float)
    right_eye_x = Column(Float)
    right_eye_y = Column(Float)
    nose_x = Column(Float)
    nose_y = Column(Float)
    # v024 : mesh MediaPipe complet (468 points x,y normalisés 0..1
    # sur l'image alignée). Format float32 little-endian compacté.
    # Nullable : images analysées avant v024 n'ont pas le mesh.
    landmarks_blob = Column(LargeBinary)
    # v025 : nombre de visages détectés dans l'image **source** (via
    # mp.FaceDetection, séparé du mesh d'alignement). >1 = composition
    # multi-personnes — utile pour distinguer flagged "mauvaise identité"
    # vs flagged "image de groupe" dans l'audit P9.
    face_count = Column(Integer)
    # v028 : score de qualité de portrait 0..1 (résolution × frontalité ×
    # netteté). Permet de choisir le meilleur cliché (vignette/export) et de
    # trier l'audit. Calculé dans process_image, recalculable via backfill.
    quality_score = Column(Float)
    # v028 (bloc B1) : âge et genre **estimés depuis le visage** par
    # InsightFace genderage (buffalo_s). Distincts des champs Wikidata
    # factuels de l'entité — ce sont des inférences sur l'image, pas des
    # faits. est_gender ∈ {'M','F'}. Nullable (passe asynchrone).
    est_age = Column(Float)
    est_gender = Column(Text)
    # v028 (bloc B2) : expression dérivée du mesh 478 points (sans modèle
    # supplémentaire). smile_score 0..1 ; expression ∈ {'neutral','smiling'}.
    # Sert notamment le composite Galton (sélection d'expressions homogènes).
    smile_score = Column(Float)
    expression = Column(Text)
    analyzed_at = Column(DateTime, server_default=func.current_timestamp())

    image = relationship("Image", back_populates="face_analysis")

    @property
    def has_full_mesh(self) -> bool:
        """Exposé via `FaceOut.has_full_mesh` pour l'UI : signale si on
        peut afficher le mesh 478 points (sinon fallback aux 3 historiques)."""
        return self.landmarks_blob is not None


class EntityCooccurrence(Base):
    """Arêtes matérialisées du graphe de cooccurrence éditoriale (v029, A5).

    Une ligne = une paire d'entités apparaissant ensemble dans `shared_articles`
    articles distincts. Convention `entity_a_id < entity_b_id` (paire non
    ordonnée stockée une seule fois). Recalculé en masse par
    `cooccurrence.recompute_cooccurrence` (le calcul à la volée par paire reste
    dispo dans `compare_entities`, mais ne scale pas pour un graphe complet).
    Seules les paires `shared_articles >= COOCCURRENCE_MIN_SHARED` sont
    matérialisées pour borner la table.
    """
    __tablename__ = "entity_cooccurrence"

    entity_a_id = Column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    entity_b_id = Column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    shared_articles = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(DateTime, server_default=func.current_timestamp())


class WorkerEvent(Base):
    """Trace des cycles worker pour `/admin/worker-status` (v021).

    API et worker tournent dans 2 process séparés ; un singleton in-memory
    ne suffit pas pour exposer les métriques côté API. Cf. incident
    2026-05-11 et `worker_metrics.py`.
    """
    __tablename__ = "worker_events"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    kind = Column(Text, nullable=False)
    loop_name = Column(Text)
    summary = Column(Text)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
