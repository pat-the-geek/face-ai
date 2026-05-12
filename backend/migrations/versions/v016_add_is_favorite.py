"""ajouter is_favorite à entities

Spec : système de favoris pour filtrer rapidement les personnes suivies de
près. Un favori est une marque sans sémantique imposée — l'utilisateur
choisit ce que ça veut dire (entités prioritaires, à surveiller, etc.).

Revision ID: v016
Revises: v015
"""
from alembic import op
import sqlalchemy as sa


revision = "v016"
down_revision = "v015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(
            sa.Column("is_favorite", sa.Boolean(), server_default="0")
        )
    # Index partiel ne marche pas en SQLite portable — on indexe la colonne
    # entière. Sur 30k entités avec ~5% favoris, l'index reste très petit.
    op.create_index("idx_entities_favorite", "entities", ["is_favorite"])


def downgrade() -> None:
    op.drop_index("idx_entities_favorite", table_name="entities")
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("is_favorite")
