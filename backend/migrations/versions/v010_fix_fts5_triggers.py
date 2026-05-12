"""fix FTS5 triggers — contentless tables don't support UPDATE

Revision ID: v010
Revises: v009
"""
from alembic import op


revision = "v010"
down_revision = "v009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ai")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_au")

    op.execute(
        """
        CREATE TRIGGER entities_fts_au AFTER UPDATE OF name ON entities BEGIN
            DELETE FROM entities_fts WHERE rowid = NEW.id;
            INSERT INTO entities_fts(rowid, name, aliases)
            VALUES (
                NEW.id,
                NEW.name,
                COALESCE(
                    (SELECT GROUP_CONCAT(alias, ' ')
                       FROM entity_aliases
                      WHERE entity_id = NEW.id),
                    ''
                )
            );
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_ai AFTER INSERT ON entity_aliases BEGIN
            DELETE FROM entities_fts WHERE rowid = NEW.entity_id;
            INSERT INTO entities_fts(rowid, name, aliases)
            VALUES (
                NEW.entity_id,
                (SELECT name FROM entities WHERE id = NEW.entity_id),
                COALESCE(
                    (SELECT GROUP_CONCAT(alias, ' ')
                       FROM entity_aliases
                      WHERE entity_id = NEW.entity_id),
                    ''
                )
            );
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_ad AFTER DELETE ON entity_aliases BEGIN
            DELETE FROM entities_fts WHERE rowid = OLD.entity_id;
            INSERT INTO entities_fts(rowid, name, aliases)
            VALUES (
                OLD.entity_id,
                (SELECT name FROM entities WHERE id = OLD.entity_id),
                COALESCE(
                    (SELECT GROUP_CONCAT(alias, ' ')
                       FROM entity_aliases
                      WHERE entity_id = OLD.entity_id),
                    ''
                )
            );
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_au AFTER UPDATE OF alias ON entity_aliases BEGIN
            DELETE FROM entities_fts WHERE rowid = NEW.entity_id;
            INSERT INTO entities_fts(rowid, name, aliases)
            VALUES (
                NEW.entity_id,
                (SELECT name FROM entities WHERE id = NEW.entity_id),
                COALESCE(
                    (SELECT GROUP_CONCAT(alias, ' ')
                       FROM entity_aliases
                      WHERE entity_id = NEW.entity_id),
                    ''
                )
            );
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ai")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_au")

    op.execute(
        """
        CREATE TRIGGER entities_fts_au AFTER UPDATE OF name ON entities BEGIN
            UPDATE entities_fts SET name = NEW.name WHERE rowid = NEW.id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_ai AFTER INSERT ON entity_aliases BEGIN
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
    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_ad AFTER DELETE ON entity_aliases BEGIN
            UPDATE entities_fts
               SET aliases = COALESCE(
                   (SELECT GROUP_CONCAT(alias, ' ')
                      FROM entity_aliases
                     WHERE entity_id = OLD.entity_id),
                   ''
               )
             WHERE rowid = OLD.entity_id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER entity_aliases_fts_au AFTER UPDATE OF alias ON entity_aliases BEGIN
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
