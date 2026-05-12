"""create images

Revision ID: v005
Revises: v004
"""
from alembic import op
import sqlalchemy as sa


revision = "v005"
down_revision = "v004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entities.id"),
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text()),
        sa.Column("aligned_path", sa.Text()),
        sa.Column("caption", sa.Text()),
        sa.Column("copyright_text", sa.Text()),
        sa.Column("alt_text", sa.Text()),
        sa.Column("width_px", sa.Integer()),
        sa.Column("height_px", sa.Integer()),
        sa.Column("scrape_status", sa.Text(), server_default="pending"),
        sa.Column("http_status", sa.Integer()),
        sa.Column("analysis_status", sa.Text(), server_default="pending"),
        sa.Column("embedding", sa.LargeBinary()),
        sa.Column("is_duplicate", sa.Boolean(), server_default="0"),
        sa.Column(
            "duplicate_of",
            sa.Integer(),
            sa.ForeignKey("images.id"),
        ),
        sa.Column("association_status", sa.Text(), server_default="auto"),
        sa.Column(
            "scraped_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("images")
