"""Insère un jeu de données minimal pour tester les endpoints.

Usage : docker compose exec api python seed.py
"""
from datetime import date, datetime

from database import (
    Article,
    ArticleEntity,
    Entity,
    EntityAlias,
    FaceAnalysis,
    Image,
    SessionLocal,
)


def run() -> None:
    db = SessionLocal()
    try:
        if db.query(Entity).count() > 0:
            print("seed déjà appliqué — abandon")
            return

        altman = Entity(
            name="Altman, Sam",
            slug="sam-altman",
            first_seen=datetime(2024, 1, 15, 10, 0),
            article_count=2,
            image_count=3,
            diversity_score=0.62,
        )
        musk = Entity(
            name="Musk, Elon",
            slug="elon-musk",
            first_seen=datetime(2024, 1, 8, 9, 0),
            article_count=1,
            image_count=1,
            diversity_score=0.21,
        )
        db.add_all([altman, musk])
        db.flush()

        db.add_all(
            [
                EntityAlias(entity_id=altman.id, alias="Sam Altman", source="lemonde.fr"),
                EntityAlias(entity_id=altman.id, alias="Samuel H. Altman", source="reuters.com"),
                EntityAlias(entity_id=musk.id, alias="Elon Musk", source="lemonde.fr"),
            ]
        )

        article_a = Article(
            url="https://wudd.ai/articles/openai-gpt5",
            title="OpenAI dévoile GPT-5",
            published_at=date(2024, 3, 14),
            source_domain="wudd.ai",
        )
        article_b = Article(
            url="https://wudd.ai/articles/davos-2024",
            title="Davos 2024 : la tech au centre",
            published_at=date(2024, 1, 20),
            source_domain="wudd.ai",
        )
        db.add_all([article_a, article_b])
        db.flush()

        db.add_all(
            [
                ArticleEntity(article_id=article_a.id, entity_id=altman.id, confidence=0.98),
                ArticleEntity(article_id=article_b.id, entity_id=altman.id, confidence=0.92),
                ArticleEntity(article_id=article_b.id, entity_id=musk.id, confidence=0.88),
            ]
        )

        img1 = Image(
            article_id=article_a.id,
            entity_id=altman.id,
            source_url="https://example.com/altman1.jpg",
            local_path="/static/originals/1.jpg",
            aligned_path="/static/aligned/1.jpg",
            caption="Sam Altman lors de l'annonce GPT-5",
            copyright_text="© OpenAI",
            scrape_status="downloaded",
            analysis_status="done",
            association_status="confirmed",
        )
        img2 = Image(
            article_id=article_b.id,
            entity_id=altman.id,
            source_url="https://example.com/altman2.jpg",
            local_path="/static/originals/2.jpg",
            aligned_path="/static/aligned/2.jpg",
            caption="Sam Altman au forum de Davos",
            copyright_text="© World Economic Forum",
            scrape_status="downloaded",
            analysis_status="done",
            association_status="auto",
        )
        img3 = Image(
            article_id=article_b.id,
            entity_id=altman.id,
            source_url="https://example.com/altman2-dup.jpg",
            local_path="/static/originals/3.jpg",
            scrape_status="downloaded",
            analysis_status="done",
            is_duplicate=True,
        )
        img4 = Image(
            article_id=article_b.id,
            entity_id=musk.id,
            source_url="https://example.com/musk1.jpg",
            local_path="/static/originals/4.jpg",
            aligned_path="/static/aligned/4.jpg",
            caption="Elon Musk en marge du forum",
            copyright_text="© Reuters",
            scrape_status="downloaded",
            analysis_status="done",
        )
        db.add_all([img1, img2, img3, img4])
        db.flush()

        img3.duplicate_of = img2.id

        db.add_all(
            [
                FaceAnalysis(
                    image_id=img1.id,
                    face_detected=True,
                    pose="front",
                    confidence=0.97,
                    yaw=-3.2,
                    pitch=1.1,
                    roll=0.4,
                    eye_distance_px=82,
                ),
                FaceAnalysis(
                    image_id=img2.id,
                    face_detected=True,
                    pose="left",
                    confidence=0.91,
                    yaw=-22.0,
                    pitch=0.5,
                    roll=-1.0,
                    eye_distance_px=78,
                ),
                FaceAnalysis(
                    image_id=img3.id,
                    face_detected=True,
                    pose="left",
                    confidence=0.89,
                    yaw=-21.5,
                    pitch=0.6,
                    roll=-1.0,
                    eye_distance_px=78,
                ),
                FaceAnalysis(
                    image_id=img4.id,
                    face_detected=True,
                    pose="right",
                    confidence=0.95,
                    yaw=18.3,
                    pitch=2.2,
                    roll=0.0,
                    eye_distance_px=85,
                ),
            ]
        )

        db.commit()
        print("seed OK : 2 entités, 2 articles, 4 images, 4 analyses faciales")
    finally:
        db.close()


if __name__ == "__main__":
    run()
