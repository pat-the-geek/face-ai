"""enrichissement Wikidata étendu sur entities (blocs A + B)

Ajoute deux familles de colonnes alimentées depuis Wikidata :

**Bloc A — factuel, périmètre d'intérêt légitime (art. 6.1.f) inchangé :**
- `gender`            P21  — genre (label unique)
- `political_party`   P102 — parti(s) politique(s), pipe-separated
- `positions_held`    P39  — fonctions occupées, pipe-separated
- `awards`            P166 — distinctions reçues, pipe-separated
- `notable_works`     P800 — œuvres notables, pipe-separated

**Bloc B — données sensibles RGPD art. 9 :**
- `ethnic_group`        P172  — origine ethnique, pipe-separated
- `religion`            P140  — religion, pipe-separated
- `sexual_orientation`  P91   — orientation sexuelle (label unique)
- `medical_condition`   P1050 — état de santé, pipe-separated

DÉCISION PROPRIÉTAIRE 2026-05-30 (Patrick Ostertag) : le bloc B est stocké et
exposé normalement, en connaissance du fait que ces catégories sortent du
régime d'intérêt légitime sur lequel CLAUDE.md §1.5 ancrait FACE.ai. Données
issues de Wikidata (déjà publiques). Revue de conformité art. 9 à mener.

Revision ID: v027
Revises: v026
"""
from alembic import op
import sqlalchemy as sa


revision = "v027"
down_revision = "v026"
branch_labels = None
depends_on = None

_A_COLUMNS = (
    "gender",
    "political_party",
    "positions_held",
    "awards",
    "notable_works",
)
_B_COLUMNS = (
    "ethnic_group",
    "religion",
    "sexual_orientation",
    "medical_condition",
)


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        for col in (*_A_COLUMNS, *_B_COLUMNS):
            batch.add_column(sa.Column(col, sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch:
        for col in reversed((*_A_COLUMNS, *_B_COLUMNS)):
            batch.drop_column(col)
