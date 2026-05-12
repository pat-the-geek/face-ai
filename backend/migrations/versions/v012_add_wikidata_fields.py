"""ajouter colonnes wikidata + wiki à entities

Revision ID: v012
Revises: v011
"""
from alembic import op
import sqlalchemy as sa


revision = "v012"
down_revision = "v011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("wikidata_qid", sa.Text()))
        batch.add_column(sa.Column("wikidata_status", sa.Text(),
                                   server_default="pending"))
        batch.add_column(sa.Column("wikidata_score", sa.Float()))
        batch.add_column(sa.Column("wikidata_synced_at", sa.DateTime()))
        batch.add_column(sa.Column("wiki_summary", sa.Text()))
        batch.add_column(sa.Column("wiki_url", sa.Text()))
        batch.add_column(sa.Column("wiki_thumbnail_url", sa.Text()))

    op.create_index("idx_entities_wikidata_status", "entities", ["wikidata_status"])


def downgrade() -> None:
    op.drop_index("idx_entities_wikidata_status", table_name="entities")
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("wiki_thumbnail_url")
        batch.drop_column("wiki_url")
        batch.drop_column("wiki_summary")
        batch.drop_column("wikidata_synced_at")
        batch.drop_column("wikidata_score")
        batch.drop_column("wikidata_status")
        batch.drop_column("wikidata_qid")
