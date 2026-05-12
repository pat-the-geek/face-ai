"""ajouter `face_analysis.landmarks_blob` (468 points MediaPipe)

L'overlay LandmarkOverlay côté UI affiche actuellement 3 points (yeux
+ nez). Pour pousser l'esthétique forensique de la spec §10, on stocke
la totalité du mesh MediaPipe (468 points sans iris, ou 478 avec
refine_landmarks).

Stockage : float32 little-endian, format compact `x1, y1, x2, y2, …`
en coordonnées normalisées (0..1) sur l'image alignée 300×300. 468
points × 2 × 4 octets = ~3.7 Ko par image. Sur 100k images = ~370 Mo,
acceptable.

Nullable : les images analysées avant cette migration n'auront pas le
mesh. Le worker le remplit progressivement aux nouvelles ingestions.
LandmarkOverlay côté UI fallback aux 3 points historiques si null.

Revision ID: v024
Revises: v023
"""
from alembic import op
import sqlalchemy as sa


revision = "v024"
down_revision = "v023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("face_analysis") as batch:
        batch.add_column(
            sa.Column("landmarks_blob", sa.LargeBinary(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("face_analysis") as batch:
        batch.drop_column("landmarks_blob")
