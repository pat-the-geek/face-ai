"""Serveur MCP FACE.ai — interface pour agents IA (spec §12).

Expose les fonctions de consultation de la base FACE.ai sous forme d'outils
Model Context Protocol. Un agent connecté (Claude Desktop, Claude Code, etc.)
peut chercher des entités, comparer des trajectoires médiatiques et obtenir
le contexte factuel nécessaire pour produire des analyses éditoriales.

Transport :
- SSE (par défaut) sur 0.0.0.0:8001 — service Docker
- stdio si invoqué depuis Claude Desktop avec `python face_ai_mcp_server.py --stdio`

Déliberément séparé de l'API REST FastAPI : le MCP n'importe ni mediapipe ni
opencv, il ne touche que la DB. Démarrage instantané, pas de coût mémoire vision.
"""
import sys
from collections import defaultdict
from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import joinedload

from database import (
    Article,
    ArticleEntity,
    Entity,
    FaceAnalysis,
    Image,
    SessionLocal,
)

# Seuil de bascule auto/flagged en distance cosine ArcFace (cf. identity.py).
# Dupliqué ici en module-level pour ne pas faire importer InsightFace par le MCP
# (qui n'a aucune raison de charger 120 MB de modèles vision pour servir des
# requêtes DB). Garder synchronisé avec identity.IDENTITY_THRESHOLD.
ARCFACE_FLAGGED_THRESHOLD = 0.55

mcp = FastMCP("face-ai", host="0.0.0.0", port=8001)


# ──────────────────────────────────────────────────────────────────────
# Outils de consultation
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def search_entities(query: str, limit: int = 10) -> dict:
    """Recherche d'entités PERSON dans FACE.ai par nom ou alias.

    Utilise l'index FTS5 avec wildcard préfixe (insensible aux accents).
    Retourne les correspondances triées par pertinence avec leurs statistiques
    de couverture (nombre d'images, d'articles, score de diversité).

    Premier appel à faire pour explorer le corpus avant tout autre outil.

    **Forme de réponse** : `{"count": N, "results": [{...}, ...]}`. Le wrapping
    dict (au lieu de `list[dict]` directe) garantit qu'un client MCP reçoit
    **un seul bloc TextContent** avec une liste claire — sinon le SDK MCP
    sérialise chaque dict en bloc séparé, ce qui force le LLM à recoller.
    """
    parts = ["".join(c for c in p if c.isalnum()) for p in query.split()]
    fts_query = " ".join(f"{p}*" for p in parts if p)
    if not fts_query:
        return {"count": 0, "results": []}

    db = SessionLocal()
    try:
        stmt = text(
            """
            SELECT e.id, e.name, e.slug,
                   e.article_count, e.image_count, e.diversity_score,
                   e.is_favorite
              FROM entities_fts f
              JOIN entities e ON e.id = f.rowid
             WHERE entities_fts MATCH :q
               AND COALESCE(e.wikidata_status, '') != 'not_person'
             ORDER BY rank
             LIMIT :limit
            """
        ).bindparams(bindparam("q", fts_query), bindparam("limit", limit))
        rows = db.execute(stmt).mappings().all()
        results = []
        for r in rows:
            d = dict(r)
            d["is_favorite"] = bool(d.get("is_favorite"))
            results.append(d)
        return {"count": len(results), "results": results}
    finally:
        db.close()


@mcp.tool()
def get_entity_profile(slug: str) -> dict:
    """Profil complet d'une entité avec statistiques visuelles.

    Inclut : aliases, distribution des poses (face/profils), sources médias
    distinctes, plage temporelle de couverture, nombre de doublons détectés.
    Tout le contexte factuel disponible sans charger les images elles-mêmes.

    Deux champs temporels **distincts** à ne pas confondre :
    - `entity_created_at` : date d'insertion de l'entité dans FACE.ai
      (métadonnée système — peut être très postérieure à la couverture
      éditoriale si l'entité a été ajoutée tard ou recréée via unmerge).
    - `date_range.from`/`to` : plage des dates de publication des articles
      du corpus mentionnant cette entité (couverture éditoriale réelle).
    """
    db = SessionLocal()
    try:
        entity = db.scalar(select(Entity).where(Entity.slug == slug))
        if entity is None or entity.wikidata_status == "not_person":
            return {"error": f"entité '{slug}' introuvable"}

        aliases = [a.alias for a in entity.aliases]

        pose_rows = db.execute(
            select(FaceAnalysis.pose, func.count())
            .join(Image, Image.id == FaceAnalysis.image_id)
            .where(Image.entity_id == entity.id)
            .group_by(FaceAnalysis.pose)
        ).all()
        pose_distribution = {
            row[0] or "unknown": row[1] for row in pose_rows
        }

        source_rows = db.execute(
            select(Article.source_domain, func.count(func.distinct(Image.id)))
            .join(Image, Image.article_id == Article.id)
            .where(Image.entity_id == entity.id)
            .group_by(Article.source_domain)
        ).all()
        sources = {row[0] or "unknown": row[1] for row in source_rows}

        date_min, date_max = db.execute(
            select(
                func.min(Article.published_at),
                func.max(Article.published_at),
            )
            .join(Image, Image.article_id == Article.id)
            .where(Image.entity_id == entity.id)
        ).first()

        duplicate_count = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(
                    Image.entity_id == entity.id,
                    Image.is_duplicate.is_(True),
                )
            )
            or 0
        )

        nationalities = [s for s in (entity.nationalities or "").split("|") if s]
        occupations = [s for s in (entity.occupations or "").split("|") if s]

        # Deux champs **distincts** sémantiquement (cf. rapport de test
        # MCP 2026-05-12 : un fallback masquait l'écart) :
        # - `entity_created_at` : métadonnée système, quand FACE.ai a
        #   inséré l'entité en DB (scraper ou unmerge récent → peut être
        #   très postérieur à la couverture éditoriale).
        # - `date_range.from` : min(Article.published_at) — couverture
        #   éditoriale réelle dans le corpus.
        # On expose les deux sans amalgame ; le LLM peut alors raisonner
        # correctement sur "depuis quand on suit X" vs "première mention".
        entity_created_iso = (
            entity.first_seen.isoformat() if entity.first_seen else None
        )

        # `diversity_score` = moyenne des distances pHash pairwise entre
        # images uniques. Indéfini sur < 2 images uniques — on renvoie 0 par
        # convention mais on explicite la valeur sentinelle pour éviter
        # qu'un LLM interprète "0" comme "couverture totalement uniforme".
        unique_count = entity.unique_image_count or 0
        diversity_note = (
            "non significatif : moins de 2 images uniques"
            if unique_count < 2
            else None
        )

        return {
            "id": entity.id,
            "name": entity.name,
            "slug": entity.slug,
            "aliases": aliases,
            "article_count": entity.article_count,
            "image_count": entity.image_count,
            "unique_image_count": unique_count,
            "diversity_score": entity.diversity_score,
            "diversity_note": diversity_note,
            "entity_created_at": entity_created_iso,
            "pose_distribution": pose_distribution,
            "sources_distribution": sources,
            "date_range": {
                "from": date_min.isoformat() if date_min else None,
                "to": date_max.isoformat() if date_max else None,
            },
            "duplicate_count": duplicate_count,
            # Bio Wikidata (spec §9.3)
            "wikidata_qid": entity.wikidata_qid,
            "wikipedia_summary": entity.wiki_summary,
            "wikipedia_url": entity.wiki_url,
            "birth_date": entity.birth_date.isoformat() if entity.birth_date else None,
            "death_date": entity.death_date.isoformat() if entity.death_date else None,
            "birth_place": entity.birth_place,
            "death_place": entity.death_place,
            "nationalities": nationalities,
            "occupations": occupations,
            "employer": entity.employer,
        }
    finally:
        db.close()


@mcp.tool()
def get_entity_images(
    slug: str,
    pose: Literal["any", "front", "left", "right"] = "any",
    unique_only: bool = True,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> dict:
    """Liste des images d'une entité avec leurs métadonnées.

    Filtres :
    - pose : 'any', 'front', 'left' (profil gauche), 'right' (profil droit)
    - unique_only : exclure les doublons (recommandé, défaut True)
    - date_from / date_to : format ISO 'YYYY-MM-DD'
    - limit : 20 par défaut

    Pour chaque image : URL source, URL alignée, caption, copyright,
    pose/angles faciaux détectés, article source.
    """
    db = SessionLocal()
    try:
        entity = db.scalar(select(Entity).where(Entity.slug == slug))
        if entity is None or entity.wikidata_status == "not_person":
            return {"error": f"entité '{slug}' introuvable", "images": []}

        q = select(Image).where(Image.entity_id == entity.id)
        if pose != "any":
            q = q.where(Image.face_analysis.has(pose=pose))
        if unique_only:
            q = q.where(Image.is_duplicate.is_(False))
        if date_from or date_to:
            q = q.join(Image.article)
            if date_from:
                q = q.where(Article.published_at >= date.fromisoformat(date_from))
            if date_to:
                q = q.where(Article.published_at <= date.fromisoformat(date_to))

        rows = db.execute(q.limit(limit)).scalars().unique().all()

        images = []
        for img in rows:
            face = img.face_analysis
            article = img.article
            images.append(
                {
                    "id": img.id,
                    "source_url": img.source_url,
                    "aligned_url": (
                        f"/static/aligned/{img.id}.jpg"
                        if img.aligned_path
                        else None
                    ),
                    "caption": img.caption,
                    "copyright": img.copyright_text,
                    "pose": face.pose if face else None,
                    "yaw": face.yaw if face else None,
                    "confidence": face.confidence if face else None,
                    "article": (
                        {
                            "title": article.title,
                            "url": article.url,
                            "published_at": (
                                article.published_at.isoformat()
                                if article.published_at
                                else None
                            ),
                            "source_domain": article.source_domain,
                        }
                        if article
                        else None
                    ),
                }
            )
        return {
            "entity": entity.name,
            "slug": entity.slug,
            "count": len(images),
            "images": images,
        }
    finally:
        db.close()


@mcp.tool()
def compare_entities(slug_a: str, slug_b: str) -> dict:
    """Comparaison statistique de deux entités.

    Volume de couverture, diversité, et **cooccurrences** : nombre d'articles
    où les deux entités apparaissent ensemble. Utile pour analyser les
    relations (rivalité, association éditoriale, agenda commun).
    """
    db = SessionLocal()
    try:
        a = db.scalar(select(Entity).where(Entity.slug == slug_a))
        b = db.scalar(select(Entity).where(Entity.slug == slug_b))
        if (
            not a or not b
            or a.wikidata_status == "not_person"
            or b.wikidata_status == "not_person"
        ):
            return {"error": "une ou les deux entités introuvables"}

        cooccurrence = (
            db.scalar(
                select(func.count())
                .select_from(ArticleEntity)
                .where(
                    ArticleEntity.article_id.in_(
                        select(ArticleEntity.article_id).where(
                            ArticleEntity.entity_id == a.id
                        )
                    ),
                    ArticleEntity.entity_id == b.id,
                )
            )
            or 0
        )

        def _stats(entity: Entity) -> dict:
            return {
                "name": entity.name,
                "slug": entity.slug,
                "image_count": entity.image_count,
                "article_count": entity.article_count,
                "diversity_score": entity.diversity_score,
            }

        return {
            "entities": {a.slug: _stats(a), b.slug: _stats(b)},
            "cooccurrence_articles": cooccurrence,
        }
    finally:
        db.close()


@mcp.tool()
def get_media_timeline(
    slug: str,
    granularity: Literal["day", "week", "month"] = "week",
) -> dict:
    """Densité d'apparition d'une entité dans le temps.

    Agrège les images par jour, semaine ISO ou mois selon `granularity`.
    Identifie les pics de visibilité et permet de poser la question des
    causes (événement déclencheur, polémique, sortie produit).
    """
    db = SessionLocal()
    try:
        entity = db.scalar(select(Entity).where(Entity.slug == slug))
        if entity is None or entity.wikidata_status == "not_person":
            return {"error": f"entité '{slug}' introuvable"}

        rows = db.execute(
            select(Article.published_at, func.count())
            .join(Image, Image.article_id == Article.id)
            .where(
                Image.entity_id == entity.id,
                Article.published_at.is_not(None),
            )
            .group_by(Article.published_at)
            .order_by(Article.published_at)
        ).all()

        bucketed: dict[str, int] = defaultdict(int)
        for d, count in rows:
            if granularity == "day":
                key = d.isoformat()
            elif granularity == "month":
                key = d.strftime("%Y-%m")
            else:
                year, week, _ = d.isocalendar()
                key = f"{year}-W{week:02d}"
            bucketed[key] += count

        return {
            "entity": entity.name,
            "granularity": granularity,
            "buckets": [
                {"period": k, "count": v} for k, v in sorted(bucketed.items())
            ],
        }
    finally:
        db.close()


@mcp.tool()
def list_favorites(limit: int = 50) -> dict:
    """Liste les entités marquées favorites par l'utilisateur (★).

    Triées par volume d'images décroissant. Permet à un agent de répondre à
    "quelles sont mes entités prioritaires ?" sans devoir d'abord faire un
    `get_corpus_stats` puis filtrer.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Entity)
            .where(Entity.is_favorite.is_(True))
            .order_by(Entity.image_count.desc(), Entity.name)
            .limit(limit)
        ).scalars().all()
        results = [
            {
                "name": e.name,
                "slug": e.slug,
                "image_count": e.image_count,
                "unique_image_count": e.unique_image_count or 0,
                "article_count": e.article_count,
                "diversity_score": e.diversity_score,
                "wikidata_qid": e.wikidata_qid,
            }
            for e in rows
        ]
        return {"count": len(results), "results": results}
    finally:
        db.close()


@mcp.tool()
def list_flagged_images(limit: int = 50) -> dict:
    """Images dont l'audit ArcFace a flaggé l'association comme suspecte (spec §5.5).

    Le score `identity_match_score` est une **distance cosine** au centroïde
    ArcFace de l'entité (vecteurs L2-normalisés, valeurs typiques 0.0–1.0).
    Seuil de bascule : distance > `ARCFACE_FLAGGED_THRESHOLD` (0.55) → `flagged`.
    Donc plus la valeur est élevée, plus l'image est éloignée de l'identité
    de référence — i.e. plus l'attribution est suspecte. Tri décroissant :
    les pires en haut.

    Pour chaque image : entité actuellement attribuée, score, caption, article
    source, et **`face_count`** (nombre de visages détectés dans l'image
    source). Quand `face_count > 1`, l'écart au centroïde peut s'expliquer
    par une **composition multi-personnes** plutôt que par une vraie
    erreur d'attribution — l'agent doit le prendre en compte avant de
    proposer un re-tag.

    Permet à un agent de prioriser le workflow audit P9 (`/audit` côté UI)
    ou de proposer des décisions.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Image)
            .options(
                joinedload(Image.entity),
                joinedload(Image.article),
                joinedload(Image.face_analysis),
            )
            .where(Image.association_status == "flagged")
            .order_by(Image.identity_match_score.desc().nulls_last())
            .limit(limit)
        ).scalars().all()
        results = []
        for img in rows:
            fa = img.face_analysis
            face_count = fa.face_count if fa else None
            results.append(
                {
                    "id": img.id,
                    "entity_slug": img.entity.slug if img.entity else None,
                    "entity_name": img.entity.name if img.entity else None,
                    "identity_match_score": img.identity_match_score,
                    "caption": img.caption,
                    "source_url": img.source_url,
                    "aligned_url": (
                        f"/static/aligned/{img.id}.jpg"
                        if img.aligned_path
                        else None
                    ),
                    "article_title": img.article.title if img.article else None,
                    "article_url": img.article.url if img.article else None,
                    "face_count": face_count,
                    "flag_hypothesis": (
                        "multi_person_composition"
                        if face_count and face_count > 1
                        else (
                            "likely_misattribution"
                            if face_count == 1
                            else "unknown"
                        )
                    ),
                }
            )
        return {
            "count": len(results),
            "flagging_threshold": ARCFACE_FLAGGED_THRESHOLD,
            "score_meaning": (
                "distance cosine au centroïde ArcFace de l'entité ; "
                f"bascule en `flagged` au-dessus de {ARCFACE_FLAGGED_THRESHOLD}"
            ),
            "flag_hypothesis_legend": {
                "multi_person_composition": (
                    "Plusieurs visages détectés (face_count>1) : l'écart au "
                    "centroïde peut venir du fait qu'on a aligné un visage "
                    "secondaire. L'attribution textuelle reste probablement "
                    "valide."
                ),
                "likely_misattribution": (
                    "Un seul visage dans l'image — l'écart au centroïde "
                    "suggère une vraie erreur d'attribution. Priorité audit."
                ),
                "unknown": (
                    "face_count non renseigné (image antérieure à v025). "
                    "Lancer `python face_processor.py --backfill-face-count`."
                ),
            },
            "results": results,
        }
    finally:
        db.close()


@mcp.tool()
def get_corpus_stats() -> dict:
    """Vue d'ensemble du corpus FACE.ai.

    Totaux (entités, images, articles), top 10 entités par volume,
    distribution globale par pose, taux d'alignement.
    Premier appel pour comprendre l'état général du système.
    """
    db = SessionLocal()
    try:
        # Exclure les tombstones not_person des totaux et du top — sinon
        # ils gonflent artificiellement le compte d'entités alors qu'ils
        # n'ont aucun contenu visible.
        not_person_filter = (Entity.wikidata_status.is_(None)) | (
            Entity.wikidata_status != "not_person"
        )
        total_entities = (
            db.scalar(
                select(func.count()).select_from(Entity).where(not_person_filter)
            )
            or 0
        )
        total_images = db.scalar(select(func.count()).select_from(Image)) or 0
        total_articles = db.scalar(select(func.count()).select_from(Article)) or 0

        aligned = (
            db.scalar(
                select(func.count())
                .select_from(Image)
                .where(Image.aligned_path.is_not(None))
            )
            or 0
        )

        top_rows = db.execute(
            select(Entity.name, Entity.slug, Entity.image_count)
            .where(not_person_filter)
            .order_by(Entity.image_count.desc())
            .limit(10)
        ).all()

        pose_rows = db.execute(
            select(FaceAnalysis.pose, func.count()).group_by(FaceAnalysis.pose)
        ).all()

        return {
            "totals": {
                "entities": total_entities,
                "images": total_images,
                "articles": total_articles,
            },
            "alignment_rate": (
                round(aligned / total_images, 3) if total_images else 0.0
            ),
            "top_entities": [
                {"name": r[0], "slug": r[1], "image_count": r[2]}
                for r in top_rows
            ],
            "pose_distribution": {
                row[0] or "unknown": row[1] for row in pose_rows
            },
        }
    finally:
        db.close()


@mcp.tool()
def analyze_visibility_pattern(slug: str) -> dict:
    """Agrège tout le contexte factuel d'une entité pour analyse par LLM.

    **Cet outil ne fait pas l'analyse** — il rassemble en un seul appel :
    profil, timeline mensuelle, échantillon de titres d'articles, statistiques.
    L'agent appelant doit ensuite formuler son propre récit éditorial à partir
    de ces faits (pics anormaux, sources dominantes, thèmes récurrents…).

    À utiliser comme socle factuel pour les prompts `portrait_editorial` ou
    `visibility_anomaly_report` (voir spec §12.5).
    """
    profile = get_entity_profile(slug)
    if "error" in profile:
        return profile

    timeline = get_media_timeline(slug, granularity="month")
    images = get_entity_images(slug, unique_only=True, limit=50)

    db = SessionLocal()
    try:
        entity_id = db.scalar(select(Entity.id).where(Entity.slug == slug))
        title_rows = db.execute(
            select(Article.title, Article.published_at, Article.source_domain)
            .join(Image, Image.article_id == Article.id)
            .where(Image.entity_id == entity_id)
            .distinct()
            .limit(50)
        ).all()
    finally:
        db.close()

    article_titles = [
        {
            "title": r[0],
            "date": r[1].isoformat() if r[1] else None,
            "source": r[2],
        }
        for r in title_rows
    ]

    return {
        "profile": profile,
        "timeline_monthly": timeline.get("buckets", []),
        "article_titles": article_titles,
        "image_count_unique": images.get("count", 0),
        "instructions_for_llm": (
            "Ces données représentent la couverture médiatique de cette entité "
            "dans le corpus WUDD.ai/FACE.ai. À partir d'elles, identifier : "
            "(1) pics ou creux anormaux de visibilité et hypothèses causales, "
            "(2) sources dominantes et angles éditoriaux, "
            "(3) diversité des poses comme proxy de couverture variée vs. "
            "    répétitive (un seul portrait recyclé est un signal faible), "
            "(4) thèmes récurrents dans les titres, "
            "(5) évolution dans le temps."
        ),
    }


@mcp.tool()
def list_flagged_by_period(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
) -> dict:
    """Entités avec images flaggées sur une période donnée (endpoint inversé).

    Symétrique de `list_flagged_images` : au lieu de lister N images, on
    regroupe par entité pour répondre à "quelles entités cumulent des
    attributions suspectes sur la période X-Y ?". Utile pour repérer les
    pics de mauvaise attribution corrélés à un événement (procès, sortie
    produit, polémique) — cf. cas Musk W18-W19 dans le rapport de test
    MCP_TEST_REPORT.md §6.

    Filtre par `Article.published_at` (pas `scraped_at`) : on regarde quand
    le contenu a paru, pas quand on l'a ingéré. Tri décroissant par nombre
    d'images flaggées.

    Format ISO `YYYY-MM-DD` pour les dates. Sans filtre, retourne le
    classement global toutes périodes confondues.
    """
    db = SessionLocal()
    try:
        q = (
            select(
                Entity.slug,
                Entity.name,
                Entity.image_count,
                func.count(Image.id).label("flagged_count"),
                func.avg(Image.identity_match_score).label("avg_score"),
                func.min(Article.published_at).label("first_flagged"),
                func.max(Article.published_at).label("last_flagged"),
            )
            .join(Image, Image.entity_id == Entity.id)
            .join(Article, Article.id == Image.article_id)
            .where(Image.association_status == "flagged")
        )
        if date_from:
            q = q.where(Article.published_at >= date.fromisoformat(date_from))
        if date_to:
            q = q.where(Article.published_at <= date.fromisoformat(date_to))
        q = (
            q.group_by(Entity.id)
            .order_by(func.count(Image.id).desc())
            .limit(limit)
        )
        rows = db.execute(q).all()

        results = []
        for r in rows:
            flagged = r.flagged_count or 0
            total = r.image_count or 0
            # Sur-représentation : ratio flagged/total de l'entité vs. corpus.
            # Calcul du ratio entité même avec total nul (protection /0).
            entity_ratio = (flagged / total) if total else None
            results.append(
                {
                    "slug": r.slug,
                    "name": r.name,
                    "flagged_count": flagged,
                    "total_images": total,
                    "flagged_ratio": (
                        round(entity_ratio, 3) if entity_ratio is not None else None
                    ),
                    "avg_match_score": (
                        round(float(r.avg_score), 4) if r.avg_score is not None else None
                    ),
                    "first_flagged": r.first_flagged.isoformat() if r.first_flagged else None,
                    "last_flagged": r.last_flagged.isoformat() if r.last_flagged else None,
                }
            )
        return {
            "date_from": date_from,
            "date_to": date_to,
            "count": len(results),
            "flagging_threshold": ARCFACE_FLAGGED_THRESHOLD,
            "results": results,
        }
    finally:
        db.close()


@mcp.tool()
def find_duplicate_candidates(limit: int = 30) -> dict:
    """Surfacer des entités probables doublons à fusionner.

    Trois catégories signalées :

    1. **same_qid** : entités partageant un `wikidata_qid` non-null →
       auto-mergeables par `entity_merge.auto_merge_by_qid` (le worker le
       fait toutes les 2 min). Si on en voit ici, c'est que le worker n'a
       pas encore tourné ou est arrêté.

    2. **same_surname** : entités dont le nom canonique partage le même
       "nom de famille" (segment avant la virgule, ou première lettre
       majuscule si pas de virgule). Cas typique : `Trump, Donald` vs
       `Trump` — même personne en notation longue/courte. Faux positifs
       attendus pour les vrais homonymes (Macron Emmanuel vs Macron Brigitte) ;
       le LLM doit trancher.

    3. **alias_collision** : entités dont le nom ou un alias correspond
       exactement à un alias d'une autre entité → indique probablement une
       fusion ratée ou une canonicalisation incohérente.

    Pour chaque candidat : suggérer `POST /entities/{canonical}/merge?source={dup}`
    où canonical = entité avec le plus d'images. Décision humaine requise
    pour les catégories 2 et 3.
    """
    from duplicate_finder import find_candidates

    result = find_candidates(limit=limit)
    result["instructions_for_llm"] = (
        "Pour chaque groupe, choisir le canonical (image_count max), "
        "vérifier qu'il s'agit bien de la même personne, et proposer "
        "à l'utilisateur la fusion via `POST /entities/{canonical}/merge"
        "?source={duplicate}`. Les `same_qid` peuvent être fusionnés "
        "sans confirmation (preuve Wikidata). Les `same_surname` "
        "incluent des homonymes légitimes (Macron Emmanuel vs Macron "
        "Brigitte) — ne JAMAIS proposer ces fusions sans validation."
    )
    return result


# ──────────────────────────────────────────────────────────────────────
# Ressources MCP (spec §12.4) — exposent l'état du corpus comme des
# "fichiers" lisibles par l'agent. Une ressource = un GET idempotent
# qui retourne du texte structuré, sans paramètres au-delà du chemin
# URI.
# ──────────────────────────────────────────────────────────────────────


@mcp.resource("face://stats")
def resource_stats() -> str:
    """Stats globales du corpus — entités totales, ratios, événements
    worker récents. Affichée comme contexte permanent pour l'agent.
    """
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(Entity)) or 0
        not_person = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(Entity.wikidata_status == "not_person")
            )
            or 0
        )
        person = total - not_person
        favorites = (
            db.scalar(
                select(func.count())
                .select_from(Entity)
                .where(Entity.is_favorite.is_(True))
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
        total_articles = db.scalar(select(func.count()).select_from(Article)) or 0
        flagged_ratio = (flagged_images / total_images) if total_images else 0.0
    finally:
        db.close()

    lines = [
        "# Corpus FACE.ai — snapshot",
        f"- Personnes : {person} (sur {total} entités, {not_person} tombstones not_person)",
        f"- Favoris : {favorites}",
        f"- Images : {total_images} (dont {flagged_images} flagged, ratio {flagged_ratio:.2%})",
        f"- Articles : {total_articles}",
    ]
    return "\n".join(lines)


@mcp.resource("face://entities")
def resource_entities_list() -> str:
    """Liste compacte des entités PERSON — un par ligne au format
    `slug · Nom canonique (image_count img)`. Réservé aux personnes
    valides (exclut not_person). Utile pour permettre à l'agent de
    parcourir le corpus sans appel d'outil.

    Limité aux 500 premières par image_count desc pour rester sous une
    taille raisonnable de contexte (sinon, utiliser `search_entities`).
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Entity)
            .where(Entity.wikidata_status != "not_person")
            .order_by(Entity.image_count.desc(), Entity.name)
            .limit(500)
        ).scalars().all()
    finally:
        db.close()

    lines = [
        f"# Top 500 entités FACE.ai (par volume d'images)",
        "",
    ]
    for e in rows:
        lines.append(
            f"- `{e.slug}` · {e.name} ({e.image_count or 0} img, {e.article_count or 0} art)"
        )
    return "\n".join(lines)


@mcp.resource("face://entity/{slug}")
def resource_entity_detail(slug: str) -> str:
    """Carte d'identité Markdown d'une entité — bio Wikidata, compteurs,
    favoris, période d'activité. À distinguer de l'outil
    `get_entity_profile` (qui retourne du JSON pour analyse) : la
    ressource est en Markdown pour lecture humaine et inclusion directe
    dans le contexte agent.
    """
    db = SessionLocal()
    try:
        entity = db.scalar(select(Entity).where(Entity.slug == slug))
        if entity is None or entity.wikidata_status == "not_person":
            return f"# Entité `{slug}` introuvable\n"

        lines = [f"# {entity.name}"]
        if entity.wikidata_qid:
            lines.append(
                f"- **Wikidata** : [{entity.wikidata_qid}](https://www.wikidata.org/wiki/{entity.wikidata_qid})"
            )
        if entity.wiki_url:
            lines.append(f"- **Wikipedia** : {entity.wiki_url}")
        if entity.birth_date:
            line = f"- **Naissance** : {entity.birth_date.isoformat()}"
            if entity.birth_place:
                line += f" ({entity.birth_place})"
            lines.append(line)
        if entity.death_date:
            line = f"- **Décès** : {entity.death_date.isoformat()}"
            if entity.death_place:
                line += f" ({entity.death_place})"
            lines.append(line)
        if entity.nationalities:
            lines.append(f"- **Nationalité** : {entity.nationalities.replace('|', ', ')}")
        if entity.occupations:
            lines.append(f"- **Occupations** : {entity.occupations.replace('|', ', ')}")
        if entity.employer:
            lines.append(f"- **Employeur** : {entity.employer}")
        lines.append(
            f"- **Corpus FACE.ai** : {entity.image_count or 0} images, "
            f"{entity.article_count or 0} articles"
            + (" · ★ favori" if entity.is_favorite else "")
        )

        if entity.wiki_summary:
            lines.extend(["", "## Résumé", "", entity.wiki_summary])

        return "\n".join(lines)
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────
# Prompts MCP (spec §12.5) — modèles pré-configurés pour les analyses
# typiques. Chaque prompt produit une instruction structurée que l'agent
# peut exécuter directement.
# ──────────────────────────────────────────────────────────────────────


@mcp.prompt()
def portrait_editorial(slug: str) -> str:
    """Génère un portrait éditorial complet d'une personne — bio
    Wikidata + chiffres FACE.ai + lecture de la trajectoire médiatique.

    Le prompt rendu indique à l'agent d'utiliser les outils MCP pour
    récupérer le profil et la timeline, puis de structurer en 5
    sections (carte d'identité, contexte médiatique, pics d'activité,
    diversité visuelle, points de vigilance).
    """
    return (
        f"Produis un portrait éditorial de l'entité `{slug}` du corpus FACE.ai.\n\n"
        f"**Étapes** :\n"
        f"1. Lis la ressource `face://entity/{slug}` pour la carte d'identité.\n"
        f"2. Appelle l'outil `get_entity_profile` avec `slug=\"{slug}\"` pour les compteurs.\n"
        f"3. Appelle `analyze_visibility_pattern` avec `slug=\"{slug}\"` pour la trajectoire.\n\n"
        f"**Structure attendue** (Markdown) :\n"
        f"- **Carte d'identité** : nom canonique, dates, nationalité, occupation, employeur actuel.\n"
        f"- **Présence dans le corpus** : nombre d'images / articles, période couverte, ★ si favori.\n"
        f"- **Trajectoire médiatique** : pics d'activité (mois ou semaines), événements probables.\n"
        f"- **Diversité visuelle** : score de diversité (variance des portraits), interprétation.\n"
        f"- **Points de vigilance** : flagged ArcFace > seuil, images DDG hors corpus, etc.\n\n"
        f"Sois factuel, sourcé, et signale toute donnée manquante explicitement."
    )


@mcp.prompt()
def media_comparison(slug_a: str, slug_b: str) -> str:
    """Compare deux personnes du corpus — trajectoires médiatiques,
    cooccurrences, intersection d'événements.
    """
    return (
        f"Compare la présence médiatique de `{slug_a}` et `{slug_b}` dans FACE.ai.\n\n"
        f"**Étapes** :\n"
        f"1. Appelle `compare_entities` avec les deux slugs.\n"
        f"2. Lis `face://entity/{slug_a}` et `face://entity/{slug_b}` pour le contexte bio.\n"
        f"3. Appelle `analyze_visibility_pattern` sur chaque pour les trajectoires temporelles.\n\n"
        f"**Structure attendue** :\n"
        f"- **Profils croisés** : occupation, employeur, nationalité — convergences/divergences.\n"
        f"- **Volumétrie comparée** : images, articles, période, score de diversité (tableau).\n"
        f"- **Cooccurrences** : articles où les deux apparaissent ensemble (si présent dans `compare_entities`).\n"
        f"- **Trajectoires** : superposition des pics — événements communs (sommets, scandales partagés, etc.).\n"
        f"- **Conclusion** : leur relation côté presse — partenaires, rivaux, indépendants ?\n\n"
        f"Marque les hypothèses comme telles, distingue ce que la DB dit factuellement vs ce que tu inférerais."
    )


@mcp.prompt()
def visibility_anomaly_report() -> str:
    """Génère un rapport sur les anomalies de visibilité du corpus —
    pics inexpliqués, entités à audit renforcé, faux PERSON résiduels.
    """
    return (
        "Audite le corpus FACE.ai pour identifier les anomalies de visibilité.\n\n"
        "**Étapes** :\n"
        "1. Lis la ressource `face://stats` pour le snapshot global.\n"
        "2. Appelle `get_corpus_stats` pour les détails techniques.\n"
        "3. Appelle `list_flagged_by_period` pour les images flagged récentes par ArcFace.\n\n"
        "**Sections du rapport** :\n"
        "- **Volumes anormaux** : entités dont le pic d'image_count récent dépasse les attentes (ex. +50 images en une journée).\n"
        "- **Ratio flagged élevé** : entités avec > 15 % d'images flagged (suggestion : audit manuel via UI `/audit`).\n"
        "- **Images hors corpus** : compte des images `source_provider='ddg'` ou `'manual'`, à valider plus strictement.\n"
        "- **Faux PERSON résiduels** : suspects = `wikidata_status='done'` + nom court inhabituel (ex. mononymes non-célèbres).\n"
        "- **Recommandations** : actions concrètes à mener depuis l'UI `/admin` ou `/audit`.\n\n"
        "Sois exhaustif mais bref : 5 anomalies max, classées par criticité décroissante."
    )


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = "stdio" if "--stdio" in sys.argv else "sse"
    mcp.run(transport=transport)
