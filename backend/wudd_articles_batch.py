"""Pull WUDD articles par batch — orchestration prioritisée (roadmap court terme).

Stratégie validée par le user : éviter les chargements massifs, préférer des
lots petits étalés. Convergence vers le corpus complet en ~50 jours.

Sélection (par ordre de priorité décroissante) :
1. **Favoris** non synchronisés depuis > `WUDD_BATCH_FAVORITES_REFRESH_DAYS`
   (défaut 7 jours) — le user veut les voir frais en premier.
2. **Top mentions** jamais synchronisés (initial fill) — meilleur signal/coût.
3. **Refresh entretien** : tous, ré-pull si > `WUDD_BATCH_REFRESH_DAYS` (30 j).

Côté worker : `wudd_articles_loop` poll `WUDD_BATCH_CYCLE_MINUTES` (défaut 60),
traite `WUDD_BATCH_ENTITIES_PER_CYCLE` entités (défaut 5). Soit 120 entités/jour
en mode standard. Marque `last_articles_synced_at` après chaque entité pour
exclure les déjà-traitées du cycle suivant.

Cap par entité : `WUDD_BATCH_ARTICLES_PER_ENTITY` (défaut 50, les plus récents
selon WUDD).

Endpoint manuel : `POST /admin/sync-wudd-articles-batch?count=N` pour déclencher
hors cycle (utile pour pousser les favoris).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from config import (
    WUDD_BATCH_ARTICLES_PER_ENTITY,
    WUDD_BATCH_ENTITIES_PER_CYCLE,
    WUDD_BATCH_FAVORITES_REFRESH_DAYS,
    WUDD_BATCH_REFRESH_DAYS,
)
from database import Entity, SessionLocal
from wudd_articles_sync import sync_articles_for_person

log = logging.getLogger("wudd_articles_batch")


def select_next_batch(n: int) -> list[tuple[int, str, str]]:
    """Sélectionne les `n` prochaines entités à traiter.

    Retourne une liste de tuples `(id, name, slug)` triés par priorité.
    Pour `name`, on préfère le **premier alias** car les articles WUDD sont
    indexés sur la forme naturelle "First Last", pas sur le canonique
    "Last, First" stocké en `entities.name`. Si pas d'alias, on rétro-convertit
    le canonique.
    """
    now = datetime.utcnow()
    fav_threshold = now - timedelta(days=WUDD_BATCH_FAVORITES_REFRESH_DAYS)
    refresh_threshold = now - timedelta(days=WUDD_BATCH_REFRESH_DAYS)

    db = SessionLocal()
    try:
        # 3 passes en cascade — on remplit jusqu'à `n`
        picks: list[Entity] = []

        # Pass 1 — favoris à rafraîchir
        if len(picks) < n:
            q = (
                select(Entity)
                .where(
                    Entity.is_favorite.is_(True),
                    or_(
                        Entity.last_articles_synced_at.is_(None),
                        Entity.last_articles_synced_at < fav_threshold,
                    ),
                )
                .order_by(Entity.wudd_mentions.desc().nulls_last())
                .limit(n - len(picks))
            )
            picks.extend(db.execute(q).scalars().all())

        # Pass 2 — top mentions jamais traités
        if len(picks) < n:
            already = {p.id for p in picks}
            q = (
                select(Entity)
                .where(
                    Entity.last_articles_synced_at.is_(None),
                    Entity.id.notin_(already) if already else True,
                )
                .order_by(Entity.wudd_mentions.desc().nulls_last())
                .limit(n - len(picks))
            )
            picks.extend(db.execute(q).scalars().all())

        # Pass 3 — refresh entretien (anciens)
        if len(picks) < n:
            already = {p.id for p in picks}
            q = (
                select(Entity)
                .where(
                    Entity.last_articles_synced_at < refresh_threshold,
                    Entity.id.notin_(already) if already else True,
                )
                .order_by(Entity.last_articles_synced_at.asc())
                .limit(n - len(picks))
            )
            picks.extend(db.execute(q).scalars().all())

        # Forme naturelle pour l'API WUDD (cf. /api/entities/articles?value=...)
        result = []
        for e in picks:
            value = _natural_name(e)
            result.append((e.id, value, e.slug))
        return result
    finally:
        db.close()


def _natural_name(entity: Entity) -> str:
    """Convertit le canonique 'Last, First' → 'First Last' attendu par WUDD.

    Si un alias existe (= la forme reçue depuis WUDD à l'origine), on le préfère.
    """
    aliases = list(entity.aliases)
    if aliases:
        # Premier alias = forme reçue depuis WUDD à l'ingestion
        return aliases[0].alias
    if "," in entity.name:
        parts = [p.strip() for p in entity.name.split(",", 1)]
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return entity.name


def run_batch(count: int | None = None) -> dict:
    """Traite un batch d'entités. Retourne un compte-rendu agrégé."""
    n = count if count is not None else WUDD_BATCH_ENTITIES_PER_CYCLE
    batch = select_next_batch(n)

    summary = {
        "selected": len(batch),
        "entities_processed": 0,
        "articles_new": 0,
        "articles_already": 0,
        "images_downloaded": 0,
        "details": [],
    }

    for entity_id, value, slug in batch:
        try:
            r = sync_articles_for_person(
                value, limit=WUDD_BATCH_ARTICLES_PER_ENTITY
            )
        except Exception as e:
            log.exception("batch entity %s (slug=%s) erreur", value, slug)
            summary["details"].append({"slug": slug, "error": str(e)})
            continue

        # Mark as synced même si 0 article (pour ne pas re-tenter immédiatement)
        db = SessionLocal()
        try:
            entity = db.get(Entity, entity_id)
            if entity is not None:
                entity.last_articles_synced_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

        summary["entities_processed"] += 1
        summary["articles_new"] += r.get("articles_new", 0)
        summary["articles_already"] += r.get("articles_already", 0)
        summary["images_downloaded"] += r.get("images_downloaded", 0)
        summary["details"].append({"slug": slug, "result": r})

    if summary["entities_processed"]:
        log.info("batch articles WUDD : %s", {
            k: v for k, v in summary.items() if k != "details"
        })
    return summary


def status() -> dict:
    """Métriques de progression : combien traité, combien restant, à rafraîchir."""
    now = datetime.utcnow()
    fav_threshold = now - timedelta(days=WUDD_BATCH_FAVORITES_REFRESH_DAYS)
    refresh_threshold = now - timedelta(days=WUDD_BATCH_REFRESH_DAYS)

    db = SessionLocal()
    try:
        from sqlalchemy import func

        total = db.scalar(select(func.count()).select_from(Entity)) or 0
        ever_synced = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(Entity.last_articles_synced_at.is_not(None))
            )
            or 0
        )
        favorites_to_refresh = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(
                    Entity.is_favorite.is_(True),
                    or_(
                        Entity.last_articles_synced_at.is_(None),
                        Entity.last_articles_synced_at < fav_threshold,
                    ),
                )
            )
            or 0
        )
        never_synced = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(Entity.last_articles_synced_at.is_(None))
            )
            or 0
        )
        stale = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(
                    Entity.last_articles_synced_at.is_not(None),
                    Entity.last_articles_synced_at < refresh_threshold,
                )
            )
            or 0
        )

        return {
            "total_entities": total,
            "ever_synced": ever_synced,
            "never_synced": never_synced,
            "favorites_to_refresh": favorites_to_refresh,
            "stale_to_refresh": stale,
            "config": {
                "entities_per_cycle": WUDD_BATCH_ENTITIES_PER_CYCLE,
                "articles_per_entity": WUDD_BATCH_ARTICLES_PER_ENTITY,
                "favorites_refresh_days": WUDD_BATCH_FAVORITES_REFRESH_DAYS,
                "refresh_days": WUDD_BATCH_REFRESH_DAYS,
            },
        }
    finally:
        db.close()
