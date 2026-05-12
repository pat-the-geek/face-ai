"""ajouter last_articles_synced_at + wudd_mentions à entities

Spec roadmap court-terme : pull WUDD articles par batch quotidien.
- `last_articles_synced_at` : marqueur de la dernière sync articles pour cette
  entité, NULL = jamais traitée. Filtre du sélecteur `select_next_batch`.
- `wudd_mentions` : nombre de mentions côté WUDD (cf. export `mentions`),
  cache local pour trier par "high value first" sans refaire l'API à chaque
  cycle batch.

Revision ID: v017
Revises: v016
"""
from alembic import op
import sqlalchemy as sa


revision = "v017"
down_revision = "v016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("last_articles_synced_at", sa.DateTime()))
        batch.add_column(
            sa.Column("wudd_mentions", sa.Integer(), server_default="0")
        )
    op.create_index(
        "idx_entities_wudd_mentions", "entities", ["wudd_mentions"]
    )
    op.create_index(
        "idx_entities_last_articles_synced",
        "entities",
        ["last_articles_synced_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_entities_last_articles_synced", table_name="entities")
    op.drop_index("idx_entities_wudd_mentions", table_name="entities")
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("wudd_mentions")
        batch.drop_column("last_articles_synced_at")
