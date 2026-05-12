"""create FTS5 index on images (caption, alt_text, copyright_text)

Permet de chercher dans les légendes des photos ("Trump golf",
"Macron Élysée", "AP Photo"). Caption + alt_text + copyright = 3 colonnes
indexées, ce qui couvre la totalité des champs textuels disponibles
sur `images` (le reste est binaire ou structurel).

Revision ID: v020
Revises: v019
"""
from alembic import op


revision = "v020"
down_revision = "v019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE images_fts USING fts5(
            caption,
            alt_text,
            copyright_text,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    op.execute(
        """
        INSERT INTO images_fts(rowid, caption, alt_text, copyright_text)
        SELECT id,
               COALESCE(caption, ''),
               COALESCE(alt_text, ''),
               COALESCE(copyright_text, '')
          FROM images
        """
    )

    op.execute(
        """
        CREATE TRIGGER images_fts_ai AFTER INSERT ON images BEGIN
            INSERT INTO images_fts(rowid, caption, alt_text, copyright_text)
            VALUES (NEW.id, COALESCE(NEW.caption, ''),
                    COALESCE(NEW.alt_text, ''),
                    COALESCE(NEW.copyright_text, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER images_fts_ad AFTER DELETE ON images BEGIN
            DELETE FROM images_fts WHERE rowid = OLD.id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER images_fts_au AFTER UPDATE ON images BEGIN
            UPDATE images_fts
               SET caption = COALESCE(NEW.caption, ''),
                   alt_text = COALESCE(NEW.alt_text, ''),
                   copyright_text = COALESCE(NEW.copyright_text, '')
             WHERE rowid = NEW.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS images_fts_au")
    op.execute("DROP TRIGGER IF EXISTS images_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS images_fts_ai")
    op.execute("DROP TABLE IF EXISTS images_fts")
