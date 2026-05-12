"""add indexes

Revision ID: v007
Revises: v006
"""
from alembic import op


revision = "v007"
down_revision = "v006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_images_entity", "images", ["entity_id"])
    op.create_index("idx_images_article", "images", ["article_id"])
    op.create_index(
        "idx_images_status", "images", ["scrape_status", "analysis_status"]
    )
    op.create_index("idx_images_duplicate", "images", ["is_duplicate"])
    op.create_index(
        "idx_face_pose", "face_analysis", ["pose", "confidence"]
    )
    op.create_index("idx_articles_domain", "articles", ["source_domain"])
    op.create_index("idx_articles_date", "articles", ["published_at"])
    op.create_index("idx_ae_entity", "article_entities", ["entity_id"])
    op.create_index("idx_aliases_alias", "entity_aliases", ["alias"])


def downgrade() -> None:
    op.drop_index("idx_aliases_alias", table_name="entity_aliases")
    op.drop_index("idx_ae_entity", table_name="article_entities")
    op.drop_index("idx_articles_date", table_name="articles")
    op.drop_index("idx_articles_domain", table_name="articles")
    op.drop_index("idx_face_pose", table_name="face_analysis")
    op.drop_index("idx_images_duplicate", table_name="images")
    op.drop_index("idx_images_status", table_name="images")
    op.drop_index("idx_images_article", table_name="images")
    op.drop_index("idx_images_entity", table_name="images")
