"""create face_analysis

Revision ID: v006
Revises: v005
"""
from alembic import op
import sqlalchemy as sa


revision = "v006"
down_revision = "v005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "face_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "image_id",
            sa.Integer(),
            sa.ForeignKey("images.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column("face_detected", sa.Boolean()),
        sa.Column("pose", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("yaw", sa.Float()),
        sa.Column("pitch", sa.Float()),
        sa.Column("roll", sa.Float()),
        sa.Column("eye_distance_px", sa.Integer()),
        sa.Column("left_eye_x", sa.Float()),
        sa.Column("left_eye_y", sa.Float()),
        sa.Column("right_eye_x", sa.Float()),
        sa.Column("right_eye_y", sa.Float()),
        sa.Column("nose_x", sa.Float()),
        sa.Column("nose_y", sa.Float()),
        sa.Column(
            "analyzed_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("face_analysis")
