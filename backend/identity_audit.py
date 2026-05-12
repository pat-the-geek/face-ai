"""Orchestration de la vérification d'identité (spec §11.2).

Trois passes successives, idempotentes :

1. **compute_missing_identities** : pour chaque image téléchargée sans
   `identity_embedding`, calcule le vecteur ArcFace via InsightFace.
   Skippe silencieusement les images où aucun visage n'est détecté à ce
   niveau (RetinaFace plus exigeant que MediaPipe Face Mesh — cas typique :
   visage très flou, vue de dos, ou silhouette).

2. **update_centroids** : pour chaque entité avec ≥1 image embeddée, calcule
   le centroïde = moyenne des embeddings non-`flagged` (pour ne pas polluer
   la référence avec de mauvaises associations) puis re-normalise L2.

3. **audit_associations** : pour chaque image avec embedding ET dont l'entité
   a un centroïde, calcule la distance cosine. Met à jour
   `images.identity_match_score` et bascule `association_status` :
   `auto` → `confirmed` si distance ≤ seuil, sinon `flagged`.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from sqlalchemy import or_, select, update
from sqlalchemy.orm.exc import StaleDataError

from database import Entity, Image, SessionLocal
from identity import (
    IDENTITY_THRESHOLD,
    compute_identity,
    cosine_distance,
    deserialize,
    serialize,
)

log = logging.getLogger("identity_audit")


def compute_missing_identities(limit: int = 20) -> dict:
    """Calcule l'embedding ArcFace ; purge si RetinaFace ne voit pas de visage humain.

    Extension de la règle §5.4 (validation en cascade) : MediaPipe Face Mesh
    accepte les visages stylisés (logos, icônes, illustrations) parce qu'il
    détecte des patterns visuels semblables à un visage. RetinaFace
    (InsightFace) est entraîné spécifiquement sur des visages humains réels
    et rejette ces faux positifs.

    Si RetinaFace ne trouve pas de visage dans une image alignée par MediaPipe,
    c'est par construction une fausse détection MediaPipe → on purge.

    Cas typiques attrapés : icônes d'app ressemblant à un visage cartoon,
    pictogrammes "18+" + main, captures d'écran d'interfaces.

    **Sélection** : on filtre sur `analysis_status='done'` pour ne traiter
    que les images déjà validées par `face_processor`. Sinon on se retrouve
    en course avec `analyze_loop` : les deux boucles ciblent la même image,
    `analyze_loop` peut purger l'image pendant que `compute_identity` (1–2 s
    InsightFace) tourne ici, et le commit suivant lève `StaleDataError`
    parce que la row n'existe plus.

    Retourne `{"done": N, "purged": M, "skipped": K}`. `skipped` couvre les
    races résiduelles avec `api.delete_image` ou `cleanup_demo_data`.
    """
    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.execute(
                select(Image.id)
                .where(
                    Image.local_path.is_not(None),
                    Image.identity_embedding.is_(None),
                    Image.analysis_status == "done",
                )
                .limit(limit)
            )
        ]
    finally:
        db.close()

    counts = {"done": 0, "purged": 0, "skipped": 0}
    for image_id in ids:
        db = SessionLocal()
        try:
            img = db.get(Image, image_id)
            if not img or not img.local_path:
                continue
            path = Path(img.local_path)
            if not path.exists():
                # Incohérence DB↔disque — purge prend en charge ce cas
                from face_processor import _purge_image

                _purge_image(db, img)
                counts["purged"] += 1
                continue
            emb = compute_identity(path)
            if emb is None:
                # MediaPipe avait validé, RetinaFace refuse → faux positif
                from face_processor import _purge_image

                log.info("purge non-human face image #%d : %s", img.id, img.caption or "")
                _purge_image(db, img)
                counts["purged"] += 1
                continue
            img.identity_embedding = serialize(emb)
            try:
                db.commit()
            except StaleDataError:
                # L'image a été supprimée pendant le calcul de l'embedding
                # (workflow audit P9, cleanup_demo_data, ou nettoyage manuel).
                # Rien à sauver — on rollback et on passe au suivant.
                db.rollback()
                log.info("identité skip image #%d : row disparue entre-temps", image_id)
                counts["skipped"] += 1
                continue
            counts["done"] += 1
        finally:
            db.close()
    return counts


def update_centroid(entity_id: int) -> int:
    """Recalcule le centroïde d'une entité. Retourne le nombre d'images contributrices."""
    db = SessionLocal()
    try:
        embeddings = [
            row[0]
            for row in db.execute(
                select(Image.identity_embedding)
                .where(
                    Image.entity_id == entity_id,
                    Image.identity_embedding.is_not(None),
                    # Exclure les images flaggées (ArcFace et humain) du
                    # calcul du centroïde — leur embedding pollue la
                    # référence d'identité de l'entité.
                    Image.association_status.not_in(["flagged", "human_flagged"]),
                )
            )
        ]
        if not embeddings:
            db.execute(
                update(Entity)
                .where(Entity.id == entity_id)
                .values(identity_centroid=None, identity_count=0)
            )
            db.commit()
            return 0

        vecs = np.stack([deserialize(b) for b in embeddings])
        centroid = vecs.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm

        db.execute(
            update(Entity)
            .where(Entity.id == entity_id)
            .values(
                identity_centroid=serialize(centroid),
                identity_count=len(embeddings),
            )
        )
        db.commit()
        return len(embeddings)
    finally:
        db.close()


def audit_entity(entity_id: int) -> dict:
    """Met à jour identity_match_score et association_status pour une entité."""
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if not entity or not entity.identity_centroid:
            return {"checked": 0, "confirmed": 0, "flagged": 0}

        centroid = deserialize(entity.identity_centroid)
        # Décisions humaines préservées dans les deux sens :
        # - `manual` : réassociation explicite (workflow P9), validation
        #   d'une image qui était en flagged ArcFace
        # - `human_flagged` : signalement manuel d'une image qu'ArcFace
        #   n'avait pas attrapée — la décision humaine doit primer, sinon
        #   le prochain cycle d'audit risque de la basculer en `confirmed`
        #   si la distance est sous le seuil.
        rows = db.execute(
            select(Image.id, Image.identity_embedding)
            .where(
                Image.entity_id == entity_id,
                Image.identity_embedding.is_not(None),
                Image.association_status.not_in(["manual", "human_flagged"]),
            )
        ).all()

        confirmed = flagged = 0
        for image_id, emb_bytes in rows:
            emb = deserialize(emb_bytes)
            dist = cosine_distance(emb, centroid)
            new_status = "confirmed" if dist <= IDENTITY_THRESHOLD else "flagged"
            db.execute(
                update(Image)
                .where(Image.id == image_id)
                .values(
                    identity_match_score=round(dist, 4),
                    association_status=new_status,
                )
            )
            if new_status == "confirmed":
                confirmed += 1
            else:
                flagged += 1
        db.commit()
        return {"checked": len(rows), "confirmed": confirmed, "flagged": flagged}
    finally:
        db.close()


def audit_all_entities() -> dict:
    """Update centroïdes + audit toutes les entités avec embeddings."""
    db = SessionLocal()
    try:
        with_emb = (
            select(Image.entity_id)
            .where(Image.identity_embedding.is_not(None))
            .scalar_subquery()
        )
        entity_ids = [
            row[0]
            for row in db.execute(
                select(Entity.id).where(Entity.id.in_(with_emb))
            )
        ]
    finally:
        db.close()

    summary = {"entities": 0, "confirmed": 0, "flagged": 0}
    for eid in entity_ids:
        update_centroid(eid)
        r = audit_entity(eid)
        summary["entities"] += 1
        summary["confirmed"] += r["confirmed"]
        summary["flagged"] += r["flagged"]
    return summary
