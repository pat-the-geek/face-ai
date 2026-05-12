"""trigger FTS : couvrir le déplacement d'alias (UPDATE OF entity_id)

Bug latent repéré pendant la restauration de l'incident 2026-05-11 : le
trigger `entity_aliases_fts_au` (v018) ne se déclenche que sur
`UPDATE OF alias`. Quand un alias est déplacé d'une entité à une autre
via `UPDATE entity_aliases SET entity_id = …`, la colonne `aliases` de
la table FTS reste figée des deux côtés (l'ancienne entité conserve
faussement l'alias dans son index, la nouvelle ne l'a pas).

Effet observé : après le démerge, recherche FTS « mccartney » remontait
encore `sam-altman` en tête parce que sa colonne FTS aliases contenait
toujours « McCartney, Paul ».

Correctif : ajouter un trigger sur `UPDATE OF entity_id` qui rafraîchit
les DEUX entités (ancien et nouveau propriétaire de l'alias).

Revision ID: v022
Revises: v021
"""
from alembic import op


revision = "v022"
down_revision = "v021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au_eid")
    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_au_eid
        AFTER UPDATE OF entity_id ON entity_aliases BEGIN
            UPDATE entities_fts
               SET aliases = COALESCE(
                   (SELECT GROUP_CONCAT(alias, ' ')
                      FROM entity_aliases
                     WHERE entity_id = OLD.entity_id),
                   ''
               )
             WHERE rowid = OLD.entity_id;
            UPDATE entities_fts
               SET aliases = COALESCE(
                   (SELECT GROUP_CONCAT(alias, ' ')
                      FROM entity_aliases
                     WHERE entity_id = NEW.entity_id),
                   ''
               )
             WHERE rowid = NEW.entity_id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au_eid")
