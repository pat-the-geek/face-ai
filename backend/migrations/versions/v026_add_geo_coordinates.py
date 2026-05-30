"""ajouter colonnes géographiques à entities (vue carte)

Pour positionner les entités sur une carte du monde (vue `/carte`), on stocke
des coordonnées résolues depuis Wikidata :
- `latitude` / `longitude` : point de la carte.
- `geo_source` : provenance du point —
  - `'city'`  : coordonnées P625 du lieu de naissance (P19), précises.
  - `'country'`: centroïde statique du pays de nationalité (P27), repli quand
    la ville est inconnue.

Nullable : null = entité non géolocalisable (ni ville ni pays connus) → non
affichée sur la carte (§1.5, on n'invente pas de position). Backfill de
l'existant : `python wikidata.py --backfill-coordinates`. Le worker renseigne
ces champs pour les nouvelles entités via `enrich_entity`.

Revision ID: v026
Revises: v025
"""
from alembic import op
import sqlalchemy as sa


revision = "v026"
down_revision = "v025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("latitude", sa.Float()))
        batch.add_column(sa.Column("longitude", sa.Float()))
        batch.add_column(sa.Column("geo_source", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("geo_source")
        batch.drop_column("longitude")
        batch.drop_column("latitude")
