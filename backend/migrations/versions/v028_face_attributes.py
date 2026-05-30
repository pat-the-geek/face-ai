"""attributs image/visage : crédit photo, qualité, âge/genre/expression estimés

`images.photo_agency` (A4) — agence/crédit photo résolu (Getty, Reuters, AFP,
Keystone, Wikimedia…) depuis copyright_text/source_url/caption.

Sur `face_analysis` :
- `quality_score` (A6) — score de portrait 0..1 (résolution × frontalité ×
  netteté), pour sélection du meilleur cliché et tri d'audit.
- `est_age` / `est_gender` (B1) — âge et genre **estimés depuis le visage**
  par InsightFace genderage. Inférences sur l'image, distinctes des champs
  Wikidata factuels de l'entité.
- `smile_score` / `expression` (B2) — dérivés du mesh 478 points, sans modèle
  supplémentaire. Servent notamment le composite Galton.

Tous nullables : passes asynchrones / backfill sur l'historique.

Revision ID: v028
Revises: v027
"""
from alembic import op
import sqlalchemy as sa


revision = "v028"
down_revision = "v027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("photo_agency", sa.Text()))
    with op.batch_alter_table("face_analysis") as batch:
        batch.add_column(sa.Column("quality_score", sa.Float()))
        batch.add_column(sa.Column("est_age", sa.Float()))
        batch.add_column(sa.Column("est_gender", sa.Text()))
        batch.add_column(sa.Column("smile_score", sa.Float()))
        batch.add_column(sa.Column("expression", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("face_analysis") as batch:
        batch.drop_column("expression")
        batch.drop_column("smile_score")
        batch.drop_column("est_gender")
        batch.drop_column("est_age")
        batch.drop_column("quality_score")
    with op.batch_alter_table("images") as batch:
        batch.drop_column("photo_agency")
