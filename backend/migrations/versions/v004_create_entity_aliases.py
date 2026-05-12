"""create entity_aliases

Revision ID: v004
Revises: v003
"""
from alembic import op
import sqlalchemy as sa


revision = "v004"
down_revision = "v003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("source", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("entity_id", "alias", name="uq_entity_alias"),
    )


def downgrade() -> None:
    op.drop_table("entity_aliases")
