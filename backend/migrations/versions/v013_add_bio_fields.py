"""ajouter colonnes biographiques à entities

Spec §9.3 — données issues des statements Wikidata :
- dates de naissance / décès
- lieux de naissance / décès (label résolu)
- nationalités (pipe-separated)
- occupations (pipe-separated)
- employeur principal (label)

Revision ID: v013
Revises: v012
"""
from alembic import op
import sqlalchemy as sa


revision = "v013"
down_revision = "v012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.add_column(sa.Column("birth_date", sa.Date()))
        batch.add_column(sa.Column("death_date", sa.Date()))
        batch.add_column(sa.Column("birth_place", sa.Text()))
        batch.add_column(sa.Column("death_place", sa.Text()))
        batch.add_column(sa.Column("nationalities", sa.Text()))
        batch.add_column(sa.Column("occupations", sa.Text()))
        batch.add_column(sa.Column("employer", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        batch.drop_column("employer")
        batch.drop_column("occupations")
        batch.drop_column("nationalities")
        batch.drop_column("death_place")
        batch.drop_column("birth_place")
        batch.drop_column("death_date")
        batch.drop_column("birth_date")
