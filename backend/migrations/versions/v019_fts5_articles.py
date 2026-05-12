"""create FTS5 index on articles (title, source_domain)

Permet la recherche full-text dans les titres d'articles ingérés depuis
WUDD. Le `source_domain` est inclus pour permettre `lemonde* trump` =
articles du Monde mentionnant Trump.

Pas besoin d'indexer l'URL ou le wudd_article_id (identifiants opaques) ;
ni de stocker le contenu de l'article — WUDD garde ça côté amont, on n'a
que les titres en local.

Revision ID: v019
Revises: v018
"""
from alembic import op


revision = "v019"
down_revision = "v018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE articles_fts USING fts5(
            title,
            source_domain,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    op.execute(
        """
        INSERT INTO articles_fts(rowid, title, source_domain)
        SELECT id, COALESCE(title, ''), COALESCE(source_domain, '')
          FROM articles
        """
    )

    op.execute(
        """
        CREATE TRIGGER articles_fts_ai AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(rowid, title, source_domain)
            VALUES (NEW.id, COALESCE(NEW.title, ''),
                    COALESCE(NEW.source_domain, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER articles_fts_ad AFTER DELETE ON articles BEGIN
            DELETE FROM articles_fts WHERE rowid = OLD.id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER articles_fts_au AFTER UPDATE ON articles BEGIN
            UPDATE articles_fts
               SET title = COALESCE(NEW.title, ''),
                   source_domain = COALESCE(NEW.source_domain, '')
             WHERE rowid = NEW.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS articles_fts_au")
    op.execute("DROP TRIGGER IF EXISTS articles_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS articles_fts_ai")
    op.execute("DROP TABLE IF EXISTS articles_fts")
