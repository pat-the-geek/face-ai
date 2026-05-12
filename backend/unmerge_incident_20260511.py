"""Démerge de l'incident du 2026-05-11 — Musk/Zuckerberg/McCartney
réabsorbés dans Altman par auto_merge_by_qid sur QID corrompu.

Stratégie :
- Recréer les 3 entités séparées (QID corrects)
- Réattribuer images sur la base des captions (les ambigus restent sur
  Altman en `flagged` pour audit manuel via /audit)
- Ajouter les liens article→nouvelle_entité (sans toucher les liens
  article→Altman existants — beaucoup sont légitimes : affaires OpenAI vs Musk, etc.)
- Migrer les aliases erronés de Altman vers leurs nouvelles entités
- Reset centroïde Altman (pollué) → recalcul au prochain audit
- recompute_counts sur les 4 entités

Ne touche PAS aux fichiers disque (local_path/aligned_path restent valides).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update

from database import (
    ArticleEntity,
    Entity,
    EntityAlias,
    Image,
    SessionLocal,
)
from entity_stats import recompute_counts


RESTORATIONS = [
    {
        "name": "Musk, Elon",
        "slug": "elon-musk",
        "qid": "Q317521",
        "aliases": ["Elon Musk", "Musk", "Musk, Elon"],
        "caption_pattern_pos": ["Musk", "musk"],
        "caption_pattern_excl": ["Zuckerberg", "zuckerberg", "McCartney", "mccartney"],
    },
    {
        "name": "Zuckerberg, Mark",
        "slug": "mark-zuckerberg",
        "qid": "Q36215",
        "aliases": ["Mark Zuckerberg", "Zuckerberg", "Zuckerberg, Mark"],
        "caption_pattern_pos": ["Zuckerberg", "zuckerberg"],
        "caption_pattern_excl": ["Musk", "musk", "McCartney", "mccartney"],
    },
    {
        "name": "McCartney, Paul",
        "slug": "paul-mccartney",
        "qid": "Q2599",
        "aliases": ["Paul McCartney", "McCartney", "McCartney, Paul"],
        "caption_pattern_pos": ["McCartney", "mccartney"],
        "caption_pattern_excl": ["Musk", "musk", "Zuckerberg", "zuckerberg"],
    },
]

ALTMAN_SLUG = "sam-altman"


def caption_matches(caption: str | None, pos: list[str], excl: list[str]) -> bool:
    if not caption:
        return False
    if not any(p in caption for p in pos):
        return False
    if any(e in caption for e in excl):
        return False
    return True


def run() -> dict:
    report: dict = {"started_at": datetime.utcnow().isoformat()}
    db = SessionLocal()
    try:
        altman = db.scalar(select(Entity).where(Entity.slug == ALTMAN_SLUG))
        if altman is None:
            raise RuntimeError("sam-altman introuvable, abandon")
        report["altman_id"] = altman.id

        created = []
        for spec in RESTORATIONS:
            existing = db.scalar(select(Entity).where(Entity.slug == spec["slug"]))
            if existing is not None:
                created.append({"slug": spec["slug"], "id": existing.id, "status": "already_exists"})
                spec["_id"] = existing.id
                continue
            e = Entity(
                name=spec["name"],
                slug=spec["slug"],
                wikidata_qid=spec["qid"],
                wikidata_status="pending",  # le worker ré-enrichira via Wikimedia
                first_seen=datetime.utcnow(),
            )
            db.add(e)
            db.flush()
            spec["_id"] = e.id
            created.append({"slug": spec["slug"], "id": e.id, "status": "created"})
        report["entities_created"] = created

        # Lister images d'Altman et trier par caption
        altman_images = db.scalars(
            select(Image).where(Image.entity_id == altman.id)
        ).all()

        reattributions: dict[str, list[int]] = {s["slug"]: [] for s in RESTORATIONS}
        ambiguous: list[int] = []
        kept_altman: list[int] = []

        for img in altman_images:
            target = None
            for spec in RESTORATIONS:
                if caption_matches(img.caption, spec["caption_pattern_pos"], spec["caption_pattern_excl"]):
                    target = spec
                    break
            if target is not None:
                reattributions[target["slug"]].append(img.id)
            else:
                # Multi-mention ? Détecter
                names = {"musk": False, "zuck": False, "mc": False}
                if img.caption:
                    names["musk"] = "Musk" in img.caption or "musk" in img.caption
                    names["zuck"] = "Zuckerberg" in img.caption or "zuckerberg" in img.caption
                    names["mc"] = "McCartney" in img.caption or "mccartney" in img.caption
                if sum(names.values()) >= 2:
                    ambiguous.append(img.id)
                else:
                    kept_altman.append(img.id)

        report["reattributions"] = {k: len(v) for k, v in reattributions.items()}
        report["ambiguous_kept_on_altman"] = len(ambiguous)
        report["true_altman"] = len(kept_altman)

        # Exécuter les réattributions
        article_ids_per_entity: dict[int, set[int]] = {}
        for spec in RESTORATIONS:
            ids = reattributions[spec["slug"]]
            if not ids:
                continue
            db.execute(
                update(Image)
                .where(Image.id.in_(ids))
                .values(entity_id=spec["_id"], association_status="auto")
            )
            article_ids = {
                row[0] for row in db.execute(
                    select(Image.article_id).where(Image.id.in_(ids))
                ) if row[0] is not None
            }
            article_ids_per_entity[spec["_id"]] = article_ids

        # Ambigus : forcer en flagged pour audit manuel
        if ambiguous:
            db.execute(
                update(Image)
                .where(Image.id.in_(ambiguous))
                .values(association_status="flagged")
            )

        # Ajouter article_entities pour les nouvelles entités (INSERT OR IGNORE)
        for new_entity_id, article_ids in article_ids_per_entity.items():
            existing_links = {
                row[0] for row in db.execute(
                    select(ArticleEntity.article_id)
                    .where(ArticleEntity.entity_id == new_entity_id)
                )
            }
            to_create = article_ids - existing_links
            for aid in to_create:
                db.add(ArticleEntity(article_id=aid, entity_id=new_entity_id, confidence=1.0))

        # Migrer les aliases erronés
        # On garde sur Altman : 'Altman', 'Sam Altman', 'Samuel H. Altman'
        # Tout le reste qui matche les noms des 3 cibles → migration
        altman_aliases = db.scalars(
            select(EntityAlias).where(EntityAlias.entity_id == altman.id)
        ).all()
        migrated_aliases = []
        for alias_row in altman_aliases:
            for spec in RESTORATIONS:
                if alias_row.alias in spec["aliases"]:
                    # Vérifier que l'alias n'existe pas déjà sur la cible
                    existing = db.scalar(
                        select(EntityAlias).where(
                            EntityAlias.entity_id == spec["_id"],
                            EntityAlias.alias == alias_row.alias,
                        )
                    )
                    if existing is None:
                        alias_row.entity_id = spec["_id"]
                        migrated_aliases.append({"alias": alias_row.alias, "to": spec["slug"]})
                    else:
                        db.delete(alias_row)
                        migrated_aliases.append({"alias": alias_row.alias, "to": spec["slug"], "deduped": True})
                    break
        report["aliases_migrated"] = migrated_aliases

        # Reset centroïde Altman (pollué)
        altman.identity_centroid = None
        altman.identity_count = 0

        # Reset centroïde des nouvelles entités (sera calculé au prochain audit)
        for spec in RESTORATIONS:
            ent = db.get(Entity, spec["_id"])
            ent.identity_centroid = None
            ent.identity_count = 0

        db.commit()
    finally:
        db.close()

    # Recompute counts hors session
    recomputes = {}
    altman_id = report["altman_id"]
    for spec in RESTORATIONS:
        recomputes[spec["slug"]] = recompute_counts(spec["_id"])
    recomputes[ALTMAN_SLUG] = recompute_counts(altman_id)
    report["recomputes"] = recomputes
    report["finished_at"] = datetime.utcnow().isoformat()
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
