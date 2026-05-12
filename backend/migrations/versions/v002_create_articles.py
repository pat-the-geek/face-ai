"""create articles

Revision ID: v002
Revises: v001
"""
from alembic import op
import sqlalchemy as sa


revision = "v002"
down_revision = "v001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text()),
        sa.Column("published_at", sa.Date()),
        sa.Column(
            "scraped_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("source_domain", sa.Text()),
        sa.Column("wudd_article_id", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("articles")
