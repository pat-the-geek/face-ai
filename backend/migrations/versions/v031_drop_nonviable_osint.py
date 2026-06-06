"""suppression des fonctions OSINT non viables (GLEIF, ICIJ, Wayback)

État des lieux 2026-06-06 : GLEIF (0 résultat — base centrée organisation,
inadaptée aux personnes), ICIJ (API morte 404, 0 résultat) et Wayback
(0 capture) n'ont jamais rien produit. Décision : suppression complète. On
retire aussi `entity_gdelt_coverage.top_themes` (thèmes dérivés de mots-clés
de titres — non fiables ; on garde volume + tonalité + pays).

Colonnes supprimées :
- entities : gleif_data, gleif_synced_at, icij_match, icij_detail, icij_synced_at
- images : capture_year (Wayback)
- entity_gdelt_coverage : top_themes

⚠ IMPORTANT — on utilise le **DROP COLUMN natif** de SQLite (≥ 3.35), PAS
`batch_alter_table`. Le mode batch RECRÉE la table (copie+rename), ce qui :
(a) supprime les triggers FTS attachés à `entities`, et (b) corrompt le B-tree
si un autre process écrit en même temps (incident 2026-06-06 : corruption du
fichier après recréation de `images` pendant que le worker écrivait). Le DROP
COLUMN natif modifie la table en place, préserve les triggers et ne copie rien.
Idempotent : on ne supprime que les colonnes encore présentes.

Revision ID: v031
Revises: v030
"""
from alembic import op
import sqlalchemy as sa


revision = "v031"
down_revision = "v030"
branch_labels = None
depends_on = None

_DROPS = {
    "entities": [
        "gleif_data",
        "gleif_synced_at",
        "icij_match",
        "icij_detail",
        "icij_synced_at",
    ],
    "images": ["capture_year"],
    "entity_gdelt_coverage": ["top_themes"],
}


def _existing(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table, cols in _DROPS.items():
        present = _existing(table)
        for col in cols:
            if col in present:
                # DROP COLUMN natif (pas de recréation de table → triggers FTS
                # préservés, pas de risque de corruption concurrente).
                op.execute(f'ALTER TABLE "{table}" DROP COLUMN "{col}"')


def downgrade() -> None:
    with op.batch_alter_table("entity_gdelt_coverage") as batch:
        batch.add_column(sa.Column("top_themes", sa.Text(), nullable=True))
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("capture_year", sa.Integer(), nullable=True))
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("gleif_data", sa.Text(), nullable=True))
        batch.add_column(sa.Column("gleif_synced_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("icij_match", sa.Boolean(), server_default="0", nullable=True)
        )
        batch.add_column(sa.Column("icij_detail", sa.Text(), nullable=True))
        batch.add_column(sa.Column("icij_synced_at", sa.DateTime(), nullable=True))
