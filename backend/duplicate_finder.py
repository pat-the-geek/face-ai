"""Détection d'entités probablement doublons à fusionner.

Trois catégories signalées :

1. **same_qid** : entités partageant un `wikidata_qid` non-null → auto-mergeables
   par `entity_merge.auto_merge_by_qid` (worker poll 2 min). Si on en voit ici,
   c'est que le worker est arrêté ou que `merge_loop` plante.

2. **same_surname** : entités dont le nom canonique partage le même "nom de
   famille" (segment avant la virgule, ou le nom entier si pas de virgule).
   Cas typique : `Trump, Donald` vs `Trump` — même personne en notation
   longue/courte. **Faux positifs attendus** pour les homonymes légitimes
   (Macron Emmanuel vs Macron Brigitte) — la décision est humaine.

3. **alias_collision** : entités dont le nom correspond exactement à un alias
   d'une autre entité → indique une fusion ratée ou une canonicalisation
   incohérente.

Module pur (pas d'effets de bord). Consommé par :
- `face_ai_mcp_server.find_duplicate_candidates` (outil MCP)
- `api.py` `GET /entities/duplicate-candidates` (UI /audit)
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select

from database import Entity, EntityAlias, SessionLocal


def find_candidates(limit: int = 30) -> dict:
    """Retourne les trois listes de candidats. Tri par poids décroissant
    (somme image_count) pour `same_surname`."""
    db = SessionLocal()
    try:
        # Tombstones not_person : exclus de toutes les détections — on n'a
        # rien à fusionner sur ces faux PERSON, ils sont déjà neutralisés
        # côté navigation (api._exclude_not_person).
        not_person = "not_person"

        # 1. Same QID
        qid_rows = db.execute(
            select(Entity.wikidata_qid)
            .where(
                Entity.wikidata_qid.is_not(None),
                (Entity.wikidata_status.is_(None))
                | (Entity.wikidata_status != not_person),
            )
            .group_by(Entity.wikidata_qid)
            .having(func.count() > 1)
            .limit(limit)
        ).all()
        same_qid = []
        for (qid,) in qid_rows:
            members = db.execute(
                select(Entity.slug, Entity.name, Entity.image_count)
                .where(
                    Entity.wikidata_qid == qid,
                    (Entity.wikidata_status.is_(None))
                    | (Entity.wikidata_status != not_person),
                )
                .order_by(Entity.image_count.desc(), Entity.name)
            ).all()
            same_qid.append(
                {
                    "qid": qid,
                    "entities": [
                        {"slug": m[0], "name": m[1], "image_count": m[2] or 0}
                        for m in members
                    ],
                }
            )

        # 2. Same surname — segment avant la virgule du nom canonique,
        # ou le nom entier si mono-token.
        entities = db.execute(
            select(Entity.id, Entity.slug, Entity.name, Entity.image_count)
            .where(
                (Entity.wikidata_status.is_(None))
                | (Entity.wikidata_status != not_person),
            )
        ).all()
        surname_buckets: dict[str, list[dict]] = defaultdict(list)
        for _eid, slug, name, count in entities:
            if not name:
                continue
            surname = (name.split(",")[0] if "," in name else name).strip().lower()
            if not surname:
                continue
            surname_buckets[surname].append(
                {"slug": slug, "name": name, "image_count": count or 0}
            )
        same_surname = []
        for surname, members in surname_buckets.items():
            if len(members) < 2:
                continue
            members.sort(key=lambda m: (-m["image_count"], m["name"]))
            same_surname.append({"surname": surname, "entities": members})
        same_surname.sort(
            key=lambda g: -sum(m["image_count"] for m in g["entities"])
        )
        same_surname = same_surname[:limit]

        # 3. Alias collision — un nom d'entité = un alias d'une autre entité
        alias_rows = db.execute(
            select(EntityAlias.alias, EntityAlias.entity_id)
        ).all()
        alias_to_owner: dict[str, int] = {a: eid for a, eid in alias_rows}
        alias_collisions = []
        seen_pairs: set[tuple[int, int]] = set()
        for eid, slug, name, count in entities:
            owner = alias_to_owner.get(name)
            if owner is None or owner == eid:
                continue
            pair = tuple(sorted([eid, owner]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            other = next(
                (e for e in entities if e[0] == owner), None
            )
            if other is None:
                continue
            this_member = {"slug": slug, "name": name, "image_count": count or 0}
            other_member = {
                "slug": other[1],
                "name": other[2],
                "image_count": other[3] or 0,
            }
            # canonical = celui avec le plus d'images en premier
            pair_sorted = sorted(
                [this_member, other_member],
                key=lambda m: (-m["image_count"], m["name"]),
            )
            alias_collisions.append(
                {"collision_on": name, "entities": pair_sorted}
            )
        alias_collisions = alias_collisions[:limit]

        return {
            "same_qid": same_qid,
            "same_surname": same_surname,
            "alias_collision": alias_collisions,
            "totals": {
                "same_qid_groups": len(same_qid),
                "same_surname_groups": len(same_surname),
                "alias_collision_groups": len(alias_collisions),
            },
        }
    finally:
        db.close()
