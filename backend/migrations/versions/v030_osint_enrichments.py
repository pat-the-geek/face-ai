"""enrichissement OSINT (open data, personnes publiques) + filtre pays

Ajoute les colonnes OSINT sur `entities` et `images`, plus la table
`entity_gdelt_coverage`. Toutes les sources alimentées par ces colonnes sont
**open data** et ne concernent que des **personnes publiques** déjà présentes
dans le corpus FACE.ai (personnalités passées par WUDD.ai). Aucune inférence,
aucune source privée — cf. CLAUDE.md, décision périmètre OSINT 2026-06-05.

Blocs :
- Filtre pays : `country_code` (ISO 3166-1 alpha-2) + `country_name` (FR),
  dérivés de Wikidata P27→P297. Transversal, alimente l'UI CountryFilter et la
  carte.
- OpenSanctions (P1A) : `sanctions_status` ('sanctioned'/'pep'/'clean'/
  'unknown') + `sanctions_detail` JSON (datasets, topics, last_checked).
- Parlement suisse (P1C) : `parliament_ch_id`, `parliament_ch_data` JSON,
  `is_swiss_parliament_member`.
- GLEIF (P3A) : `gleif_data` JSON (organisations légales liées).
- ICIJ Offshore Leaks (P3B) : `icij_match` + `icij_detail` JSON.
- Wayback (P2B) : `images.capture_year` (année de la capture archivée).
- GDELT (P2A) : table `entity_gdelt_coverage` (séries temporelles de
  couverture médiatique mondiale).

Revision ID: v030
Revises: v029
"""
from alembic import op
import sqlalchemy as sa


revision = "v030"
down_revision = "v029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        # Filtre pays (transversal)
        batch.add_column(sa.Column("country_code", sa.Text(), nullable=True))
        batch.add_column(sa.Column("country_name", sa.Text(), nullable=True))
        # OpenSanctions (P1A)
        batch.add_column(sa.Column("sanctions_status", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sanctions_detail", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sanctions_synced_at", sa.DateTime(), nullable=True))
        # Parlement suisse (P1C)
        batch.add_column(sa.Column("parliament_ch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("parliament_ch_data", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "is_swiss_parliament_member",
                sa.Boolean(),
                server_default="0",
                nullable=True,
            )
        )
        # GLEIF (P3A)
        batch.add_column(sa.Column("gleif_data", sa.Text(), nullable=True))
        batch.add_column(sa.Column("gleif_synced_at", sa.DateTime(), nullable=True))
        # ICIJ Offshore Leaks (P3B)
        batch.add_column(
            sa.Column(
                "icij_match", sa.Boolean(), server_default="0", nullable=True
            )
        )
        batch.add_column(sa.Column("icij_detail", sa.Text(), nullable=True))
        batch.add_column(sa.Column("icij_synced_at", sa.DateTime(), nullable=True))

    # Wayback Machine (P2B) — année de capture sur l'image archivée
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("capture_year", sa.Integer(), nullable=True))

    # Index pour le filtre pays (GET /entities?country=CH et /entities/countries)
    op.create_index("ix_entities_country_code", "entities", ["country_code"])

    # GDELT (P2A) — couverture médiatique mondiale, série temporelle par entité
    op.create_table(
        "entity_gdelt_coverage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("article_count", sa.Integer()),
        sa.Column("avg_tone", sa.Float()),
        sa.Column("top_countries", sa.Text()),  # JSON
        sa.Column("top_themes", sa.Text()),  # JSON
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_gdelt_entity", "entity_gdelt_coverage", ["entity_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_gdelt_entity", table_name="entity_gdelt_coverage")
    op.drop_table("entity_gdelt_coverage")
    op.drop_index("ix_entities_country_code", table_name="entities")
    with op.batch_alter_table("images") as batch:
        batch.drop_column("capture_year")
    with op.batch_alter_table("entities") as batch:
        for col in (
            "country_code",
            "country_name",
            "sanctions_status",
            "sanctions_detail",
            "sanctions_synced_at",
            "parliament_ch_id",
            "parliament_ch_data",
            "is_swiss_parliament_member",
            "gleif_data",
            "gleif_synced_at",
            "icij_match",
            "icij_detail",
            "icij_synced_at",
        ):
            batch.drop_column(col)
