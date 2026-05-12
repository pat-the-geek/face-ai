"""index entities.name

Revision ID: v008
Revises: v007
"""
from alembic import op


revision = "v008"
down_revision = "v007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_entities_name", "entities", ["name"])


def downgrade() -> None:
    op.drop_index("idx_entities_name", table_name="entities")
