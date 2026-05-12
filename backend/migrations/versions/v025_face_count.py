"""ajouter `face_analysis.face_count` (nombre de visages dans l'image source)

Le pipeline d'alignement (face_processor.detect_landmarks) force MediaPipe
à `max_num_faces=1` et garde le premier visage détecté pour l'alignement.
Conséquence : une image de groupe (ex. Trump + Murdoch, Trump + Carlson +
Owens + Jones) est alignée sur **un seul** visage, l'autre est invisible
pour le pipeline. Quand ArcFace calcule la distance au centroïde, un
visage de groupe dévie souvent du centroïde individuel et bascule en
`flagged` — alors que l'attribution n'est pas fausse, c'est juste une
composition multi-personnes.

On stocke `face_count` (visages détectés via mp.FaceDetection sur l'image
source) pour permettre à l'UI audit P9 et à `list_flagged_images` (MCP) de
distinguer :
- distance élevée + face_count=1 → vraie mauvaise attribution (priorité
  audit haute)
- distance élevée + face_count>1 → composition multi-personnes (audit
  cosmétique, l'attribution textuelle reste pertinente)

Nullable : valeur null = pré-v025, sera remplie par
`python face_processor.py --backfill-face-count`. Le worker la renseigne
pour toutes les nouvelles ingestions.

Revision ID: v025
Revises: v024
"""
from alembic import op
import sqlalchemy as sa


revision = "v025"
down_revision = "v024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("face_analysis") as batch:
        batch.add_column(
            sa.Column("face_count", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("face_analysis") as batch:
        batch.drop_column("face_count")
