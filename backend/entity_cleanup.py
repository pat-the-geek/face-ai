"""Nettoyage des entités hors périmètre PERSON.

FACE.ai cible **exclusivement** les personnes physiques apparaissant dans
la presse (spec §1.5, CLAUDE.md — veille interne sur des personnalités
publiques, régime d'intérêt légitime RGPD/nLPD). Les "PERSON" produits
par le NER côté WUDD incluent régulièrement des faux positifs :
- Lieux : "Mar-a-Lago", "Apple Park"
- Entreprises : "OpenAI", "Anthropic"
- Concepts : "AI Act"

Le filtre `type=PERSON` côté requête WUDD ne suffit pas — la classification
NER fait des erreurs. Le garde-fou définitif est `wikidata.P31` (instance
of) : une vraie personne est `Q5` (être humain). Tout ce qui ne l'est pas
doit être purgé.

Stratégie :
- **Purge des données** : on supprime les images (DB + fichiers), les
  liens article_entities, les aliases. Aucune trace photographique d'une
  non-personne ne doit persister.
- **Marqueur fantôme** : on garde la row `entities` avec
  `wikidata_status='not_person'` pour bloquer la recréation au prochain
  pull WUDD (sinon `scraper.get_or_create_entity` recréerait l'entité
  par son nom et le cycle recommencerait).

Deux entrées :
- `purge_non_person(entity_id)` : appelée par le worker dès que
  `wikidata.enrich_entity` renvoie `'not_person'`
- `purge_all_non_persons()` (CLI) : rétro-traitement des entités enrichies
  avant que le garde-fou P31 ne soit en place
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, select

from database import (
    Article,
    ArticleEntity,
    Entity,
    EntityAlias,
    FaceAnalysis,
    Image,
    SessionLocal,
)

log = logging.getLogger("entity_cleanup")


def purge_non_person(entity_id: int) -> dict:
    """Purge les données d'une entité confirmée non-personne.

    - Supprime ses images (DB + fichiers originaux + alignés)
    - Supprime ses face_analysis (cascade ORM via Image.face_analysis)
    - Supprime ses ArticleEntity (le scraper, le worker WUDD et l'API ne
      doivent plus considérer ces liens)
    - Supprime ses EntityAlias (sinon `scraper` retombe dessus par alias)
    - Marque la row Entity avec `wikidata_status='not_person'` et remet
      tous les compteurs à 0. La row reste comme "tombstone" pour qu'un
      ré-pull WUDD du même nom retombe dessus sans la recréer.

    Retourne un résumé chiffré pour audit.
    """
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return {"status": "missing"}

        # Snapshot des chemins fichiers avant suppression DB
        image_rows = (
            db.execute(select(Image).where(Image.entity_id == entity_id))
            .scalars()
            .all()
        )
        files_to_remove: list[Path] = []
        for img in image_rows:
            if img.local_path:
                files_to_remove.append(Path(img.local_path))
            if img.aligned_path:
                files_to_remove.append(Path(img.aligned_path))

        # 1. face_analysis (FK sans cascade DB en SQLite → DELETE explicite)
        image_ids = [img.id for img in image_rows]
        if image_ids:
            db.execute(
                delete(FaceAnalysis).where(FaceAnalysis.image_id.in_(image_ids))
            )

        # 2. images
        db.execute(delete(Image).where(Image.entity_id == entity_id))

        # 3. article_entities
        db.execute(
            delete(ArticleEntity).where(ArticleEntity.entity_id == entity_id)
        )

        # 4. aliases — sinon get_or_create_entity retombe dessus au prochain pull
        db.execute(
            delete(EntityAlias).where(EntityAlias.entity_id == entity_id)
        )

        # 5. tombstone — on garde l'entité pour bloquer la recréation
        entity.wikidata_status = "not_person"
        entity.image_count = 0
        entity.unique_image_count = 0
        entity.article_count = 0
        entity.diversity_score = 0.0
        entity.identity_centroid = None
        entity.identity_count = 0
        entity.is_favorite = False
        # On vide les champs biographiques — ils n'ont plus de sens sur un
        # non-PERSON et leur présence pollue la recherche FTS5 (v018).
        entity.wiki_summary = None
        entity.wiki_url = None
        entity.wiki_thumbnail_url = None
        entity.birth_date = None
        entity.death_date = None
        entity.birth_place = None
        entity.death_place = None
        entity.nationalities = None
        entity.occupations = None
        entity.employer = None
        db.commit()

        # Cleanup fichiers — hors transaction (best effort)
        files_removed = 0
        for path in files_to_remove:
            try:
                if path.exists():
                    path.unlink()
                    files_removed += 1
            except OSError:
                pass

        log.info(
            "purge not_person : entity=%s (qid=%s) images=%d files=%d",
            entity.name,
            entity.wikidata_qid,
            len(image_rows),
            files_removed,
        )
        return {
            "status": "purged",
            "name": entity.name,
            "qid": entity.wikidata_qid,
            "images_removed": len(image_rows),
            "files_removed": files_removed,
        }
    finally:
        db.close()


def find_done_entities_to_recheck() -> list[int]:
    """IDs des entités enrichies AVANT le garde-fou P31 — à re-valider.

    Ce sont celles dont `wikidata_status='done'` ET qui ont un QID. Le
    rétro-traitement appelle `enrich_entity` à nouveau, et si Wikidata
    renvoie un P31 != Q5, l'entité bascule en `not_person` puis on purge.
    """
    db = SessionLocal()
    try:
        return [
            row[0]
            for row in db.execute(
                select(Entity.id).where(
                    Entity.wikidata_status == "done",
                    Entity.wikidata_qid.is_not(None),
                )
            )
        ]
    finally:
        db.close()


def purge_all_non_persons(limit: int | None = None) -> dict:
    """Rétro-traitement : re-vérifie toutes les entités enrichies contre P31.

    Pour chaque entité `wikidata_status='done'` :
      1. Re-appelle `wikidata.enrich_entity` qui maintenant teste P31
      2. Si elle retourne `not_person` → on purge

    Politesse : un appel `_get_statements` par entité (~1 req Wikidata).
    On rate-limit à 1 s entre 2 entités, comme l'enrich initial.

    `limit` : si fourni, n'évalue que les N premières (utile pour tester
    en dry-run avant un passage complet).
    """
    import time

    from wikidata import enrich_entity

    ids = find_done_entities_to_recheck()
    if limit:
        ids = ids[:limit]

    summary = {
        "checked": 0,
        "purged": 0,
        "still_person": 0,
        "errors": 0,
        "details": [],
    }
    for eid in ids:
        try:
            status = enrich_entity(eid)
        except Exception as e:  # noqa: BLE001
            log.exception("erreur recheck entity=%s", eid)
            summary["errors"] += 1
            continue
        summary["checked"] += 1
        if status == "not_person":
            r = purge_non_person(eid)
            if r.get("status") == "purged":
                summary["purged"] += 1
                summary["details"].append(
                    f"{r['name']} (Q{r['qid']}) — {r['images_removed']} img"
                )
        else:
            summary["still_person"] += 1
        time.sleep(1.0)  # politesse Wikidata

    return summary


def find_orphan_articles() -> int:
    """Articles sans aucune entité associée — devenus orphelins après les
    purges not_person. Pour info uniquement, on ne les supprime pas
    automatiquement (un article peut servir à l'historique scraping).
    """
    db = SessionLocal()
    try:
        return (
            db.scalar(
                select(__import__("sqlalchemy").func.count())
                .select_from(Article)
                .where(
                    Article.id.not_in(
                        select(ArticleEntity.article_id).distinct()
                    )
                )
            )
            or 0
        )
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    import logging as lg

    parser = argparse.ArgumentParser(
        description="Nettoyage des entités hors périmètre PERSON (faux PERSON WUDD)"
    )
    parser.add_argument(
        "--purge-non-persons",
        action="store_true",
        help="Re-vérifie via Wikidata P31 et purge les entités non-Q5",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="N'évalue que les N premières entités (test/dry-run)",
    )
    parser.add_argument(
        "--purge-entity",
        type=int,
        default=None,
        help="Purge directement une entité par ID (forçage manuel)",
    )
    args = parser.parse_args()

    lg.basicConfig(level=lg.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.purge_entity is not None:
        print(purge_non_person(args.purge_entity))
    elif args.purge_non_persons:
        result = purge_all_non_persons(limit=args.limit)
        print(result)
        print(f"\nArticles orphelins après purge : {find_orphan_articles()}")
    else:
        parser.print_help()
