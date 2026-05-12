"""Fusion d'entités doublons (spec §19, point ouvert "déduplication").

Trois cas couverts :

1. **Auto-merge par QID Wikidata** (`auto_merge_by_qid`) : si 2+ entités
   pointent vers le même `wikidata_qid`, c'est par construction la même
   personne — on fusionne sans intervention humaine. Cas typique observé :
   `Vance, J.D.` et `Vance, JD` → tous deux Q28935729.

2. **Merge manuel** (`merge_entities`) : décision humaine via endpoint
   `POST /entities/{canonical}/merge?source={duplicate}`. Pour les cas
   ambigus où Wikidata ne tranche pas (homonymes, formes courtes vs
   complètes). Les variantes "Zuckerberg" (Q21491489) et "Zuckerberg, Mark"
   (Q36215) sont ainsi traitables manuellement si le user juge qu'il s'agit
   en réalité de la même personne.

3. **Fusion par centroïde ArcFace** (à implémenter — pas dans ce module) :
   pour les cas où les QIDs diffèrent mais les centroïdes d'identité sont
   proches, suggérer la fusion.

Choix du canonical (pour l'auto-merge) : entité avec le plus d'images,
puis la plus complète (nom le plus long), puis la plus ancienne. Politique
explicite et déterministe.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, select, update

from config import MERGE_MAX_GROWTH_RATIO, MERGE_MIN_WIKIDATA_SCORE
from database import (
    ArticleEntity,
    Entity,
    EntityAlias,
    Image,
    SessionLocal,
)
from entity_stats import recompute_counts

log = logging.getLogger("entity_merge")


def merge_entities(canonical_id: int, duplicate_id: int) -> dict:
    """Fusionne `duplicate` dans `canonical`. Idempotent.

    - Toutes les images de duplicate → entity_id de canonical
    - Tous les liens article_entities de duplicate → canonical (collapse
      sur conflits de PK)
    - Le nom de duplicate + ses aliases → ajoutés comme aliases de canonical
    - Centroïde de canonical réinitialisé (recalcul au prochain audit_loop
      avec les images supplémentaires)
    - Compteurs recomputed
    - Duplicate supprimé en cascade

    Note : les fichiers (`local_path`/`aligned_path`) ne sont PAS déplacés
    sur disque — leur chemin reste valide tant que l'image existe en DB.
    """
    if canonical_id == duplicate_id:
        return {"status": "noop_same_entity"}

    db = SessionLocal()
    try:
        canonical = db.get(Entity, canonical_id)
        duplicate = db.get(Entity, duplicate_id)
        if canonical is None or duplicate is None:
            return {"status": "missing_entity"}

        canonical_name = canonical.name
        duplicate_name = duplicate.name

        # 1. Images : UPDATE en masse, SQL direct.
        # Important : on ne touche pas `duplicate.images` via l'ORM, sinon
        # SQLAlchemy tenterait de blank-out `entity_id` lors du delete final
        # (cf. note ci-dessous pour ArticleEntity, même mécanisme).
        images_moved = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.entity_id == duplicate.id)
        ) or 0
        if images_moved:
            db.execute(
                update(Image)
                .where(Image.entity_id == duplicate.id)
                .values(entity_id=canonical.id)
            )

        # 2. ArticleEntity — collapse en cas de conflit, SQL direct.
        #
        # **Pourquoi pas l'ORM ici.** ArticleEntity a une PK composite
        # (article_id, entity_id). Quand on modifie `link.entity_id` via
        # l'ORM, l'objet reste dans `duplicate.article_links` côté Python.
        # Au `db.delete(duplicate)` ci-dessous, SQLAlchemy itère sur cette
        # collection en mémoire et tente de "blank-out" `entity_id` des
        # enfants — interdit puisque c'est une colonne PK → AssertionError
        # "tried to blank-out primary key column". SQL direct contourne le
        # cache ORM.
        existing_article_ids = {
            row[0]
            for row in db.execute(
                select(ArticleEntity.article_id).where(
                    ArticleEntity.entity_id == canonical.id
                )
            )
        }
        duplicate_article_ids = {
            row[0]
            for row in db.execute(
                select(ArticleEntity.article_id).where(
                    ArticleEntity.entity_id == duplicate.id
                )
            )
        }
        to_collapse = duplicate_article_ids & existing_article_ids
        to_move = duplicate_article_ids - existing_article_ids
        if to_collapse:
            db.execute(
                delete(ArticleEntity).where(
                    ArticleEntity.entity_id == duplicate.id,
                    ArticleEntity.article_id.in_(to_collapse),
                )
            )
        if to_move:
            db.execute(
                update(ArticleEntity)
                .where(
                    ArticleEntity.entity_id == duplicate.id,
                    ArticleEntity.article_id.in_(to_move),
                )
                .values(entity_id=canonical.id)
            )
        links_moved = len(to_move)
        links_collapsed = len(to_collapse)

        # 3. Aliases : nom de duplicate + ses propres aliases
        existing_aliases = {a.alias for a in canonical.aliases}
        aliases_added = 0
        if duplicate_name not in existing_aliases:
            db.add(
                EntityAlias(
                    entity_id=canonical.id,
                    alias=duplicate_name,
                    source="merge",
                )
            )
            existing_aliases.add(duplicate_name)
            aliases_added += 1
        for a in list(duplicate.aliases):
            if a.alias not in existing_aliases:
                db.add(
                    EntityAlias(
                        entity_id=canonical.id,
                        alias=a.alias,
                        source=a.source or "merge",
                    )
                )
                existing_aliases.add(a.alias)
                aliases_added += 1

        # 4. Reset centroïde canonical pour recalcul propre
        canonical.identity_centroid = None
        canonical.identity_count = 0

        # 5. Vider le cache ORM de duplicate.
        # On a fait les UPDATE en SQL direct (étapes 1 et 2), donc les
        # collections `duplicate.images` et `duplicate.article_links` chargées
        # plus tôt (ou paresseusement) sont obsolètes. Expirer force un
        # rechargement lazy au prochain accès — au `delete(duplicate)` les
        # collections seront vues vides (les FK pointent désormais vers
        # canonical), et SQLAlchemy n'essaiera pas de blank-out.
        db.expire(duplicate)

        # 6. Suppression duplicate (cascade aliases ORM)
        db.delete(duplicate)
        db.commit()
    finally:
        db.close()

    # 6. Recompute counts hors session
    recompute_counts(canonical_id)

    return {
        "status": "merged",
        "canonical_name": canonical_name,
        "duplicate_name": duplicate_name,
        "images_moved": images_moved,
        "article_links_moved": links_moved,
        "article_links_collapsed": links_collapsed,
        "aliases_added": aliases_added,
    }


def find_qid_duplicate_groups() -> list[tuple[int, list[int]]]:
    """Renvoie les groupes [(canonical_id, [duplicate_ids])] partageant un QID.

    Tri par : (a) plus d'images, (b) nom plus long (proxy "plus complet"),
    (c) première vue. La première de chaque groupe est `canonical`.
    """
    db = SessionLocal()
    try:
        qids = [
            row[0]
            for row in db.execute(
                select(Entity.wikidata_qid)
                .where(Entity.wikidata_qid.is_not(None))
                .group_by(Entity.wikidata_qid)
                .having(func.count() > 1)
            )
        ]
        groups: list[tuple[int, list[int]]] = []
        for qid in qids:
            entities = db.execute(
                select(Entity)
                .where(Entity.wikidata_qid == qid)
                .order_by(
                    Entity.image_count.desc(),
                    func.length(Entity.name).desc(),
                    Entity.first_seen.asc(),
                )
            ).scalars().all()
            if len(entities) >= 2:
                groups.append((entities[0].id, [e.id for e in entities[1:]]))
        return groups
    finally:
        db.close()


def _check_auto_merge_safe(
    canonical: Entity, duplicate: Entity
) -> tuple[bool, str | None]:
    """Garde-fous incident 2026-05-11.

    Refuse l'auto-fusion si :
    - le canonical grossirait de plus de `MERGE_MAX_GROWTH_RATIO` en une fois
      (un QID corrompu génère typiquement un saut massif de l'image_count)
    - un des deux scores Wikidata est inférieur à `MERGE_MIN_WIKIDATA_SCORE`
      (un label inexact = trop d'incertitude pour une opération irréversible)

    Retourne (autorise, raison_si_refus). Les conflits refusés restent listés
    dans `find_qid_duplicate_groups` et visibles via `/admin/merge-conflicts`.
    Le merge manuel via `merge_entities` reste accessible — c'est une décision
    humaine, pas auto.
    """
    canon_count = canonical.image_count or 0
    dup_count = duplicate.image_count or 0
    if canon_count > 0:
        projected_ratio = (canon_count + dup_count) / canon_count
        if projected_ratio > MERGE_MAX_GROWTH_RATIO:
            return False, (
                f"growth_ratio {projected_ratio:.2f} > {MERGE_MAX_GROWTH_RATIO} "
                f"(canonical={canon_count}, duplicate={dup_count})"
            )

    for ent, role in ((canonical, "canonical"), (duplicate, "duplicate")):
        score = ent.wikidata_score
        if score is None or score < MERGE_MIN_WIKIDATA_SCORE:
            return False, (
                f"{role} wikidata_score={score} < {MERGE_MIN_WIKIDATA_SCORE} "
                f"(entity={ent.slug}, qid={ent.wikidata_qid})"
            )

    return True, None


def find_blocked_merge_conflicts() -> list[dict]:
    """Liste les groupes QID en doublon qui sont actuellement bloqués par
    le garde-fou. Sert au diagnostic et à la décision manuelle.
    """
    blocked: list[dict] = []
    db = SessionLocal()
    try:
        for canonical_id, dup_ids in find_qid_duplicate_groups():
            canonical = db.get(Entity, canonical_id)
            if canonical is None:
                continue
            for dup_id in dup_ids:
                duplicate = db.get(Entity, dup_id)
                if duplicate is None:
                    continue
                ok, reason = _check_auto_merge_safe(canonical, duplicate)
                if not ok:
                    blocked.append({
                        "canonical": {
                            "id": canonical.id,
                            "slug": canonical.slug,
                            "name": canonical.name,
                            "image_count": canonical.image_count,
                            "wikidata_qid": canonical.wikidata_qid,
                            "wikidata_score": canonical.wikidata_score,
                        },
                        "duplicate": {
                            "id": duplicate.id,
                            "slug": duplicate.slug,
                            "name": duplicate.name,
                            "image_count": duplicate.image_count,
                            "wikidata_qid": duplicate.wikidata_qid,
                            "wikidata_score": duplicate.wikidata_score,
                        },
                        "reason": reason,
                    })
        return blocked
    finally:
        db.close()


def auto_merge_by_qid() -> dict:
    """Fusionne automatiquement toutes les entités au même QID Wikidata.

    Soumis à `_check_auto_merge_safe` (cf. incident 2026-05-11). Les paires
    bloquées sont comptées dans `blocked` et restent visibles via
    `find_blocked_merge_conflicts` / endpoint `/admin/merge-conflicts`.
    """
    summary = {"groups": 0, "merged": 0, "blocked": 0, "details": [], "blocks": []}
    for canonical_id, duplicate_ids in find_qid_duplicate_groups():
        summary["groups"] += 1
        # On charge canonical une fois ; image_count peut évoluer si une
        # première fusion du groupe a réussi, on relit donc à chaque itération.
        for dup_id in duplicate_ids:
            db = SessionLocal()
            try:
                canonical = db.get(Entity, canonical_id)
                duplicate = db.get(Entity, dup_id)
                if canonical is None or duplicate is None:
                    continue
                ok, reason = _check_auto_merge_safe(canonical, duplicate)
                canonical_name = canonical.name
                duplicate_name = duplicate.name
                duplicate_slug = duplicate.slug
            finally:
                db.close()

            if not ok:
                summary["blocked"] += 1
                summary["blocks"].append({
                    "canonical_id": canonical_id,
                    "duplicate_id": dup_id,
                    "duplicate_slug": duplicate_slug,
                    "reason": reason,
                })
                log.warning(
                    "auto-merge BLOQUÉ : %s → %s (%s)",
                    duplicate_name,
                    canonical_name,
                    reason,
                )
                continue

            r = merge_entities(canonical_id, dup_id)
            if r.get("status") == "merged":
                summary["merged"] += 1
                summary["details"].append(
                    f"{r['duplicate_name']} → {r['canonical_name']}"
                )
                log.info(
                    "auto-merge OK : %s → %s (images +%d)",
                    r["duplicate_name"],
                    r["canonical_name"],
                    r.get("images_moved", 0),
                )
    if summary["merged"] or summary["blocked"]:
        log.info(
            "auto-merge QID : %d fusionnées, %d bloquées",
            summary["merged"],
            summary["blocked"],
        )
    return summary
