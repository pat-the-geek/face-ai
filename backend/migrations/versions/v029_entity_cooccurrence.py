"""table entity_cooccurrence — graphe de cooccurrence éditoriale matérialisé (A5)

Une ligne = une paire d'entités apparaissant ensemble dans `shared_articles`
articles distincts. Convention `entity_a_id < entity_b_id` (paire non ordonnée
stockée une seule fois). Recalculé en masse par
`cooccurrence.recompute_cooccurrence`. Index sur chaque extrémité pour
interroger « partenaires de X » dans les deux sens.

Revision ID: v029
Revises: v028
"""
from alembic import op
import sqlalchemy as sa


revision = "v029"
down_revision = "v028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_cooccurrence",
        sa.Column(
            "entity_a_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_b_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("shared_articles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_cooccurrence_a", "entity_cooccurrence", ["entity_a_id"]
    )
    op.create_index(
        "ix_cooccurrence_b", "entity_cooccurrence", ["entity_b_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cooccurrence_b", table_name="entity_cooccurrence")
    op.drop_index("ix_cooccurrence_a", table_name="entity_cooccurrence")
    op.drop_table("entity_cooccurrence")
