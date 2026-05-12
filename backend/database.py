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
    analyzed_at = Column(DateTime, server_default=func.current_timestamp())

    image = relationship("Image", back_populates="face_analysis")

    @property
    def has_full_mesh(self) -> bool:
        """Exposé via `FaceOut.has_full_mesh` pour l'UI : signale si on
        peut afficher le mesh 478 points (sinon fallback aux 3 historiques)."""
        return self.landmarks_blob is not None


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
