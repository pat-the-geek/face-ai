"""extend entities_fts with bio fields (occupations, employer, nationalities, summary)

Permet la recherche par profession ("physicien"), employeur ("OpenAI"),
nationalité ("américain"), ou tout mot du résumé Wikipedia. Sans cet
élargissement la recherche est strictement onomastique.

Le résumé Wikipedia (`wiki_summary`) peut faire 5–10 ko par entité enrichie.
Sur ~6000 entités enrichies, l'index gonfle de ~30–60 MB — acceptable au
regard de la valeur ajoutée (et SQLite FTS5 a une compression interne par
préfixe sur les colonnes répétitives).

Revision ID: v018
Revises: v017
"""
from alembic import op


revision = "v018"
down_revision = "v017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # On reconstruit la table entities_fts pour ajouter les nouvelles colonnes.
    # FTS5 ne supporte pas ALTER TABLE ADD COLUMN.
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entity_aliases_fts_ai")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_au")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS entities_fts_ai")
    op.execute("DROP TABLE IF EXISTS entities_fts")

    # Les champs bio sont stockés en pipe-separated dans `entities`
    # (occupations, nationalities) ou en texte libre (employer, wiki_summary,
    # birth_place). FTS5 traite tout comme des tokens espace-séparés ;
    # on transforme les pipes en espaces côté SELECT pour ne pas casser
    # le tokenizer sur les `|`.
    op.execute(
        """
        CREATE VIRTUAL TABLE entities_fts USING fts5(
            name,
            aliases,
            occupations,
            employer,
            nationalities,
            birth_place,
            summary,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    op.execute(
        """
        INSERT INTO entities_fts(
            rowid, name, aliases, occupations, employer, nationalities,
            birth_place, summary
        )
        SELECT
            e.id,
            e.name,
            COALESCE(
                (SELECT GROUP_CONCAT(alias, ' ')
                   FROM entity_aliases
                  WHERE entity_id = e.id),
                ''
            ),
            REPLACE(COALESCE(e.occupations, ''), '|', ' '),
            COALESCE(e.employer, ''),
            REPLACE(COALESCE(e.nationalities, ''), '|', ' '),
            COALESCE(e.birth_place, ''),
            COALESCE(e.wiki_summary, '')
        FROM entities e
        """
    )

    # Triggers : INSERT initialise avec les valeurs entities (les bio
    # arriveront via update lors de l'enrichissement Wikidata async).
    op.execute(
        """
        CREATE TRIGGER entities_fts_ai AFTER INSERT ON entities BEGIN
            INSERT INTO entities_fts(
                rowid, name, aliases, occupations, employer, nationalities,
                birth_place, summary
            )
            VALUES (
                NEW.id, NEW.name, '',
                REPLACE(COALESCE(NEW.occupations, ''), '|', ' '),
                COALESCE(NEW.employer, ''),
                REPLACE(COALESCE(NEW.nationalities, ''), '|', ' '),
                COALESCE(NEW.birth_place, ''),
                COALESCE(NEW.wiki_summary, '')
            );
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
    # UPDATE catch-all : on rafraîchit toutes les colonnes dès qu'une entité
    # change. Plus simple qu'un trigger par colonne ; coût négligeable.
    op.execute(
        """
        CREATE TRIGGER entities_fts_au AFTER UPDATE ON entities BEGIN
            UPDATE entities_fts SET
                name = NEW.name,
                occupations = REPLACE(COALESCE(NEW.occupations, ''), '|', ' '),
                employer = COALESCE(NEW.employer, ''),
                nationalities = REPLACE(COALESCE(NEW.nationalities, ''), '|', ' '),
                birth_place = COALESCE(NEW.birth_place, ''),
                summary = COALESCE(NEW.wiki_summary, '')
             WHERE rowid = NEW.id;
        END
        """
    )

    # Aliases : recompose l'ensemble en cas d'INSERT/UPDATE/DELETE.
    # `entities_fts.aliases` est une concaténation de tous les aliases de
    # l'entité — il faut donc refaire le GROUP_CONCAT à chaque mutation.
    for op_kind, ref in (
        ("INSERT", "NEW"),
        ("DELETE", "OLD"),
        ("UPDATE OF alias", "NEW"),
    ):
        # Pour DELETE on lit OLD.entity_id ; pour INSERT/UPDATE c'est NEW.
        # Trigger name : entity_aliases_fts_ai / ad / au.
        suffix = {
            "INSERT": "ai",
            "DELETE": "ad",
            "UPDATE OF alias": "au",
        }[op_kind]
        op.execute(
            f"""
            CREATE TRIGGER entity_aliases_fts_{suffix}
            AFTER {op_kind} ON entity_aliases BEGIN
                UPDATE entities_fts
                   SET aliases = COALESCE(
                       (SELECT GROUP_CONCAT(alias, ' ')
                          FROM entity_aliases
                         WHERE entity_id = {ref}.entity_id),
                       ''
                   )
                 WHERE rowid = {ref}.entity_id;
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

    # Recréer en mode v011 (2 colonnes seulement)
    op.execute(
        """
        CREATE VIRTUAL TABLE entities_fts USING fts5(
            name, aliases,
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )
    op.execute(
        """
        INSERT INTO entities_fts(rowid, name, aliases)
        SELECT e.id, e.name,
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
