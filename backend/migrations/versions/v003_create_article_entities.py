"""create article_entities

Revision ID: v003
Revises: v002
"""
from alembic import op
import sqlalchemy as sa


revision = "v003"
down_revision = "v002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_entities",
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("confidence", sa.Float(), server_default="1.0"),
    )


def downgrade() -> None:
    op.drop_table("article_entities")
