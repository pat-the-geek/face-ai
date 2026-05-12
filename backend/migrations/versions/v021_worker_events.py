"""table worker_events pour observabilité multi-container

API et worker tournent dans 2 containers Docker distincts (process Python
séparés), donc un singleton in-memory ne suffit pas pour exposer les
métriques worker au /admin/worker-status (cf. incident 2026-05-11).

On persiste chaque événement (success/error d'un cycle de loop, ou
événement métier comme `merge_ok`/`merge_blocked`) en DB. L'API agrège
sur une fenêtre 24h pour exposer les métriques. Rotation à 7 jours côté
worker (window large pour debug historique).

Revision ID: v021
Revises: v020
"""
from alembic import op
import sqlalchemy as sa


revision = "v021"
down_revision = "v020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ts",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # 'success' / 'error' pour les cycles de loop ; sinon nom d'événement
        # métier (`merge_ok`, `merge_blocked`, `not_person_purged`, etc.)
        sa.Column("kind", sa.Text(), nullable=False),
        # Nom de la boucle worker pour les success/error, sinon NULL pour
        # les événements métier qui ne sont pas liés à un cycle unique
        sa.Column("loop_name", sa.Text(), nullable=True),
        # JSON sérialisé du résumé de cycle (utile pour voir le dernier
        # contenu d'un cycle « le dernier merge_loop a fusionné 0,
        # bloqué 2 »). Toujours < 1 Kio en pratique.
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.create_index("idx_worker_events_ts", "worker_events", ["ts"])
    op.create_index(
        "idx_worker_events_kind_ts", "worker_events", ["kind", "ts"]
    )


def downgrade() -> None:
    op.drop_index("idx_worker_events_kind_ts", table_name="worker_events")
    op.drop_index("idx_worker_events_ts", table_name="worker_events")
    op.drop_table("worker_events")
