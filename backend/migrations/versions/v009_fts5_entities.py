"""create FTS5 search index over entities (name + aliases)

Revision ID: v009
Revises: v008
"""
from alembic import op


revision = "v009"
down_revision = "v008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE entities_fts USING fts5(
            name,
            aliases,
            content='',
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    op.execute(
        """
        INSERT INTO entities_fts(rowid, name, aliases)
        SELECT
            e.id,
            e.name,
            COALESCE(
                (SELECT GROUP_CONCAT(alias, ' ')
                   FROM entity_aliases
                  WHERE entity_id = e.id),
                ''
            )
        FROM entities e
        """
    )

    op.execute(
        """
        CREATE TRIGGER entities_fts_ai AFTER INSERT ON entities BEGIN
            INSERT INTO entities_fts(rowid, name, aliases)
            VALUES (NEW.id, NEW.name, '');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER entities_fts_ad AFTER DELETE ON entities BEGIN
            DELETE FROM entities_fts WHERE rowid = OLD.id;
        END
        """
    )
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


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ai")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_ai")
    op.execute("DROP TABLE IF EXISTS entities_fts")
