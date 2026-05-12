"""Fusion d'entités par proximité de centroïde ArcFace (spec roadmap moyen).

Complémentaire à `entity_merge.auto_merge_by_qid` :
- L'auto-merge par QID résout les variantes de nommage (`Vance, JD` /
  `Vance, J.D.` pointent sur le même Q28935729).
- Cette fusion-ci résout les **homonymes Wikidata** : deux entités
  Wikidata distinctes qui sont en réalité la même personne (ex.
  `Zuckerberg` Q21491489 redirect vs `Zuckerberg, Mark` Q36215 — QIDs
  différents mais centroïdes ArcFace identiques).

Approche : pour chaque paire (A, B) d'entités avec centroïde calculé,
on mesure la distance cosine entre centroïdes. Si :
- `< AUTO_MERGE_DISTANCE` (0.30) : candidate auto-merge (mais soumis au
  même garde-fou de croissance que `entity_merge.auto_merge_by_qid`)
- `< SUGGEST_DISTANCE` (0.45) : suggéré pour décision manuelle

**Coût** : O(n²) sur n entités avec centroïde. À 1100 entités, ~600k
paires à évaluer (≤ 2s). Au-delà de 10k, faudra une indexation type
ANN (FAISS, HNSW).

**Risques** :
- Vrais frères / sosies / vieillissement extrême peuvent donner des
  distances proches. C'est pourquoi le seuil 0.30 est strict (le seuil
  d'audit `identity_audit` est 0.55 entre image et centroïde, donc deux
  centroïdes < 0.30 sont franchement plus suspects).
- Le garde-fou de croissance bloque les fusions qui doubleraient le
  canonical en une fois (même règle que `auto_merge_by_qid`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from config import (
    CENTROID_AUTO_DISTANCE,
    CENTROID_MIN_IMAGES,
    CENTROID_SUGGEST_DISTANCE,
    MERGE_MAX_GROWTH_RATIO,
)
from database import Entity, SessionLocal
from identity import cosine_distance, deserialize

log = logging.getLogger("centroid_merge")

# Seuils calibrés conservativement (cf. config.py pour overrides env).
# CENTROID_AUTO_DISTANCE = 0.20 : distance suffisamment faible pour
# considérer auto. CENTROID_SUGGEST_DISTANCE = 0.45 : zone de
# suggestion pour décision humaine (frères, sosies tombent ~0.4–0.6).
# CENTROID_MIN_IMAGES = 5 : sous ce seuil le centroïde est trop bruité
# pour servir de référence (cas Mark Hamill 1 image → matche Trump par
# accident — observé live).
AUTO_MERGE_DISTANCE = CENTROID_AUTO_DISTANCE
SUGGEST_DISTANCE = CENTROID_SUGGEST_DISTANCE
MIN_IMAGES = CENTROID_MIN_IMAGES


@dataclass
class CentroidPair:
    canonical_id: int
    canonical_slug: str
    canonical_name: str
    canonical_image_count: int
    duplicate_id: int
    duplicate_slug: str
    duplicate_name: str
    duplicate_image_count: int
    distance: float
    can_auto: bool
    block_reason: str | None


def _load_entities_with_centroid() -> list[tuple[Entity, np.ndarray]]:
    """Retourne `(entity, centroid_np)` pour toutes les entités qui ont
    un centroïde calculé. Charge tout en mémoire — économe vu la taille
    (512 floats × 8 bytes = 4 KB par entité, ~5 MB à 1100 entités).
    """
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Entity).where(
                Entity.identity_centroid.is_not(None),
                # Exclure les tombstones not_person — pas de fusion
                # possible avec une row qui n'a plus d'images.
                Entity.wikidata_status != "not_person",
            )
        ).all()
        # Force le chargement des champs avant fermeture de la session
        out = []
        for e in rows:
            centroid = deserialize(e.identity_centroid)
            out.append((e, centroid))
        return out
    finally:
        db.close()


def find_candidate_pairs(
    max_distance: float = SUGGEST_DISTANCE,
    min_images: int | None = None,
) -> list[CentroidPair]:
    """Retourne toutes les paires d'entités dont les centroïdes sont à
    distance ≤ `max_distance`. Triées par distance ascendante (les plus
    suspectes en premier).

    Exclut :
    - Les paires qui ont déjà le même QID (déjà géré par
      `auto_merge_by_qid` — ce module cible les homonymes Wikidata)
    - Les entités avec < `min_images` images : leur centroïde n'est pas
      fiable (cf. `CENTROID_MIN_IMAGES`). Le faux match observé
      `donald-trump ← mark-hamill` à d=0.20 venait de Hamill = 1 image.

    `min_images=0` désactive le filtre (utile pour tests).
    """
    threshold = MIN_IMAGES if min_images is None else min_images

    pairs: list[CentroidPair] = []
    loaded = _load_entities_with_centroid()
    n = len(loaded)

    for i in range(n):
        e_a, c_a = loaded[i]
        if (e_a.image_count or 0) < threshold:
            continue
        for j in range(i + 1, n):
            e_b, c_b = loaded[j]
            if (e_b.image_count or 0) < threshold:
                continue
            # Skip si même QID — c'est le territoire de auto_merge_by_qid
            if (
                e_a.wikidata_qid
                and e_b.wikidata_qid
                and e_a.wikidata_qid == e_b.wikidata_qid
            ):
                continue

            dist = cosine_distance(c_a, c_b)
            if dist > max_distance:
                continue

            # Élit canonical = celui avec le plus d'images (ou la plus
            # ancienne si égalité). Cohérent avec auto_merge_by_qid.
            if (e_a.image_count or 0) >= (e_b.image_count or 0):
                canonical, duplicate = e_a, e_b
            else:
                canonical, duplicate = e_b, e_a

            can_auto, block_reason = _check_safe_auto(
                canonical, duplicate, dist,
            )

            pairs.append(
                CentroidPair(
                    canonical_id=canonical.id,
                    canonical_slug=canonical.slug,
                    canonical_name=canonical.name,
                    canonical_image_count=canonical.image_count or 0,
                    duplicate_id=duplicate.id,
                    duplicate_slug=duplicate.slug,
                    duplicate_name=duplicate.name,
                    duplicate_image_count=duplicate.image_count or 0,
                    distance=dist,
                    can_auto=can_auto,
                    block_reason=block_reason,
                )
            )

    pairs.sort(key=lambda p: p.distance)
    return pairs


def _check_safe_auto(
    canonical: Entity, duplicate: Entity, distance: float,
) -> tuple[bool, str | None]:
    """Auto-merge si :
    - distance ≤ AUTO_MERGE_DISTANCE
    - growth ratio respecte MERGE_MAX_GROWTH_RATIO (≈ règle entity_merge)

    Sinon manuel ; on retourne la raison pour exposition côté UI/admin.
    """
    if distance > AUTO_MERGE_DISTANCE:
        return False, (
            f"distance {distance:.3f} > seuil auto {AUTO_MERGE_DISTANCE} "
            f"(suggéré pour décision manuelle)"
        )

    canon_n = canonical.image_count or 0
    dup_n = duplicate.image_count or 0
    if canon_n > 0:
        projected = (canon_n + dup_n) / canon_n
        if projected > MERGE_MAX_GROWTH_RATIO:
            return False, (
                f"growth_ratio {projected:.2f} > {MERGE_MAX_GROWTH_RATIO} "
                f"(canonical={canon_n}, duplicate={dup_n})"
            )

    return True, None


def auto_merge_by_centroid() -> dict:
    """Tour de boucle — examine toutes les paires < AUTO_MERGE_DISTANCE
    et fusionne celles qui passent le garde-fou.

    Retourne un summary similaire à `auto_merge_by_qid`.
    """
    from entity_merge import merge_entities

    summary = {"checked": 0, "merged": 0, "blocked": 0, "details": [], "blocks": []}
    pairs = find_candidate_pairs(max_distance=AUTO_MERGE_DISTANCE)
    summary["checked"] = len(pairs)

    for p in pairs:
        if not p.can_auto:
            summary["blocked"] += 1
            summary["blocks"].append({
                "canonical_slug": p.canonical_slug,
                "duplicate_slug": p.duplicate_slug,
                "distance": p.distance,
                "reason": p.block_reason,
            })
            log.warning(
                "centroid auto-merge BLOQUÉ : %s ← %s (d=%.3f, %s)",
                p.canonical_slug,
                p.duplicate_slug,
                p.distance,
                p.block_reason,
            )
            continue

        r = merge_entities(p.canonical_id, p.duplicate_id)
        if r.get("status") == "merged":
            summary["merged"] += 1
            summary["details"].append({
                "canonical_slug": p.canonical_slug,
                "duplicate_slug": p.duplicate_slug,
                "distance": p.distance,
            })
            log.info(
                "centroid auto-merge OK : %s ← %s (d=%.3f)",
                p.canonical_slug,
                p.duplicate_slug,
                p.distance,
            )

    return summary
