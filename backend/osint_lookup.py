"""Couche de lecture OSINT (v030), partagée par l'API et le serveur MCP.

Volontairement légère (`database` + `sqlalchemy` + `osint_common` seulement →
importable par l'API et le MCP sans tirer la vision), sur le modèle de
`presence.py`. Toutes les fonctions lisent les colonnes/tables alimentées par
les scripts d'ingestion (open data, personnes publiques) et renvoient des dicts
JSON-sérialisables avec une forme d'erreur cohérente `{"error": ...}`.

Aucune écriture, aucun appel réseau : pur read sur le corpus local.
"""
from __future__ import annotations

import json

from sqlalchemy import func, select

from database import Entity, EntityGdeltCoverage, SessionLocal
from osint_common import country_code_to_flag


def _load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _get_person(db, slug: str) -> Entity | None:
    entity = db.scalar(select(Entity).where(Entity.slug == slug))
    if entity is None or entity.wikidata_status == "not_person":
        return None
    return entity


# ── P1A — OpenSanctions ──────────────────────────────────────────────────────

def get_entity_sanctions(slug: str) -> dict:
    db = SessionLocal()
    try:
        e = _get_person(db, slug)
        if e is None:
            return {"error": f"entité '{slug}' introuvable", "slug": slug}
        detail = _load_json(e.sanctions_detail, {})
        return {
            "slug": slug,
            "name": e.name,
            "sanctions_status": e.sanctions_status or "unknown",
            "datasets": detail.get("datasets", []),
            "topics": detail.get("topics", []),
            "match_score": detail.get("score") or detail.get("name_score"),
            # Niveau de corroboration anti-homonymie (garde-fou) : 'birthdate' /
            # 'country' = match confirmé par la naissance/le pays ; 'unverified'
            # = match par nom non corroboré (à auditer). Cf. ingest_opensanctions.
            "verification": detail.get("verification"),
            "last_checked": detail.get("last_checked")
            or (e.sanctions_synced_at.isoformat() if e.sanctions_synced_at else None),
        }
    finally:
        db.close()


# ── P1C — Parlement suisse ───────────────────────────────────────────────────

def get_entity_parliament_profile(slug: str) -> dict:
    db = SessionLocal()
    try:
        e = _get_person(db, slug)
        if e is None:
            return {"error": f"entité '{slug}' introuvable", "slug": slug}
        data = _load_json(e.parliament_ch_data, {})
        return {
            "slug": slug,
            "name": e.name,
            "is_swiss_parliament_member": bool(e.is_swiss_parliament_member),
            "parliament_ch_id": e.parliament_ch_id,
            "party": data.get("party"),
            "canton": data.get("canton"),
            "council": data.get("council"),
            "active": data.get("active"),
            "role": data.get("role"),
            "commissions": data.get("commissions", []),
        }
    finally:
        db.close()


# ── P2A — GDELT media coverage ───────────────────────────────────────────────

def get_entity_media_coverage(slug: str, days: int = 30) -> dict:
    db = SessionLocal()
    try:
        e = _get_person(db, slug)
        if e is None:
            return {"error": f"entité '{slug}' introuvable", "slug": slug}
        snap = db.scalar(
            select(EntityGdeltCoverage)
            .where(EntityGdeltCoverage.entity_id == e.id)
            .order_by(EntityGdeltCoverage.fetched_at.desc())
        )
        if snap is None:
            return {
                "slug": slug,
                "name": e.name,
                "available": False,
                "note": "aucune couverture GDELT ingérée pour cette entité",
            }
        return {
            "slug": slug,
            "name": e.name,
            "available": True,
            "period_start": snap.period_start.isoformat() if snap.period_start else None,
            "period_end": snap.period_end.isoformat() if snap.period_end else None,
            "requested_days": days,
            "article_count": snap.article_count,
            "avg_tone": snap.avg_tone,
            "top_countries": _load_json(snap.top_countries, []),
            "fetched_at": snap.fetched_at.isoformat() if snap.fetched_at else None,
        }
    finally:
        db.close()


# ── Transversal — filtre pays ────────────────────────────────────────────────

def list_entities_by_country(country_code: str, limit: int = 50) -> dict:
    db = SessionLocal()
    try:
        code = (country_code or "").upper()
        rows = db.execute(
            select(Entity)
            .where(
                Entity.country_code == code,
                (Entity.wikidata_status.is_(None))
                | (Entity.wikidata_status != "not_person"),
            )
            .order_by(Entity.name.asc())
            .limit(limit)
        ).scalars().all()
        return {
            "country_code": code,
            "country_flag": country_code_to_flag(code),
            "count": len(rows),
            "results": [
                {
                    "slug": e.slug,
                    "name": e.name,
                    "country_code": e.country_code,
                    "country_name": e.country_name,
                    "country_flag": country_code_to_flag(e.country_code),
                    "image_count": e.image_count or 0,
                }
                for e in rows
            ],
        }
    finally:
        db.close()


def get_entity_osint(slug: str) -> dict:
    """Agrégat OSINT d'une entité pour l'UI (1 requête → 1 panneau).

    N'inclut que les sections **renseignées** (les vides sont omises → le
    frontend ne rend que ce qui existe). Marque `sensitive=True` les sections
    RGPD art. 9/10 (sanctions/PEP, ICIJ) pour le regroupement UI « ⚠ ».
    """
    db = SessionLocal()
    try:
        e = _get_person(db, slug)
        if e is None:
            return {"error": f"entité '{slug}' introuvable", "slug": slug}
        country = (
            {
                "code": e.country_code,
                "name": e.country_name,
                "flag": country_code_to_flag(e.country_code),
            }
            if e.country_code
            else None
        )
    finally:
        db.close()

    out: dict = {"slug": slug, "country": country}

    san = get_entity_sanctions(slug)
    if san.get("sanctions_status") in ("sanctioned", "pep"):
        out["sanctions"] = san  # sensible (art. 9/10)

    parl = get_entity_parliament_profile(slug)
    if parl.get("is_swiss_parliament_member"):
        out["parliament"] = parl

    mc = get_entity_media_coverage(slug)
    if mc.get("available"):
        out["media_coverage"] = mc

    return out


def get_country_stats() -> list[dict]:
    """Liste des pays représentés (≥ 1 entité), triée par effectif décroissant."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                Entity.country_code,
                func.max(Entity.country_name),
                func.count(),
            )
            .where(
                Entity.country_code.is_not(None),
                (Entity.wikidata_status.is_(None))
                | (Entity.wikidata_status != "not_person"),
            )
            .group_by(Entity.country_code)
            .order_by(func.count().desc())
        ).all()
        return [
            {
                "code": code,
                "name": name or code,
                "flag": country_code_to_flag(code),
                "count": count,
            }
            for code, name, count in rows
        ]
    finally:
        db.close()
