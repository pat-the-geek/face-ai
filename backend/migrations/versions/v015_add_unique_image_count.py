"""ajouter unique_image_count à entities

Le champ image_count compte toutes les images. unique_image_count compte
uniquement celles non marquées is_duplicate par le pipeline pHash. Les deux
sont maintenus par entity_stats.recompute_counts().

Revision ID: v015
Revises: v014
"""
from alembic import op
import sqlalchemy as sa


revision = "v015"
down_revision = "v014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(
            sa.Column("unique_image_count", sa.Integer(), server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("unique_image_count")
