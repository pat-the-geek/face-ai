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

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select

import config
from database import (
    Article,
    ArticleEntity,
    Entity,
    EntityAlias,
    EntityCooccurrence,
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


def find_orphan_entities(days: int | None = None) -> list[Entity]:
    """Entités orphelines = `not_found` Wikidata + 0 image + confirmées
    not_found depuis > `days` jours.

    Différence avec `not_person` : `not_found` signifie « introuvable sur
    Wikidata » (pas « confirmée non-humaine »). Une telle entité est soit un
    faux PERSON du NER WUDD, soit une personne trop obscure. Sans portrait
    (0 image), elle est inutilisable dans une galerie de visages → candidate
    à la purge. Le seuil temporel évite de toucher une entité tout juste
    marquée not_found qui pourrait recevoir un portrait sous peu (ingestion
    asynchrone).
    """
    if days is None:
        days = config.CLEANUP_ORPHAN_AFTER_DAYS
    cutoff = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        # Sous-requête : entity_id ayant au moins une image. **Filtrer les
        # NULL est crucial** : `id NOT IN (… , NULL)` est faux pour TOUTES les
        # lignes en SQL (piège NULL). Sans ce filtre, des images à entity_id
        # NULL (ingestion en attente) feraient retourner 0 orphelin à tort.
        with_images = select(Image.entity_id).where(Image.entity_id.is_not(None)).distinct()
        return (
            db.execute(
                select(Entity)
                .where(
                    Entity.wikidata_status == "not_found",
                    Entity.id.not_in(with_images),
                    # synced_at NULL est traité comme « assez vieux » : un
                    # not_found sans horodatage est un résidu historique.
                    or_(
                        Entity.wikidata_synced_at.is_(None),
                        Entity.wikidata_synced_at < cutoff,
                    ),
                )
                .order_by(Entity.name)
            )
            .scalars()
            .all()
        )
    finally:
        db.close()


def _delete_orphan(db, entity: Entity) -> None:
    """Suppression COMPLÈTE d'une entité orpheline (pas de tombstone).

    Contrairement à `purge_non_person`, on retire la row `entities`
    elle-même : `not_found` n'est pas un verdict définitif (l'entité peut
    réapparaître avec un portrait via un futur pull WUDD et mériter alors
    une vraie place). On supprime aussi ses liens (aliases, article_entities,
    cooccurrences) car les FK SQLite ne cascadent pas (CLAUDE.md). Le
    trigger FTS5 `entities_fts_ad` nettoie l'index plein-texte au DELETE.
    """
    eid = entity.id
    db.execute(delete(ArticleEntity).where(ArticleEntity.entity_id == eid))
    db.execute(delete(EntityAlias).where(EntityAlias.entity_id == eid))
    db.execute(
        delete(EntityCooccurrence).where(
            or_(
                EntityCooccurrence.entity_a_id == eid,
                EntityCooccurrence.entity_b_id == eid,
            )
        )
    )
    db.delete(entity)


def cleanup_orphan_entities(days: int | None = None, dry_run: bool = False) -> dict:
    """Purge manuelle des entités orphelines (`find_orphan_entities`).

    `dry_run=True` : ne supprime rien, retourne juste la liste des candidates.
    Déclenchée à la main (endpoint `/admin/cleanup-orphans` + UI) — pas de
    boucle worker, l'opération est destructive et on veut un humain dans la
    boucle (décision de périmètre, cf. AskUserQuestion 2026-06-02).
    """
    if days is None:
        days = config.CLEANUP_ORPHAN_AFTER_DAYS
    orphans = find_orphan_entities(days)
    names = [{"slug": e.slug, "name": e.name} for e in orphans]

    if dry_run:
        return {"dry_run": True, "days": days, "count": len(names), "entities": names}

    db = SessionLocal()
    try:
        removed = 0
        for o in orphans:
            entity = db.get(Entity, o.id)
            if entity is None:
                continue
            _delete_orphan(db, entity)
            removed += 1
        db.commit()
        log.info("cleanup orphelines : %d entités supprimées (seuil %dj)", removed, days)
        return {
            "dry_run": False,
            "days": days,
            "count": removed,
            "entities": names,
            "orphan_articles": find_orphan_articles(),
        }
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
    parser.add_argument(
        "--cleanup-orphans",
        action="store_true",
        help="Purge les entités orphelines (not_found Wikidata + 0 image > N jours)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Avec --cleanup-orphans : liste les candidates sans rien supprimer",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Seuil en jours pour --cleanup-orphans (défaut config)",
    )
    args = parser.parse_args()

    lg.basicConfig(level=lg.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.purge_entity is not None:
        print(purge_non_person(args.purge_entity))
    elif args.cleanup_orphans:
        print(cleanup_orphan_entities(days=args.days, dry_run=args.dry_run))
    elif args.purge_non_persons:
        result = purge_all_non_persons(limit=args.limit)
        print(result)
        print(f"\nArticles orphelins après purge : {find_orphan_articles()}")
    else:
        parser.print_help()
