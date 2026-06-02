"""Bibliographie & export Markdown par entité (v031).

Deux usages :
- `entity_articles(entity_id, ...)` : liste paginée des articles mentionnant
  l'entité (titre, date, source, url, nb d'images de CETTE entité dans
  l'article). Sert la modale « 📚 Bibliographie » de la fiche.
- `entity_markdown(entity_id)` : **dossier complet** d'une entité rendu en
  Markdown — portrait (URL **publique**), biographie factuelle, puis la liste
  des articles avec citations. Pensé pour être copié/partagé hors de l'app.

**Périmètre de l'export (posture §1.5 / CLAUDE.md).** Comme un export quitte
potentiellement le LAN, on applique la même règle que le digest Discord :
- on n'inclut **que des champs factuels publics** ;
- on **exclut les attributs sensibles RGPD art. 9** (religion, ethnic_group,
  sexual_orientation, medical_condition) ;
- le portrait est une **URL publique** : `wiki_thumbnail_url` (Wikimedia) en
  priorité, sinon le `source_url` original (URL presse publique) de la
  meilleure image du corpus. Jamais un chemin `/static/` (LAN, non public).

Module volontairement léger (`database` + `sqlalchemy` seulement → importable
par l'API sans tirer la vision), comme `presence.py`.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from database import (
    Article,
    ArticleEntity,
    Entity,
    FaceAnalysis,
    Image,
    SessionLocal,
)


def _split_pipe(value: str | None) -> list[str]:
    return [v.strip() for v in value.split("|") if v.strip()] if value else []


def _natural_name(name: str) -> str:
    """`"Last, First"` → `"First Last"` pour un rendu lisible en titre."""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            return f"{parts[1]} {parts[0]}"
    return name


def public_portrait_url(db, entity: Entity) -> str | None:
    """URL **publique** d'un portrait, ou None.

    Priorité Wikimedia (`wiki_thumbnail_url`, stable et public). Repli : le
    `source_url` original de la meilleure image du corpus (URL presse
    publique d'où l'image a été extraite) — on NE renvoie jamais un chemin
    `/static/` aligné, qui n'est servi que sur le LAN.
    """
    if entity.wiki_thumbnail_url:
        return entity.wiki_thumbnail_url
    row = db.execute(
        select(Image.source_url)
        .join(FaceAnalysis, FaceAnalysis.image_id == Image.id, isouter=True)
        .where(
            Image.entity_id == entity.id,
            Image.is_duplicate.is_(False),
            Image.association_status != "flagged",
            Image.source_url.is_not(None),
        )
        .order_by(func.coalesce(FaceAnalysis.quality_score, 0).desc(), Image.id)
        .limit(1)
    ).first()
    return row[0] if row else None


def entity_articles(entity_id: int, limit: int = 50, offset: int = 0) -> dict:
    """Liste paginée des articles mentionnant l'entité, récents d'abord.

    `images` = nombre d'images de **cette** entité dans l'article (pas le total
    de l'article), ce qui est l'info pertinente pour une bibliographie.
    """
    db = SessionLocal()
    try:
        total = (
            db.scalar(
                select(func.count())
                .select_from(ArticleEntity)
                .where(ArticleEntity.entity_id == entity_id)
            )
            or 0
        )
        rows = db.execute(
            select(Article)
            .join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .where(ArticleEntity.entity_id == entity_id)
            .order_by(
                Article.published_at.desc().nulls_last(),
                Article.scraped_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars().all()

        ids = [a.id for a in rows]
        img_counts: dict[int, int] = {}
        if ids:
            img_counts = dict(
                db.execute(
                    select(Image.article_id, func.count(Image.id))
                    .where(
                        Image.article_id.in_(ids),
                        Image.entity_id == entity_id,
                    )
                    .group_by(Image.article_id)
                ).all()
            )

        articles = [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source_domain": a.source_domain,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "images": img_counts.get(a.id, 0),
            }
            for a in rows
        ]
        return {"total": total, "limit": limit, "offset": offset, "articles": articles}
    finally:
        db.close()


def _bio_lines(entity: Entity) -> list[str]:
    """Repères factuels publics — **sans** attributs RGPD art. 9."""
    lines: list[str] = []

    def add(label: str, value):
        if isinstance(value, list):
            value = ", ".join(value)
        if value:
            lines.append(f"- **{label}** : {value}")

    if entity.birth_date:
        bd = entity.birth_date.isoformat()
        add("Naissance", f"{bd}{f' à {entity.birth_place}' if entity.birth_place else ''}")
    if entity.death_date:
        dd = entity.death_date.isoformat()
        add("Décès", f"{dd}{f' à {entity.death_place}' if entity.death_place else ''}")
    add("Nationalité(s)", _split_pipe(entity.nationalities))
    add("Genre", entity.gender)
    add("Profession(s)", _split_pipe(entity.occupations))
    add("Employeur", entity.employer)
    add("Parti politique", _split_pipe(entity.political_party))
    add("Fonctions", _split_pipe(entity.positions_held))
    add("Distinctions", _split_pipe(entity.awards))
    add("Œuvres notables", _split_pipe(entity.notable_works))
    return lines


def entity_markdown(entity_id: int, articles_limit: int = 200) -> str | None:
    """Dossier Markdown complet de l'entité (portrait + bio + bibliographie).

    Retourne None si l'entité n'existe pas. N'inclut **aucun** champ sensible
    art. 9 (cf. docstring module).
    """
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return None

        title = _natural_name(entity.name)
        portrait = public_portrait_url(db, entity)
        parts: list[str] = [f"# {title}", ""]

        if portrait:
            parts += [f"![{title}]({portrait})", ""]
        if entity.wiki_summary:
            parts += [f"> {entity.wiki_summary}", ""]

        bio = _bio_lines(entity)
        if bio:
            parts += ["## Repères", "", *bio, ""]

        links = []
        if entity.wiki_url:
            links.append(f"[Wikipédia]({entity.wiki_url})")
        if entity.wikidata_qid:
            links.append(
                f"[Wikidata](https://www.wikidata.org/wiki/{entity.wikidata_qid})"
            )
        if links:
            parts += [" · ".join(links), ""]
    finally:
        db.close()

    # Bibliographie (sa propre session via entity_articles)
    bib = entity_articles(entity_id, limit=articles_limit, offset=0)
    parts += [f"## Bibliographie ({bib['total']} article(s))", ""]
    if not bib["articles"]:
        parts += ["_Aucun article dans le corpus._", ""]
    for a in bib["articles"]:
        d = a["published_at"] or "date inconnue"
        src = f" · {a['source_domain']}" if a["source_domain"] else ""
        imgs = f" · {a['images']} img" if a["images"] else ""
        title_txt = a["title"] or a["url"]
        parts.append(f"- **{d}** — [{title_txt}]({a['url']}){src}{imgs}")
    if bib["total"] > len(bib["articles"]):
        parts.append(
            f"- _… et {bib['total'] - len(bib['articles'])} autre(s) "
            f"(tronqué à {articles_limit})_"
        )
    parts += [
        "",
        "---",
        f"*Exporté de FACE.ai le {date.today().isoformat()} — "
        f"corpus : {entity.image_count or 0} image(s), {bib['total']} article(s).*",
    ]
    return "\n".join(parts)
