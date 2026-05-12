"""ajouter les champs de vérification d'identité ArcFace

Spec §11.2 (nouvelle) : pour chaque image, on calcule un embedding d'identité
512-dim (ArcFace via InsightFace), et on l'agrège par entité en un centroïde.
La distance cosine au centroïde sert à confirmer ou flagger l'association
caption→entité produite par le scraper.

Revision ID: v014
Revises: v013
"""
from alembic import op
import sqlalchemy as sa


revision = "v014"
down_revision = "v013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("identity_embedding", sa.LargeBinary()))
        batch.add_column(sa.Column("identity_match_score", sa.Float()))

    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("identity_centroid", sa.LargeBinary()))
        batch.add_column(sa.Column("identity_count", sa.Integer(), server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("identity_count")
        batch.drop_column("identity_centroid")
    with op.batch_alter_table("images") as batch:
        batch.drop_column("identity_match_score")
        batch.drop_column("identity_embedding")
