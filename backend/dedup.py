"""Déduplication par pHash + score de diversité (spec §11).

Pipeline :
1. **Calcul d'empreintes** : pour chaque image alignée sans `embedding`,
   on calcule le pHash 64 bits (`embeddings.compute_embedding`).
2. **Déduplication par entité** : pour toutes les paires (i, j) non-doublons
   avec i antérieur à j, si la distance Hamming normalisée est sous seuil,
   j est marqué doublon de i. La plus ancienne reste canonique pour
   préserver le contexte du premier scrape.
3. **Score de diversité** : moyenne des distances pairwise entre images
   uniques (non-doublons). 0 = toutes identiques, valeurs autour de 0.3–0.5
   = couverture variée. Stocké dans `entities.diversity_score`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select, update

from database import Entity, Image, SessionLocal
from embeddings import compute_embedding, embedding_distance, serialize
from entity_stats import recompute_counts

DUP_THRESHOLD = 0.08  # ≈ 5 bits sur 64 — copies, ré-encodages, redimensionnements

log = logging.getLogger("dedup")


def compute_missing_embeddings(limit: int = 20) -> int:
    """Calcule l'embedding pour les images alignées qui n'en ont pas. Retourne le nombre traité."""
    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.execute(
                select(Image.id)
                .where(
                    Image.aligned_path.is_not(None),
                    Image.embedding.is_(None),
                )
                .limit(limit)
            )
        ]
    finally:
        db.close()

    n_done = 0
    for image_id in ids:
        db = SessionLocal()
        try:
            img = db.get(Image, image_id)
            if not img or not img.aligned_path:
                continue
            emb = compute_embedding(Path(img.aligned_path))
            if emb is None:
                continue
            img.embedding = serialize(emb)
            db.commit()
            n_done += 1
        finally:
            db.close()
    return n_done


def dedup_entity(entity_id: int) -> dict:
    """Marque les doublons et calcule le score de diversité."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Image.id, Image.embedding)
            .where(
                Image.entity_id == entity_id,
                Image.embedding.is_not(None),
            )
            .order_by(Image.scraped_at)  # canonique = plus ancienne
        ).all()

        if len(rows) < 2:
            return {"checked": len(rows), "marked": 0, "diversity": None}

        ids = [r[0] for r in rows]
        hashes = [r[1] for r in rows]
        n = len(ids)

        # Matrice de distances pairwise. Pour de petits n (≤ 50/entité),
        # O(n²) tient en moins de 10 ms.
        dist = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                d = embedding_distance(hashes[i], hashes[j])
                dist[i][j] = d
                dist[j][i] = d

        # Marquage : pour chaque j, premier i antérieur (i < j) sous seuil
        # et qui n'est pas lui-même un doublon (préservation de la chaîne)
        canonical_for: dict[int, int] = {}
        for j in range(1, n):
            for i in range(j):
                if i in canonical_for:
                    continue
                if dist[i][j] < DUP_THRESHOLD:
                    canonical_for[j] = i
                    break

        # Reset puis ré-écrit l'état de dedup pour cette entité (idempotent)
        db.execute(
            update(Image)
            .where(Image.entity_id == entity_id)
            .values(is_duplicate=False, duplicate_of=None)
        )
        for j, i in canonical_for.items():
            db.execute(
                update(Image)
                .where(Image.id == ids[j])
                .values(is_duplicate=True, duplicate_of=ids[i])
            )

        # Diversité : moyenne des distances pairwise entre uniques
        unique_idx = [i for i in range(n) if i not in canonical_for]
        if len(unique_idx) >= 2:
            pair_dists = [
                dist[a][b]
                for x, a in enumerate(unique_idx)
                for b in unique_idx[x + 1 :]
            ]
            diversity = sum(pair_dists) / len(pair_dists)
        else:
            diversity = 0.0

        db.execute(
            update(Entity)
            .where(Entity.id == entity_id)
            .values(diversity_score=round(diversity, 4))
        )
        db.commit()
    finally:
        db.close()

    # Les compteurs sont recalculés après la fermeture de la session pour
    # être sûr que les UPDATE is_duplicate ci-dessus sont visibles. La fonction
    # gère sa propre session.
    recompute_counts(entity_id)

    return {
        "checked": n,
        "marked": len(canonical_for),
        "diversity": round(diversity, 4),
    }


def dedup_all_entities() -> dict:
    """Repasse la dedup sur toutes les entités ayant >= 2 images avec embedding."""
    db = SessionLocal()
    try:
        # Sous-requête : entités avec au moins 1 image embeddée
        with_embedding_subq = (
            select(Image.entity_id)
            .where(Image.embedding.is_not(None))
            .scalar_subquery()
        )
        entity_ids = [
            row[0]
            for row in db.execute(
                select(Entity.id).where(Entity.id.in_(with_embedding_subq))
            )
        ]
    finally:
        db.close()

    summary = {"entities": 0, "marked_total": 0}
    for eid in entity_ids:
        r = dedup_entity(eid)
        summary["entities"] += 1
        summary["marked_total"] += r["marked"]
    return summary
