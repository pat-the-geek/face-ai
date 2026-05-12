"""ajouter `images.source_provider` (wudd / ddg / manual)

Trace la provenance d'une image pour distinguer les ingestions WUDD (corpus
maîtrisé, spec §1.5) des ingestions hors-corpus (DuckDuckGo, upload manuel).
Permet :
- Filtrage côté UI pour audit renforcé sur les images non-WUDD
- Statistiques (combien d'images hors-corpus dans la collection)
- Rollback simple via DELETE WHERE source_provider='ddg' si besoin

Valeurs attendues :
- `wudd` (défaut, valeur historique) — image issue d'un article WUDD
- `ddg`  — image trouvée via DuckDuckGo Images, ingérée explicitement par
  l'utilisateur via le picker (cf. bouton DDG dans GalleryHeader)
- `manual` — réservé pour upload direct futur

Revision ID: v023
Revises: v022
"""
from alembic import op
import sqlalchemy as sa


revision = "v023"
down_revision = "v022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("images") as batch:
        batch.add_column(
            sa.Column(
                "source_provider",
                sa.Text(),
                server_default="wudd",
            )
        )
    op.create_index(
        "idx_images_source_provider",
        "images",
        ["source_provider"],
    )


def downgrade() -> None:
    op.drop_index("idx_images_source_provider", table_name="images")
    with op.batch_alter_table("images") as batch:
        batch.drop_column("source_provider")
