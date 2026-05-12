import unicodedata
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import bindparam, func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from config import STATIC_DIR
from database import (
    Article,
    ArticleEntity,
    Entity,
    EntityAlias,
    Image,
    get_db,
)
from pathlib import Path as _Path
from schemas import (
    AnalyzeResultOut,
    ArticleHit,
    ArticleRefOut,
    EntitiesResponse,
    EntityDetail,
    EntityHit,
    EntityImagesResponse,
    EntityListItem,
    FaceOut,
    FlaggedImage,
    FlaggedListResponse,
    GlobalSearchResponse,
    ArticleDetail,
    ArticleEntityRef,
    ArticleListItem,
    ArticleListResponse,
    ImageConfirmResult,
    ImageDeleteResult,
    ImageHit,
    ImageOut,
    ImageReassignRequest,
    ImageReassignResult,
    PoseFilter,
    PurgeEntityResult,
    QueueStatus,
    ScrapeRequest,
    ScrapeResultOut,
    SearchResponse,
)
from scraper import EntityInput, ScrapeInput, process_article

app = FastAPI(title="FACE.ai", version="0.0.1")


# Statut qui marque les entités hors périmètre PERSON (faux PERSON WUDD
# rejetés par le garde-fou Wikidata P31, cf. entity_cleanup). On les exclut
# de toutes les vues utilisateur : liste, recherche, profil, favoris,
# export. Le tombstone reste en DB pour bloquer la recréation au prochain
# pull WUDD du même nom.
NOT_PERSON_STATUS = "not_person"


def _exclude_not_person(query):
    """Helper : ajoute `WHERE entities.wikidata_status != 'not_person'`."""
    return query.where(
        (Entity.wikidata_status.is_(None))
        | (Entity.wikidata_status != NOT_PERSON_STATUS)
    )

# CORS pour le frontend Vite en dev (LAN/Tailscale uniquement, pas un service exposé)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Variantes accentuées par lettre canonique. Couvre FR + langues latines courantes.
_ACCENT_GROUPS: dict[str, list[str]] = {
    "A": ["A", "À", "Á", "Â", "Ã", "Ä", "Å"],
    "C": ["C", "Ç"],
    "E": ["E", "È", "É", "Ê", "Ë"],
    "I": ["I", "Ì", "Í", "Î", "Ï"],
    "N": ["N", "Ñ"],
    "O": ["O", "Ò", "Ó", "Ô", "Õ", "Ö"],
    "U": ["U", "Ù", "Ú", "Û", "Ü"],
    "Y": ["Y", "Ý", "Ÿ"],
}


def _letter_variants(letter: str) -> list[str]:
    letter = letter.upper()
    return _ACCENT_GROUPS.get(letter, [letter])


def _bucket_letter(name: str) -> str:
    if not name:
        return "#"
    nfkd = unicodedata.normalize("NFKD", name)
    base = "".join(c for c in nfkd if not unicodedata.combining(c))
    first = base[0].upper() if base else "#"
    return first if "A" <= first <= "Z" else "#"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_db)):
    """Métriques au format texte Prometheus.

    Exposé sans auth (LAN/Tailscale only, cf. CLAUDE.md §13.9). Source
    de vérité agrégée :
    - Compteurs DB (entités, images, flagged ratio) lus en live
    - Métriques worker (cycles 24h, événements rares) lues depuis la
      table `worker_events` (cf. `worker_metrics.get_status`)

    Format Prometheus text-based exposition format
    (https://prometheus.io/docs/instrumenting/exposition_formats/).
    """
    from worker_metrics import get_status

    lines: list[str] = []

    # ── Compteurs DB ─────────────────────────────────────────────
    total_entities = db.scalar(select(func.count()).select_from(Entity)) or 0
    not_person_count = (
        db.scalar(
            select(func.count())
            .select_from(Entity)
            .where(Entity.wikidata_status == "not_person")
        )
        or 0
    )
    total_images = db.scalar(select(func.count()).select_from(Image)) or 0
    flagged_images = (
        db.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.association_status.in_(("flagged", "human_flagged")))
        )
        or 0
    )
    flagged_ratio = (flagged_images / total_images) if total_images else 0.0

    lines.extend([
        "# HELP face_ai_entities_total Nombre total d'entités (tous statuts).",
        "# TYPE face_ai_entities_total gauge",
        f"face_ai_entities_total {total_entities}",
        "# HELP face_ai_entities_not_person Entités classées not_person (tombstones).",
        "# TYPE face_ai_entities_not_person gauge",
        f"face_ai_entities_not_person {not_person_count}",
        "# HELP face_ai_images_total Nombre total d'images en DB.",
        "# TYPE face_ai_images_total gauge",
        f"face_ai_images_total {total_images}",
        "# HELP face_ai_images_flagged Images en queue d'audit.",
        "# TYPE face_ai_images_flagged gauge",
        f"face_ai_images_flagged {flagged_images}",
        "# HELP face_ai_images_flagged_ratio Ratio flagged / total.",
        "# TYPE face_ai_images_flagged_ratio gauge",
        f"face_ai_images_flagged_ratio {flagged_ratio:.6f}",
    ])

    # ── Compteurs par source_provider (v023) ─────────────────────
    by_provider = db.execute(
        select(Image.source_provider, func.count())
        .group_by(Image.source_provider)
    ).all()
    lines.append("# HELP face_ai_images_by_provider Images par origine.")
    lines.append("# TYPE face_ai_images_by_provider gauge")
    for provider, n in by_provider:
        lines.append(
            f'face_ai_images_by_provider{{provider="{provider or "wudd"}"}} {n}'
        )

    # ── Métriques worker (cycles 24h, événements rares) ──────────
    status = get_status()
    lines.append("# HELP face_ai_worker_successes Cycles worker réussis 24h.")
    lines.append("# TYPE face_ai_worker_successes counter")
    lines.append("# HELP face_ai_worker_errors Cycles worker en erreur 24h.")
    lines.append("# TYPE face_ai_worker_errors counter")
    for loop_name, info in status["loops"].items():
        lines.append(
            f'face_ai_worker_successes{{loop="{loop_name}"}} {info["successes_24h"]}'
        )
        lines.append(
            f'face_ai_worker_errors{{loop="{loop_name}"}} {info["errors_24h"]}'
        )

    # Événements métier (merge_ok, merge_blocked, not_person_purged)
    if status["events_24h"]:
        lines.append("# HELP face_ai_worker_events_24h Événements métier worker 24h.")
        lines.append("# TYPE face_ai_worker_events_24h counter")
        for kind, n in status["events_24h"].items():
            lines.append(
                f'face_ai_worker_events_24h{{kind="{kind}"}} {n}'
            )

    return "\n".join(lines) + "\n"


FLAGGED_STATUSES = ("flagged", "human_flagged")


@app.get("/flagged", response_model=FlaggedListResponse)
def list_flagged(
    limit: int = Query(50, ge=1, le=200),
    source_provider: str | None = Query(
        None,
        description="Filtre par origine : 'wudd' (corpus), 'ddg' (hors corpus), 'manual'. "
                    "Omis = toutes origines.",
    ),
    db: Session = Depends(get_db),
):
    """Images en queue d'audit — deux origines possibles (spec §11.2 / §5.5).

    - `association_status='flagged'` : audit ArcFace automatique (distance
      cosine > 0.55 du centroïde de l'entité).
    - `association_status='human_flagged'` : signalement manuel posé par
      l'utilisateur depuis la galerie (`POST /images/{id}/flag`). Couvre
      les cas où ArcFace n'a pas attrapé une mauvaise attribution (photo
      de groupe, image floue sous le seuil, etc.).

    Tri : DDG / non-wudd d'abord (audit renforcé car pas de cross-check
    texte↔image), puis distance décroissante (les plus suspectes en haut).
    Les `human_flagged` sans score ArcFace remontent via `nulls_last`.
    Filtre `?source_provider=ddg` pour cibler uniquement les images hors corpus.
    """
    base_filter = Image.association_status.in_(FLAGGED_STATUSES)
    if source_provider is not None:
        base_filter = base_filter & (Image.source_provider == source_provider)

    rows = (
        db.execute(
            select(Image)
            .options(joinedload(Image.entity), joinedload(Image.article))
            .where(base_filter)
            # Ordre : non-wudd (DDG/manual) d'abord pour les amener en
            # haut de queue (audit renforcé), puis distance desc.
            .order_by(
                (Image.source_provider == "wudd").asc(),
                Image.identity_match_score.desc().nulls_last(),
            )
            .limit(limit)
        )
        .scalars()
        .all()
    )
    flagged = [
        FlaggedImage(
            id=img.id,
            aligned_url=(
                f"/static/aligned/{img.id}.jpg" if img.aligned_path else None
            ),
            caption=img.caption,
            identity_match_score=img.identity_match_score,
            entity_slug=img.entity.slug if img.entity else "",
            entity_name=img.entity.name if img.entity else "",
            article_title=img.article.title if img.article else None,
            flagged_by=(
                "human" if img.association_status == "human_flagged" else "arcface"
            ),
            source_provider=img.source_provider or "wudd",
        )
        for img in rows
    ]
    total = (
        db.scalar(
            select(func.count())
            .select_from(Image)
            .where(base_filter)
        )
        or 0
    )
    return FlaggedListResponse(flagged=flagged, total=total)


@app.post("/images/{image_id}/flag", response_model=FlaggedImage)
def flag_image(image_id: int, db: Session = Depends(get_db)):
    """Signalement manuel d'une image dont l'humain juge qu'elle n'est pas
    la personne attribuée.

    Bascule `association_status` à `human_flagged` (statut distinct pour
    éviter qu'`audit_entity` ne l'écrase au prochain cycle si le score
    ArcFace est sous le seuil). L'image apparaît immédiatement dans
    `/audit` aux côtés des flagged ArcFace, traitée par le même workflow
    P9 (Réassocier / Supprimer).

    Idempotent : signaler une image déjà `human_flagged` ou `flagged` est
    un noop côté DB (statut courant préservé pour ne pas perdre l'origine
    ArcFace), réponse 200 quand même.
    """
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")

    # Préserver l'origine si déjà flaggée par ArcFace — signaler à la main
    # une image déjà ArcFace-flagged n'a pas de raison d'écraser la trace.
    if img.association_status not in FLAGGED_STATUSES:
        img.association_status = "human_flagged"
        db.commit()
        db.refresh(img)

    return FlaggedImage(
        id=img.id,
        aligned_url=(
            f"/static/aligned/{img.id}.jpg" if img.aligned_path else None
        ),
        caption=img.caption,
        identity_match_score=img.identity_match_score,
        entity_slug=img.entity.slug if img.entity else "",
        entity_name=img.entity.name if img.entity else "",
        article_title=img.article.title if img.article else None,
        flagged_by=(
            "human" if img.association_status == "human_flagged" else "arcface"
        ),
    )


@app.get("/images/{image_id}/landmarks")
def get_image_landmarks(image_id: int, db: Session = Depends(get_db)):
    """Mesh facial complet — 478 points MediaPipe en coordonnées
    normalisées 0..1 sur l'image alignée 300×300 (v024).

    Chargé à la demande par `LandmarkOverlay` côté UI (touche L sur le
    Flipbook). Payload ~3.7 Ko (468×2×4 octets).

    Retourne `{ image_id, count, points: [[x, y], …] }` ou 404 si
    l'image n'existe pas / n'a pas de face_analysis / a été analysée
    avant v024 (landmarks_blob NULL).
    """
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")
    fa = img.face_analysis
    if fa is None or fa.landmarks_blob is None:
        raise HTTPException(
            status_code=404,
            detail="no mesh available (image pre-v024 or analysis failed)",
        )

    import numpy as _np

    arr = _np.frombuffer(fa.landmarks_blob, dtype=_np.float32).reshape(-1, 2)
    return {
        "image_id": image_id,
        "count": int(arr.shape[0]),
        "points": arr.tolist(),
    }


@app.post("/images/{image_id}/confirm", response_model=ImageConfirmResult)
def confirm_image(image_id: int, db: Session = Depends(get_db)):
    """Valide l'attribution actuelle d'une image flagged (workflow P9).

    Cas couvert : l'image est correcte, c'est juste qu'ArcFace s'est trompé
    en signalant (variation d'âge/pose/éclairage extrême, profil, lunettes).
    Bascule `association_status` à `manual` sans changer l'entité — l'audit
    ArcFace ne la repassera plus en `flagged` automatiquement (cf. `manual`
    dans `identity_audit.audit_entity`).

    Idempotent : si déjà `manual`, noop.
    """
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")

    entity_slug = img.entity.slug if img.entity else ""

    if img.association_status == "manual":
        return ImageConfirmResult(
            image_id=image_id,
            entity_slug=entity_slug,
            new_status="manual",
        )

    img.association_status = "manual"
    db.commit()

    return ImageConfirmResult(
        image_id=image_id,
        entity_slug=entity_slug,
        new_status="manual",
    )


@app.delete("/images/{image_id}", response_model=ImageDeleteResult)
def delete_image(image_id: int, db: Session = Depends(get_db)):
    """Supprime une image (workflow P9). Cascade fichiers + face_analysis.

    Recompute_counts de l'entité associée (le compteur image_count change).
    L'identity_centroid de l'entité reste valide tant qu'il est recalculé
    par le worker au prochain cycle dedup_loop / identity_loop.
    """
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")

    entity_slug = img.entity.slug if img.entity else ""
    entity_id = img.entity_id

    files_to_remove: list[_Path] = []
    if img.local_path:
        files_to_remove.append(_Path(img.local_path))
    if img.aligned_path:
        files_to_remove.append(_Path(img.aligned_path))

    db.delete(img)  # cascade ORM → face_analysis
    db.commit()

    files_removed = 0
    for path in files_to_remove:
        try:
            if path.exists():
                path.unlink()
                files_removed += 1
        except OSError:
            pass

    if entity_id is not None:
        from entity_stats import recompute_counts

        recompute_counts(entity_id)

    return ImageDeleteResult(
        image_id=image_id,
        files_removed=files_removed,
        entity_slug=entity_slug,
    )


@app.patch("/images/{image_id}", response_model=ImageReassignResult)
def reassign_image(
    image_id: int,
    payload: ImageReassignRequest,
    db: Session = Depends(get_db),
):
    """Réassocie une image à une autre entité (workflow P9).

    Bascule `association_status` à `manual` (la décision humaine fait foi,
    l'audit ArcFace ne la repassera pas en `flagged` automatiquement).
    Recompute_counts pour les 2 entités touchées + reset de leurs centroïdes
    pour forcer un recalcul propre au prochain cycle worker.
    """
    img = db.get(Image, image_id)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")

    target = db.scalar(select(Entity).where(Entity.slug == payload.target_slug))
    if target is None:
        raise HTTPException(status_code=404, detail="target entity not found")

    from_slug = img.entity.slug if img.entity else ""
    from_entity_id = img.entity_id

    if from_entity_id == target.id:
        return ImageReassignResult(
            image_id=image_id,
            from_slug=from_slug,
            to_slug=target.slug,
            new_status=img.association_status,
        )

    img.entity_id = target.id
    img.association_status = "manual"
    img.identity_match_score = None  # le centroïde cible n'a pas encore été comparé
    db.commit()

    # Reset des centroïdes des 2 entités → le worker les recalcule au prochain cycle.
    from sqlalchemy import update as sa_update

    db.execute(
        sa_update(Entity)
        .where(Entity.id.in_([from_entity_id, target.id]))
        .values(identity_centroid=None, identity_count=0)
    )
    db.commit()

    from entity_stats import recompute_counts

    if from_entity_id:
        recompute_counts(from_entity_id)
    recompute_counts(target.id)

    return ImageReassignResult(
        image_id=image_id,
        from_slug=from_slug,
        to_slug=target.slug,
        new_status="manual",
    )


@app.post("/analyze/{image_id}", response_model=AnalyzeResultOut)
def analyze(image_id: int):
    # Import différé : mediapipe + opencv sont lourds, on évite l'import au boot
    from face_processor import process_image as fp_process

    r = fp_process(image_id)
    return AnalyzeResultOut(image_id=image_id, status=r.status, detail=r.detail)


@app.post("/admin/sync-wudd")
def admin_sync_wudd(limit: int = Query(50, ge=1, le=5000)):
    """Déclenche manuellement un pull WUDD → FACE.ai (spec §8).

    Mode admin : pas d'auth puisque LAN/Tailscale uniquement (§13.9).
    Pour un import à grande échelle, prefer le worker (poll 30 min)
    qui chaîne automatiquement avec les boucles d'analyse + identité +
    enrichissement Wikidata.
    """
    from wudd_sync import sync_persons

    return sync_persons(limit=limit)


@app.post("/entities/{canonical_slug}/merge")
def merge_entity_endpoint(
    canonical_slug: str,
    source: str = Query(..., description="Slug de l'entité à fusionner DANS le canonical"),
    db: Session = Depends(get_db),
):
    """Fusion manuelle de 2 entités (cas où Wikidata QID diffère).

    Le `source` perd son existence ; ses images, articles liés et aliases
    sont transférés vers `canonical_slug`. Le nom du source devient un alias
    de canonical (donc un re-pull WUDD du même nom retombera sur canonical).
    """
    from entity_merge import merge_entities

    canonical = db.scalar(select(Entity).where(Entity.slug == canonical_slug))
    duplicate = db.scalar(select(Entity).where(Entity.slug == source))
    if canonical is None or canonical.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail=f"canonical '{canonical_slug}' not found")
    if duplicate is None or duplicate.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail=f"source '{source}' not found")
    if canonical.id == duplicate.id:
        raise HTTPException(status_code=400, detail="canonical and source are the same entity")

    return merge_entities(canonical.id, duplicate.id)


@app.post("/admin/auto-merge-qid")
def admin_auto_merge_qid():
    """Déclenche manuellement la fusion par QID Wikidata (sinon worker poll 2 min).

    Les paires bloquées par le garde-fou (incident 2026-05-11) ressortent
    dans `summary["blocks"]`. Pour décider de fusionner quand même,
    voir l'endpoint manuel `POST /entities/{canonical}/merge?source={dup}`.
    """
    from entity_merge import auto_merge_by_qid

    return auto_merge_by_qid()


@app.get("/admin/worker-status")
def admin_worker_status(db: Session = Depends(get_db)):
    """Observabilité worker (boucles + événements 24h + ratios DB).

    Permet de détecter un worker arrêté (aucune `last_success_at` récente),
    une boucle qui plante en silence (`errors_24h` élevé sans `successes`),
    ou un incident en cours (`merge_ok` ou `not_person_purged` qui explose
    soudainement — cf. incident 2026-05-11).
    """
    from worker_metrics import get_status

    status = get_status()

    # Ratios DB : flagged / total — un saut soudain de ce ratio est typique
    # d'un mauvais cluster de réassociations.
    total_images = db.scalar(select(func.count()).select_from(Image)) or 0
    flagged = (
        db.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.association_status == "flagged")
        )
        or 0
    )
    status["db"] = {
        "total_images": total_images,
        "flagged_images": flagged,
        "flagged_ratio": round(flagged / total_images, 4) if total_images else 0,
    }
    return status


@app.post("/admin/backup-now")
def admin_backup_now():
    """Force un snapshot immédiat de la DB (sinon worker quotidien).

    Idempotent : si le fichier du jour existe déjà, overwrité avec un
    snapshot frais. Utile avant une opération risquée (script de migration,
    démerge manuel, etc.).
    """
    from backup import make_backup

    return make_backup()


@app.get("/admin/backups")
def admin_backups():
    """Inventaire des backups SQLite disponibles, par fenêtre de rétention."""
    from backup import list_backups

    return list_backups()


@app.post("/admin/restore-backup")
def admin_restore_backup(filename: str = Query(..., description="Nom de fichier dans data/backups/")):
    """Restaure un snapshot SQLite. **Action destructive** : remplace
    `face_ai.db` par le contenu du backup choisi.

    Un snapshot `pre-restore-…` de l'état courant est créé en parallèle —
    rollback possible en restaurant ce fichier-là.

    L'API et le worker doivent être redémarrés manuellement après
    (`docker compose restart api worker`) car l'engine SQLAlchemy garde
    son cache du fichier précédent.
    """
    from backup import restore_backup

    try:
        return restore_backup(filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/backfill-landmarks")
def admin_backfill_landmarks(
    limit: int = Query(100, ge=1, le=1000, description="Nombre max d'images à traiter par appel"),
):
    """Rétro-extrait le mesh 478 points sur les images analysées avant v024.

    Re-run MediaPipe sur l'image alignée 300×300 stockée. Coût ~150 ms
    par image, donc `limit=100` ≈ 15 s. Idempotent (skip celles qui ont
    déjà `landmarks_blob`). À relancer plusieurs fois pour couvrir tout
    le corpus historique sans bloquer l'API trop longtemps.
    """
    from face_processor import backfill_landmarks

    return backfill_landmarks(limit=limit)


@app.post("/admin/recheck-not-person")
def admin_recheck_not_person(
    limit: int = Query(50, ge=1, le=500, description="Nombre d'entités à re-vérifier par appel"),
):
    """Rétro-applique le garde-fou P31 sur les entités déjà `wikidata_status='done'`.

    Cas couvert : entités enrichies avant l'ajout du garde-fou type=PERSON
    (v014) — typiquement ChatGPT, OpenAI, certains pays ou organisations
    qui ont conservé leur statut `done` au lieu de basculer en `not_person`.

    Politesse Wikidata : 1 s entre deux appels (1 req `_get_statements`
    par entité). Avec `limit=50`, ~50 s d'exécution max.
    """
    from entity_cleanup import purge_all_non_persons

    return purge_all_non_persons(limit=limit)


@app.get("/admin/centroid-merge-candidates")
def admin_centroid_merge_candidates():
    """Paires d'entités candidates à la fusion par proximité de centroïde
    ArcFace (homonymes Wikidata = QIDs différents mais même personne).

    Retourne toutes les paires à distance ≤ `SUGGEST_DISTANCE` (0.45),
    classées par distance ascendante. Pour chaque paire :
    - `can_auto=true` : passerait l'auto-merge si on relance la boucle
    - `can_auto=false` + `block_reason` : décision manuelle requise
      (distance trop élevée OU growth ratio dépassé)
    """
    from centroid_merge import find_candidate_pairs

    pairs = find_candidate_pairs()
    return {
        "count": len(pairs),
        "pairs": [
            {
                "canonical": {
                    "id": p.canonical_id,
                    "slug": p.canonical_slug,
                    "name": p.canonical_name,
                    "image_count": p.canonical_image_count,
                },
                "duplicate": {
                    "id": p.duplicate_id,
                    "slug": p.duplicate_slug,
                    "name": p.duplicate_name,
                    "image_count": p.duplicate_image_count,
                },
                "distance": round(p.distance, 4),
                "can_auto": p.can_auto,
                "block_reason": p.block_reason,
            }
            for p in pairs
        ],
    }


@app.post("/admin/centroid-auto-merge")
def admin_centroid_auto_merge():
    """Déclenche un tour d'auto-merge par centroïde (manuel). Soumis au
    même garde-fou que `auto_merge_by_qid` (cf. incident 2026-05-11)."""
    from centroid_merge import auto_merge_by_centroid

    return auto_merge_by_centroid()


@app.get("/admin/merge-conflicts")
def admin_merge_conflicts():
    """Liste les paires d'entités partageant un QID Wikidata mais que
    le garde-fou refuse de fusionner automatiquement (cf. incident
    2026-05-11 — corruption de QID + fusion catastrophique).

    Chaque entrée donne : `canonical`, `duplicate`, et `reason` (ratio de
    croissance trop fort, ou score Wikidata < 1.0). Décision humaine
    requise — soit fusion manuelle via `POST /entities/{slug}/merge`,
    soit correction du QID erroné sur une des deux entités.
    """
    from entity_merge import find_blocked_merge_conflicts

    conflicts = find_blocked_merge_conflicts()
    return {"count": len(conflicts), "conflicts": conflicts}


@app.get("/entities/duplicate-candidates")
def list_duplicate_candidates(limit: int = Query(30, ge=1, le=200)):
    """Entités probables doublons à fusionner (3 catégories).

    Alimente l'UI `/audit` côté frontend. Logique partagée avec l'outil MCP
    `find_duplicate_candidates` via `duplicate_finder.find_candidates`.

    `same_qid` devrait être vide en régime normal (auto-mergé toutes les
    2 min par `worker.merge_loop`). Si la liste n'est pas vide, c'est un
    signal que le worker est arrêté ou plante.
    """
    from duplicate_finder import find_candidates

    return find_candidates(limit=limit)


@app.post("/admin/sync-wudd-articles-batch")
def admin_sync_wudd_articles_batch(
    count: int = Query(None, ge=1, le=50, description="Nombre d'entités à traiter (défaut = config)"),
):
    """Pull WUDD articles par lot, hors cycle worker (utile pour pousser les favoris)."""
    from wudd_articles_batch import run_batch

    summary = run_batch(count=count)
    # On retire le détail verbeux pour la réponse HTTP, juste le résumé
    return {k: v for k, v in summary.items() if k != "details"}


@app.get("/admin/wudd-status")
def admin_wudd_status():
    """Métriques de progression du pull WUDD articles par batch."""
    from wudd_articles_batch import status

    return status()


@app.post("/admin/sync-wudd-articles")
def admin_sync_wudd_articles(
    person: str = Query(..., description="Nom de la PERSON côté WUDD (ex. 'Sam Altman')"),
    limit: int = Query(20, ge=1, le=200),
):
    """Pull les articles WUDD mentionnant une PERSON et ingère leurs images.

    Cette voie utilise les images **déjà extraites par WUDD** (champ `Images`)
    plutôt que de re-scraper la page HTML d'origine. Plus rapide et plus
    propre. L'audit ArcFace en aval filtrera les associations douteuses.
    """
    from wudd_articles_sync import sync_articles_for_person

    return sync_articles_for_person(person, limit=limit)


@app.get("/articles", response_model=ArticleListResponse)
def list_articles(
    source_domain: str | None = Query(None, description="Filtre par domaine source (lemonde.fr…)"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    entity_slug: str | None = Query(None, description="Filtre par entité liée"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Liste paginée des articles ingérés.

    Spec §6 endpoint identifié, ajouté pour cohérence d'API (utilisable
    par le MCP et les agents externes). Filtres : domaine, dates,
    entité liée.

    Tri : `published_at` desc (les plus récents en haut), `scraped_at`
    desc en fallback pour les articles sans date.
    """
    base = select(Article)
    count_base = select(func.count()).select_from(Article)

    if entity_slug is not None:
        sub = (
            select(ArticleEntity.article_id)
            .join(Entity, Entity.id == ArticleEntity.entity_id)
            .where(Entity.slug == entity_slug)
            .scalar_subquery()
        )
        base = base.where(Article.id.in_(sub))
        count_base = count_base.where(Article.id.in_(sub))
    if source_domain is not None:
        base = base.where(Article.source_domain == source_domain)
        count_base = count_base.where(Article.source_domain == source_domain)
    if date_from is not None:
        base = base.where(Article.published_at >= date_from)
        count_base = count_base.where(Article.published_at >= date_from)
    if date_to is not None:
        base = base.where(Article.published_at <= date_to)
        count_base = count_base.where(Article.published_at <= date_to)

    total = db.scalar(count_base) or 0
    rows = db.execute(
        base.order_by(
            Article.published_at.desc().nulls_last(),
            Article.scraped_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    article_ids = [a.id for a in rows]
    # Compteurs entités + images par article via 2 sous-requêtes
    # agrégées (évite N+1).
    if article_ids:
        entity_counts = dict(
            db.execute(
                select(
                    ArticleEntity.article_id,
                    func.count(func.distinct(ArticleEntity.entity_id)),
                )
                .where(ArticleEntity.article_id.in_(article_ids))
                .group_by(ArticleEntity.article_id)
            ).all()
        )
        image_counts = dict(
            db.execute(
                select(
                    Image.article_id,
                    func.count(),
                )
                .where(Image.article_id.in_(article_ids))
                .group_by(Image.article_id)
            ).all()
        )
    else:
        entity_counts = {}
        image_counts = {}

    items = [
        ArticleListItem(
            id=a.id,
            url=a.url,
            title=a.title,
            published_at=a.published_at,
            source_domain=a.source_domain,
            entity_count=entity_counts.get(a.id, 0),
            image_count=image_counts.get(a.id, 0),
        )
        for a in rows
    ]
    return ArticleListResponse(articles=items, total=total)


@app.get("/articles/{article_id}", response_model=ArticleDetail)
def get_article(article_id: int, db: Session = Depends(get_db)):
    """Détail d'un article : entités liées + images.

    Spec §6 endpoint identifié. Utile au MCP pour suivre les
    cooccurrences entité↔article. Pas d'auth (LAN-only).
    """
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")

    # Entités liées (jointure article_entities)
    entities = db.execute(
        select(Entity)
        .join(ArticleEntity, ArticleEntity.entity_id == Entity.id)
        .where(ArticleEntity.article_id == article_id)
        .order_by(Entity.name)
    ).scalars().all()

    # Images de l'article
    images_rows = db.execute(
        select(Image)
        .options(joinedload(Image.face_analysis), joinedload(Image.article))
        .where(Image.article_id == article_id)
        .order_by(Image.id)
    ).scalars().unique().all()

    return ArticleDetail(
        id=article.id,
        url=article.url,
        title=article.title,
        published_at=article.published_at,
        scraped_at=article.scraped_at,
        source_domain=article.source_domain,
        wudd_article_id=article.wudd_article_id,
        entities=[
            ArticleEntityRef(
                id=e.id,
                slug=e.slug,
                name=e.name,
                is_favorite=bool(e.is_favorite),
            )
            for e in entities
        ],
        images=[
            ImageOut(
                id=img.id,
                source_url=img.source_url,
                aligned_url=(
                    f"/static/aligned/{img.id}.jpg" if img.aligned_path else None
                ),
                caption=img.caption,
                copyright=img.copyright_text,
                scrape_status=img.scrape_status,
                analysis_status=img.analysis_status,
                is_duplicate=bool(img.is_duplicate),
                association_status=img.association_status,
                identity_match_score=img.identity_match_score,
                article=ArticleRefOut.model_validate(img.article) if img.article else None,
                face=FaceOut.model_validate(img.face_analysis) if img.face_analysis else None,
            )
            for img in images_rows
        ],
    )


@app.get("/queue", response_model=QueueStatus)
def queue_status(db: Session = Depends(get_db)):
    # Note : depuis la règle §5.4, les statuts 'failed' et 'no_face' ne
    # peuvent plus apparaître — purge automatique à l'analyse. On garde
    # 'pending' et 'done' uniquement.
    analysis: dict[str, int] = {}
    for s in ("pending", "done"):
        analysis[s] = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(Image.analysis_status == s)
            )
            or 0
        )
    scrape: dict[str, int] = {}
    for s in ("downloaded",):
        scrape[s] = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(Image.scrape_status == s)
            )
            or 0
        )
    return QueueStatus(analysis=analysis, scrape=scrape)


@app.post("/scrape", response_model=ScrapeResultOut)
def scrape(payload: ScrapeRequest):
    result = process_article(
        ScrapeInput(
            article_url=payload.article_url,
            article_title=payload.article_title,
            entities=[
                EntityInput(name=e.name, type=e.type) for e in payload.entities
            ],
        )
    )
    return ScrapeResultOut(**result.__dict__)


@app.get("/entities", response_model=EntitiesResponse)
def list_entities(
    letter: str | None = Query(None, min_length=1, max_length=1),
    favorites_only: bool = False,
    sort_by: str = Query(
        "canonical",
        description="`canonical` (filtre par 1re lettre du nom de famille) ou `first_name` (par prénom)",
    ),
    # CLAUDE.md prévoit 16k+ entités cibles. Sans pagination/virtualization
    # côté UI, on liste tout dans la sidebar. Plafond haut pour ne pas
    # tronquer (le payload reste léger : ~150 octets/entité = ~2 Mo à 16k).
    # Virtualization a été tentée 4× sans succès — refonte layout requise.
    limit: int = Query(50, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    base = _exclude_not_person(select(Entity))
    count_base = _exclude_not_person(select(func.count()).select_from(Entity))

    if favorites_only:
        base = base.where(Entity.is_favorite.is_(True))
        count_base = count_base.where(Entity.is_favorite.is_(True))

    if letter is not None:
        variants = _letter_variants(letter)
        if sort_by == "first_name":
            # Filtrer sur la 1re lettre du prénom (= après la virgule).
            # SQL LIKE `%, V%` matche "Chalamet, Victor", "Smith, Vincent", etc.
            # Pour les mononymes (pas de virgule), on filtre sur la 1re
            # lettre du nom entier comme en canonique.
            if letter.upper() == "#":
                # Le bucket # exclut tous les prénoms commençant par une
                # lettre connue. Approximation : on filtre sur les noms
                # sans virgule dont la 1re lettre est hors alphabet.
                cond = ~or_(
                    *[Entity.name.like(f"%, {v}%") for v in _flatten_known_letters()],
                    *[Entity.name.like(f"{v}%") for v in _flatten_known_letters()],
                )
            else:
                # `%, V%` pour les noms canoniques + `V%` pour les mononymes
                cond = or_(
                    *[Entity.name.like(f"%, {v}%") for v in variants],
                    # Mononymes : 1re lettre du nom entier ET pas de virgule
                    *[
                        Entity.name.like(f"{v}%") & ~Entity.name.contains(",")
                        for v in variants
                    ],
                )
        else:
            if letter.upper() == "#":
                cond = ~or_(
                    *[Entity.name.like(f"{v}%") for v in _flatten_known_letters()]
                )
            else:
                cond = or_(*[Entity.name.like(f"{v}%") for v in variants])
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = db.scalar(count_base) or 0
    rows = (
        db.execute(base.order_by(Entity.name).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return EntitiesResponse(
        entities=[EntityListItem.model_validate(r) for r in rows],
        total=total,
    )


@app.put("/entities/{slug}/favorite")
def set_favorite(slug: str, db: Session = Depends(get_db)):
    """Marque l'entité comme favorite. Idempotent.

    Refus si l'entité est un tombstone `not_person` (404, comme si elle
    n'existait pas du point de vue utilisateur)."""
    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None or entity.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail="entity not found")
    entity.is_favorite = True
    db.commit()
    return {"slug": slug, "is_favorite": True}


@app.delete("/entities/{slug}/favorite")
def unset_favorite(slug: str, db: Session = Depends(get_db)):
    """Retire le favori. Idempotent."""
    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")
    entity.is_favorite = False
    db.commit()
    return {"slug": slug, "is_favorite": False}


def _flatten_known_letters() -> list[str]:
    out: list[str] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        out.extend(_letter_variants(letter))
    return out


@app.get("/entities/letters")
def list_letter_distribution(
    favorites_only: bool = False,
    sort_by: str = Query(
        "canonical",
        description="`canonical` (défaut, bucket sur la 1re lettre du nom de famille) ou `first_name` (sur le prénom).",
    ),
    db: Session = Depends(get_db),
):
    """Distribution des entités par lettre initiale (normalisée, accents repliés).

    En mode `sort_by=first_name`, on bucket sur le prénom (= ce qui suit
    la virgule dans le canonique `Last, First`). Pour les mononymes
    (Madonna, Beyoncé), le nom entier est utilisé. C'est nécessaire pour
    cohérence avec le toggle `↕ prénom` côté UI (`useSortMode`) qui
    réordonne EntityList — sans recalcul des buckets, l'AlphaNav reste
    indexée sur le nom de famille et l'utilisateur est perdu.
    """
    stmt = _exclude_not_person(select(Entity.name))
    if favorites_only:
        stmt = stmt.where(Entity.is_favorite.is_(True))
    counts: dict[str, int] = {}
    for (name,) in db.execute(stmt).all():
        if sort_by == "first_name" and "," in name:
            # "Chalamet, Timothée" → "Timothée"
            parts = name.split(",", 1)
            if len(parts) == 2:
                name = parts[1].strip()
        bucket = _bucket_letter(name)
        counts[bucket] = counts.get(bucket, 0) + 1
    return {
        "total": sum(counts.values()),
        "letters": dict(sorted(counts.items())),
    }


@app.get("/entities/search", response_model=SearchResponse)
def search_entities(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    fts_query = _build_fts_query(q)
    if fts_query is None:
        return SearchResponse(results=[])

    stmt = text(
        """
        SELECT e.*
          FROM entities_fts f
          JOIN entities e ON e.id = f.rowid
         WHERE entities_fts MATCH :q
           AND COALESCE(e.wikidata_status, '') != 'not_person'
         ORDER BY rank
         LIMIT :limit
        """
    ).bindparams(bindparam("q", fts_query), bindparam("limit", limit))

    rows = db.execute(stmt).mappings().all()
    return SearchResponse(
        results=[EntityListItem.model_validate(dict(r)) for r in rows]
    )


@app.get("/search", response_model=GlobalSearchResponse)
def global_search(
    q: str = Query(..., min_length=1),
    scope: str = Query(
        "all",
        pattern="^(all|entities|articles|images)$",
        description="all, entities, articles, ou images",
    ),
    limit: int = Query(10, ge=1, le=50, description="par catégorie"),
    db: Session = Depends(get_db),
):
    """Recherche full-text globale (FTS5) sur entités, articles, images.

    - **entities** : FTS5 sur name + aliases + occupations + employer +
      nationalities + birth_place + wiki_summary (cf. migration v018).
    - **articles** : FTS5 sur title + source_domain (v019).
    - **images** : FTS5 sur caption + alt_text + copyright_text (v020).

    Le tokenizer FTS5 `unicode61 remove_diacritics 2` gère les accents FR
    (`Macron` matche `Mâcon`, `physicien` matche `physicien-ne`).

    Chaque résultat inclut un `snippet` HTML (`<mark>...</mark>` autour du
    match) pour l'affichage. Les articles et images joignent leur entité
    associée principale pour permettre la navigation depuis le résultat.

    `scope=all` exécute les 3 requêtes en parallèle (3 round-trips DB,
    négligeable avec SQLite local). Pour réduire la latence côté frontend
    on peut filtrer avec `scope=entities|articles|images`.
    """
    fts_query = _build_fts_query(q)
    response = GlobalSearchResponse(
        query=q, totals={"entities": 0, "articles": 0, "images": 0}
    )
    if fts_query is None:
        return response

    want = lambda kind: scope in ("all", kind)  # noqa: E731

    if want("entities"):
        # snippet() : 5 = nom de la colonne ? Non, FTS5 snippet(table, col_idx,
        # opening, closing, ellipsis, max_tokens). col_idx=-1 = toutes les
        # colonnes. On vise 12 tokens autour du hit.
        stmt = text(
            """
            SELECT e.slug, e.name, e.image_count, e.article_count,
                   snippet(entities_fts, -1, '<mark>', '</mark>', '…', 12) AS snippet
              FROM entities_fts f
              JOIN entities e ON e.id = f.rowid
             WHERE entities_fts MATCH :q
               AND COALESCE(e.wikidata_status, '') != 'not_person'
             ORDER BY rank
             LIMIT :limit
            """
        ).bindparams(bindparam("q", fts_query), bindparam("limit", limit))
        for r in db.execute(stmt).mappings():
            response.entities.append(EntityHit(**dict(r)))

        # Total séparé — comme la query ci-dessus, on exclut les not_person
        total = (
            db.scalar(
                text(
                    """
                    SELECT COUNT(*)
                      FROM entities_fts f
                      JOIN entities e ON e.id = f.rowid
                     WHERE entities_fts MATCH :q
                       AND COALESCE(e.wikidata_status, '') != 'not_person'
                    """
                ).bindparams(bindparam("q", fts_query))
            )
            or 0
        )
        response.totals["entities"] = total

    if want("articles"):
        # Contrainte FTS5 : `snippet()` ne peut être appelée que dans une
        # requête qui sélectionne directement depuis la table FTS5, sans
        # JOIN ni GROUP BY. On la calcule donc dans une CTE puis on joint
        # les entités via des sous-requêtes scalaires (1 entité par article,
        # arbitraire mais stable — première par id article_entities).
        stmt = text(
            """
            WITH hits AS (
                SELECT rowid AS article_id,
                       snippet(articles_fts, -1, '<mark>', '</mark>', '…', 12) AS snippet,
                       rank
                  FROM articles_fts
                 WHERE articles_fts MATCH :q
                 ORDER BY rank
                 LIMIT :limit
            )
            SELECT a.id           AS article_id,
                   a.title        AS title,
                   a.url          AS url,
                   a.source_domain AS source_domain,
                   a.published_at AS published_at,
                   h.snippet      AS snippet,
                   (SELECT e.slug FROM article_entities ae
                      JOIN entities e ON e.id = ae.entity_id
                     WHERE ae.article_id = a.id
                     LIMIT 1)     AS entity_slug,
                   (SELECT e.name FROM article_entities ae
                      JOIN entities e ON e.id = ae.entity_id
                     WHERE ae.article_id = a.id
                     LIMIT 1)     AS entity_name
              FROM hits h
              JOIN articles a ON a.id = h.article_id
             ORDER BY h.rank
            """
        ).bindparams(bindparam("q", fts_query), bindparam("limit", limit))
        for r in db.execute(stmt).mappings():
            response.articles.append(ArticleHit(**dict(r)))

        total = (
            db.scalar(
                text("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH :q")
                .bindparams(bindparam("q", fts_query))
            )
            or 0
        )
        response.totals["articles"] = total

    if want("images"):
        # Même contrainte FTS5 que pour articles — snippet via CTE.
        stmt = text(
            """
            WITH hits AS (
                SELECT rowid AS image_id,
                       snippet(images_fts, -1, '<mark>', '</mark>', '…', 12) AS snippet,
                       rank
                  FROM images_fts
                 WHERE images_fts MATCH :q
                 ORDER BY rank
                 LIMIT :limit
            )
            SELECT i.id           AS image_id,
                   i.caption      AS caption,
                   i.aligned_path AS aligned_path,
                   e.slug         AS entity_slug,
                   e.name         AS entity_name,
                   h.snippet      AS snippet
              FROM hits h
              JOIN images i ON i.id = h.image_id
              LEFT JOIN entities e ON e.id = i.entity_id
             ORDER BY h.rank
            """
        ).bindparams(bindparam("q", fts_query), bindparam("limit", limit))
        for r in db.execute(stmt).mappings():
            d = dict(r)
            aligned_path = d.pop("aligned_path", None)
            d["aligned_url"] = (
                f"/static/aligned/{d['image_id']}.jpg" if aligned_path else None
            )
            response.images.append(ImageHit(**d))

        total = (
            db.scalar(
                text("SELECT COUNT(*) FROM images_fts WHERE images_fts MATCH :q")
                .bindparams(bindparam("q", fts_query))
            )
            or 0
        )
        response.totals["images"] = total

    return response


def _build_fts_query(q: str) -> str | None:
    """Convertit la requête utilisateur en expression FTS5.

    On découpe sur les espaces, on retire les caractères qui cassent le parser
    FTS5, et on ajoute un wildcard de préfixe à chaque terme pour autoriser
    la complétion ("alt" → "alt*" → "Altman").
    """
    parts: list[str] = []
    for raw in q.split():
        cleaned = "".join(c for c in raw if c.isalnum())
        if cleaned:
            parts.append(f"{cleaned}*")
    return " ".join(parts) if parts else None


def _entity_detail(entity: Entity) -> EntityDetail:
    nationalities = [
        s for s in (entity.nationalities or "").split("|") if s
    ]
    occupations = [
        s for s in (entity.occupations or "").split("|") if s
    ]
    age_at_death = None
    if entity.birth_date and entity.death_date:
        years = entity.death_date.year - entity.birth_date.year
        if (entity.death_date.month, entity.death_date.day) < (
            entity.birth_date.month,
            entity.birth_date.day,
        ):
            years -= 1
        age_at_death = years if years >= 0 else None
    return EntityDetail(
        id=entity.id,
        name=entity.name,
        slug=entity.slug,
        article_count=entity.article_count,
        image_count=entity.image_count,
        unique_image_count=entity.unique_image_count or 0,
        diversity_score=entity.diversity_score,
        is_favorite=bool(entity.is_favorite),
        aliases=[a.alias for a in entity.aliases],
        first_seen=entity.first_seen,
        updated_at=entity.updated_at,
        wikidata_qid=entity.wikidata_qid,
        wikidata_status=entity.wikidata_status,
        wiki_summary=entity.wiki_summary,
        wiki_url=entity.wiki_url,
        wiki_thumbnail_url=entity.wiki_thumbnail_url,
        birth_date=entity.birth_date,
        death_date=entity.death_date,
        age_at_death=age_at_death,
        birth_place=entity.birth_place,
        death_place=entity.death_place,
        nationalities=nationalities,
        occupations=occupations,
        employer=entity.employer,
    )


@app.post("/entities/{slug}/search-ddg")
def search_ddg_for_entity(
    slug: str,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Cherche des images de l'entité via DuckDuckGo Images.

    Preview only : retourne des URLs candidates avec leurs thumbnails,
    sans rien télécharger. C'est l'UI picker (modale) qui consomme et
    qui demande ensuite à ingérer celles que l'utilisateur sélectionne
    via `POST /entities/{slug}/ingest-ddg-image`.

    Élargit le périmètre vs spec §1.5 (corpus WUDD maîtrisé). Désactivé
    par défaut, activable via env `FACE_AI_ENABLE_DDG=true`. Cf. CLAUDE.md
    pour la posture éthique.
    """
    from ddg_search import can_use_ddg, search_images

    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")

    ok, reason = can_use_ddg(entity)
    if not ok:
        raise HTTPException(status_code=403, detail=reason)

    # Construit la requête à partir de la forme naturelle "First Last"
    name = entity.name
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"

    candidates = search_images(name, limit=limit)
    return {
        "slug": slug,
        "query": name,
        "count": len(candidates),
        "candidates": candidates,
    }


@app.post("/entities/{slug}/ingest-ddg-image")
def ingest_ddg_image(
    slug: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Ingère une image DDG sélectionnée par l'utilisateur dans le picker.

    Body : `{ "url": "...", "title": "...", "source_page": "..." }`

    Crée une `images` row avec `source_provider='ddg'`, télécharge le
    binaire sur disque, et délègue au pipeline standard (face_processor +
    identity_audit) pour la qualification visuelle. Pas de lien article
    (DDG = hors corpus WUDD).

    Idempotent : si l'URL est déjà ingérée (recherche DDG répétée, double-
    clic UI), retourne l'image_id existant sans re-télécharger.
    """
    from ddg_search import can_use_ddg, ingest_image

    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")

    ok, reason = can_use_ddg(entity)
    if not ok:
        raise HTTPException(status_code=403, detail=reason)

    url = (payload or {}).get("url", "").strip()
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="invalid url")

    result = ingest_image(
        entity.id,
        url,
        title=payload.get("title"),
        source_page=payload.get("source_page"),
    )
    if result["status"] == "missing_entity":
        raise HTTPException(status_code=404, detail="entity not found")
    if result["status"] == "download_failed":
        raise HTTPException(
            status_code=502,
            detail=f"download failed (http={result.get('http_status')})",
        )
    return {"slug": slug, **result}


@app.post("/entities/{slug}/collect")
def collect_entity(
    slug: str,
    limit: int = Query(200, ge=1, le=2000, description="Nombre max d'articles WUDD à pull"),
    db: Session = Depends(get_db),
):
    """Force une collecte WUDD ciblée pour une entité, hors batch worker.

    Lit le nom de l'entité côté FACE.ai (format canonique `Last, First`),
    le convertit en forme naturelle `First Last` (le format attendu par
    WUDD), puis appelle `sync_articles_for_person`. Ré-ingère les articles
    récents, télécharge les nouvelles images, le pipeline d'analyse les
    prend ensuite en charge (face_processor → identity audit → dedup).

    Idempotent : un article déjà ingéré est compté `articles_already`.

    Synchrone — peut prendre jusqu'à ~1 min pour 200 articles selon la
    politesse Wikimedia. Le frontend doit afficher un spinner.

    Marque aussi `last_articles_synced_at` pour que le batch_loop
    automatique n'y revienne pas immédiatement.
    """
    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")

    # "Last, First" → "First Last" (format WUDD), cf. wikidata.enrich_entity
    name = entity.name
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"

    from datetime import datetime as _dt

    from wudd_articles_sync import sync_articles_for_person

    summary = sync_articles_for_person(name, limit=limit)
    entity.last_articles_synced_at = _dt.utcnow()
    db.commit()

    return {
        "slug": slug,
        "person_searched": name,
        **summary,
    }


@app.delete("/entities/{slug}", response_model=PurgeEntityResult)
def delete_entity(slug: str, db: Session = Depends(get_db)):
    """Droit d'opposition / effacement (RGPD art. 17, 21 / nLPD art. 32, spec §19).

    Supprime en cascade :
    - L'entité et ses aliases (cascade ORM `all, delete-orphan`)
    - Toutes ses images (rows + fichiers `local_path` et `aligned_path`)
    - Les analyses faciales liées (cascade ORM via `Image.face_analysis`)
    - Les liens article↔entité (`article_entities`)

    Conserve les articles eux-mêmes (contenu de presse tiers, pas une donnée
    personnelle au sens RGPD/nLPD). Les articles devenus orphelins (plus
    aucune entité associée) sont juste signalés dans la réponse — ils
    pourraient être nettoyés ultérieurement par un endpoint d'audit dédié.

    Idempotent côté disque : un fichier déjà absent ne fait pas échouer.
    """
    entity = db.scalar(
        select(Entity)
        .options(joinedload(Entity.aliases), joinedload(Entity.images))
        .where(Entity.slug == slug)
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")

    # Snapshot avant cascade — pour les compteurs et la suppression disque
    name = entity.name
    files_to_remove: list[_Path] = []
    for img in entity.images:
        if img.local_path:
            files_to_remove.append(_Path(img.local_path))
        if img.aligned_path:
            files_to_remove.append(_Path(img.aligned_path))

    images_count = len(entity.images)
    aliases_count = len(entity.aliases)

    # Articles potentiellement orphelins APRÈS la suppression
    article_ids = [
        row[0]
        for row in db.execute(
            select(ArticleEntity.article_id).where(
                ArticleEntity.entity_id == entity.id
            )
        )
    ]

    # Suppression manuelle des liens article_entities (cascade FK SQL non
    # garantie : SQLite n'active pas les FK par défaut ; cf. spec §4.9)
    article_links_removed = db.execute(
        ArticleEntity.__table__.delete().where(
            ArticleEntity.entity_id == entity.id
        )
    ).rowcount

    # Suppression des images (déclenche la cascade ORM vers face_analysis)
    for img in list(entity.images):
        db.delete(img)
    db.flush()

    db.delete(entity)  # cascade ORM aliases ; trigger FTS5 nettoie entities_fts
    db.commit()

    # Compte les articles devenus orphelins
    orphan_articles = 0
    for article_id in article_ids:
        still_linked = db.scalar(
            select(func.count())
            .select_from(ArticleEntity)
            .where(ArticleEntity.article_id == article_id)
        )
        if not still_linked:
            orphan_articles += 1

    files_removed = 0
    for path in files_to_remove:
        try:
            if path.exists():
                path.unlink()
                files_removed += 1
        except OSError:
            pass

    return PurgeEntityResult(
        slug=slug,
        name=name,
        images_removed=images_count,
        aliases_removed=aliases_count,
        article_links_removed=article_links_removed,
        files_removed=files_removed,
        orphan_articles=orphan_articles,
    )


@app.get("/entities/{slug}", response_model=EntityDetail)
def get_entity(slug: str, db: Session = Depends(get_db)):
    entity = db.scalar(
        select(Entity)
        .options(joinedload(Entity.aliases))
        .where(Entity.slug == slug)
    )
    if entity is None or entity.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail="entity not found")
    return _entity_detail(entity)


@app.get("/entities/{slug}/export.jpg")
def export_entity_jpg(slug: str, db: Session = Depends(get_db)):
    """Planche composite JPG (spec §11.6).

    Sélectionne les images alignées non-doublons et non-flagged, triées
    par date de scrape (plus ancienne d'abord), max 24. La typographie
    Cormorant Garamond / Space Mono est récupérée la 1re fois et cachée.
    """
    from export import render_entity_jpg

    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None or entity.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail="entity not found")

    images = (
        db.execute(
            select(Image)
            .where(
                Image.entity_id == entity.id,
                Image.aligned_path.is_not(None),
                Image.is_duplicate.is_(False),
                Image.association_status != "flagged",
            )
            .order_by(Image.scraped_at)
            .limit(24)
        )
        .scalars()
        .all()
    )
    paths = [_Path(img.aligned_path) for img in images if img.aligned_path]

    jpg_bytes = render_entity_jpg(entity, paths)
    return Response(
        content=jpg_bytes,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="face_ai_{slug}.jpg"'
        },
    )


@app.get("/entities/{slug}/timeline")
def get_entity_timeline(
    slug: str,
    db: Session = Depends(get_db),
):
    """Heatmap-style timeline d'une entité — densité d'apparition par
    jour sur les 365 derniers jours.

    Compte les articles distincts (pas les images) où l'entité est
    mentionnée, par `published_at`. Un pic visible = événement
    médiatique (élection, scandale, sortie d'album).

    Retourne :
    - `days` : liste compactée `[{date: "2026-05-12", count: 3}, …]`,
      uniquement les jours avec activité (≥1 article)
    - `total_days` : nombre de jours distincts avec ≥1 article
    - `total_articles` : nombre total d'articles sur la fenêtre
    - `max_count` : pic max (utile côté UI pour graduer la couleur)
    - `from`, `to` : bornes de la fenêtre (ISO date)
    """
    from datetime import timedelta

    entity = db.scalar(
        select(Entity).where(Entity.slug == slug)
    )
    if entity is None or entity.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail="entity not found")

    to_date = date.today()
    from_date = to_date - timedelta(days=365)

    # Compte par jour via published_at de articles liés à l'entité
    rows = db.execute(
        select(
            Article.published_at,
            func.count(func.distinct(Article.id)).label("n"),
        )
        .join(ArticleEntity, ArticleEntity.article_id == Article.id)
        .where(
            ArticleEntity.entity_id == entity.id,
            Article.published_at.is_not(None),
            Article.published_at >= from_date,
            Article.published_at <= to_date,
        )
        .group_by(Article.published_at)
        .order_by(Article.published_at)
    ).all()

    days = [
        {"date": row.published_at.isoformat(), "count": int(row.n)}
        for row in rows
    ]
    total_articles = sum(d["count"] for d in days)
    max_count = max((d["count"] for d in days), default=0)

    return {
        "slug": slug,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "total_days": len(days),
        "total_articles": total_articles,
        "max_count": max_count,
        "days": days,
    }


@app.get("/entities/{slug}/images", response_model=EntityImagesResponse)
def get_entity_images(
    slug: str,
    pose: PoseFilter | None = None,
    unique: bool = False,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(24, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    entity = db.scalar(
        select(Entity)
        .options(joinedload(Entity.aliases))
        .where(Entity.slug == slug)
    )
    if entity is None or entity.wikidata_status == NOT_PERSON_STATUS:
        raise HTTPException(status_code=404, detail="entity not found")

    base = (
        select(Image)
        .options(
            joinedload(Image.article),
            joinedload(Image.face_analysis),
        )
        .where(Image.entity_id == entity.id)
    )
    total = db.scalar(
        select(func.count()).select_from(Image).where(Image.entity_id == entity.id)
    ) or 0

    if pose is not None:
        base = base.where(Image.face_analysis.has(pose=pose))
    if unique:
        base = base.where(Image.is_duplicate.is_(False))
    if status is not None:
        base = base.where(Image.analysis_status == status)
    if date_from is not None or date_to is not None:
        base = base.join(Image.article)
        if date_from is not None:
            base = base.where(Article.published_at >= date_from)
        if date_to is not None:
            base = base.where(Article.published_at <= date_to)

    filtered_total = db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    rows = db.execute(base.limit(limit).offset(offset)).unique().scalars().all()

    images = [
        ImageOut(
            id=img.id,
            source_url=img.source_url,
            aligned_url=(
                f"/static/aligned/{img.id}.jpg" if img.aligned_path else None
            ),
            caption=img.caption,
            copyright=img.copyright_text,
            scrape_status=img.scrape_status,
            analysis_status=img.analysis_status,
            is_duplicate=bool(img.is_duplicate),
            association_status=img.association_status,
            identity_match_score=img.identity_match_score,
            article=(
                ArticleRefOut.model_validate(img.article) if img.article else None
            ),
            face=(
                FaceOut.model_validate(img.face_analysis)
                if img.face_analysis
                else None
            ),
        )
        for img in rows
    ]

    return EntityImagesResponse(
        entity=_entity_detail(entity),
        images=images,
        total=total,
        filtered=filtered_total,
    )
