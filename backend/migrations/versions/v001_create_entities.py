"""create entities

Revision ID: v001
Revises:
"""
from alembic import op
import sqlalchemy as sa


revision = "v001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("first_seen", sa.DateTime()),
        sa.Column("article_count", sa.Integer(), server_default="0"),
        sa.Column("image_count", sa.Integer(), server_default="0"),
        sa.Column("diversity_score", sa.Float(), server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("entities")
