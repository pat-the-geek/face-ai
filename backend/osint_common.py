"""Helpers partagés par les scripts d'ingestion OSINT (v030).

PÉRIMÈTRE (décision 2026-06-05) : ces utilitaires servent UNIQUEMENT à croiser
des données OPEN SOURCE avec des PERSONNES PUBLIQUES déjà présentes dans le
corpus FACE.ai. Le point d'entrée `iter_corpus_persons` ne renvoie jamais que
des entités existantes (jamais de découverte d'inconnus). Cf. CLAUDE.md.

Contenu :
- `country_code_to_flag` : ISO 3166-1 alpha-2 → emoji drapeau (sans lib).
- `normalize_person_name` : "Last, First" (forme canonique FACE.ai) → "First
  Last" pour le matching avec des sources qui stockent l'ordre naturel.
- `best_fuzzy_match` / `name_matches` : fuzzy matching rapidfuzz tolérant aux
  accents et à l'ordre des tokens.
- `get_logger` : logger fichier `logs/ingest_{source}_{date}.log` + console.
- `make_session` : session requests avec User-Agent OSINT et retries.
- `iter_corpus_persons` : itère les entités PERSON du corpus (helper DB lazy).

Les helpers purs (drapeau, normalisation, fuzzy) n'importent PAS `database` —
ils restent testables sans toucher la base (cf. mémoire test-isolation-prod-db).
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date
from pathlib import Path

# rapidfuzz est optionnel à l'import (les helpers purs non-fuzzy restent
# utilisables même si la lib n'est pas installée dans l'environnement courant).
try:
    from rapidfuzz import fuzz

    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    fuzz = None
    _HAS_RAPIDFUZZ = False


# ── Drapeaux pays ───────────────────────────────────────────────────────────

def country_code_to_flag(code: str | None) -> str:
    """Convertit un code ISO 3166-1 alpha-2 en emoji drapeau.

    Construit à partir des Regional Indicator Symbols Unicode — pas de lib.
    Repli sur le drapeau blanc 🏳️ si le code est absent ou mal formé.
    """
    if not code or len(code) != 2 or not code.isalpha():
        return "🏳️"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


# ── Normalisation & matching de noms ────────────────────────────────────────

def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_person_name(name: str | None) -> str:
    """Forme canonique FACE.ai "Last, First" → ordre naturel "First Last".

    Les sources externes (OpenSanctions, GLEIF, parlament.ch…) stockent le nom
    en ordre naturel. On retourne une chaîne sans accents, espaces normalisés,
    pour comparaison robuste. Si le nom ne contient pas de virgule, on le rend
    tel quel (déjà en ordre naturel).
    """
    if not name:
        return ""
    raw = name.strip()
    if "," in raw:
        last, _, first = raw.partition(",")
        raw = f"{first.strip()} {last.strip()}"
    cleaned = _strip_accents(raw).lower()
    return " ".join(cleaned.split())


def best_fuzzy_match(
    query: str, candidates: list[str], threshold: int = 90
) -> tuple[int | None, float]:
    """Renvoie (index du meilleur candidat, score) si ≥ threshold, sinon
    (None, meilleur score observé).

    Utilise `token_sort_ratio` (insensible à l'ordre des tokens) sur des noms
    déjà normalisés via `normalize_person_name`. Repli sur égalité stricte si
    rapidfuzz est absent.
    """
    if not query or not candidates:
        return None, 0.0
    q = normalize_person_name(query)
    best_idx, best_score = None, 0.0
    for idx, cand in enumerate(candidates):
        c = normalize_person_name(cand)
        if _HAS_RAPIDFUZZ:
            score = fuzz.token_sort_ratio(q, c)
        else:  # pragma: no cover
            score = 100.0 if q == c else 0.0
        if score > best_score:
            best_idx, best_score = idx, score
    if best_score >= threshold:
        return best_idx, best_score
    return None, best_score


def name_matches(a: str, b: str, threshold: int = 90) -> bool:
    """True si deux noms désignent vraisemblablement la même personne."""
    idx, _ = best_fuzzy_match(a, [b], threshold=threshold)
    return idx is not None


# ── Logging ─────────────────────────────────────────────────────────────────

def get_logger(source: str) -> logging.Logger:
    """Logger dédié à un script d'ingestion.

    Écrit dans `OSINT_LOG_DIR/ingest_{source}_{YYYY-MM-DD}.log` (créé au besoin)
    ET sur la console. Idempotent : ne ré-ajoute pas de handlers si déjà câblé.
    """
    from config import OSINT_LOG_DIR  # import lazy : pas de dépendance au top

    logger = logging.getLogger(f"osint.{source}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_dir = Path(OSINT_LOG_DIR)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            log_dir / f"ingest_{source}_{date.today().isoformat()}.log",
            encoding="utf-8",
        )
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(fh)
    except OSError:  # pragma: no cover - disque en lecture seule
        pass
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(ch)
    return logger


# ── HTTP ────────────────────────────────────────────────────────────────────

def make_session():
    """Session requests avec User-Agent OSINT et retries doux sur 429/5xx."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    from config import OSINT_USER_AGENT

    session = requests.Session()
    session.headers["User-Agent"] = OSINT_USER_AGENT
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ── Accès corpus (lazy DB) ──────────────────────────────────────────────────

def iter_corpus_persons(db, *, require_qid=False, only_missing=None):
    """Itère les entités PERSON exploitables du corpus.

    Exclut les tombstones `wikidata_status='not_person'`. Filtres optionnels :
    - `require_qid` : seulement celles ayant un `wikidata_qid` (utile pour les
      sources adossées à Wikidata : Commons, Wayback).
    - `only_missing` : nom d'une colonne ; ne renvoie que les entités dont
      cette colonne est NULL (rejouabilité / idempotence des backfills).

    `db` est une Session SQLAlchemy fournie par l'appelant (import DB lazy).
    """
    from sqlalchemy import select

    from database import Entity

    stmt = select(Entity).where(
        (Entity.wikidata_status.is_(None))
        | (Entity.wikidata_status != "not_person")
    )
    if require_qid:
        stmt = stmt.where(Entity.wikidata_qid.is_not(None))
    if only_missing:
        col = getattr(Entity, only_missing)
        stmt = stmt.where(col.is_(None))
    yield from db.scalars(stmt)


# ── Ingestion d'image externe (open data) ───────────────────────────────────

def _guess_extension(url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(url).path.lower()
    for cand in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(cand):
            return ".jpg" if cand == ".jpeg" else cand
    return ".jpg"


def ingest_external_image(
    entity_id: int,
    url: str,
    *,
    source_provider: str,
    caption: str | None = None,
    copyright_text: str | None = None,
    capture_year: int | None = None,
    session=None,
) -> dict:
    """Télécharge et ingère une image OPEN DATA comme image d'une entité.

    Générique (Wikimedia Commons, Wayback, parlament.ch…) : pose
    `source_provider` (≠ 'wudd' → audit /audit renforcé, pas de cross-check
    texte↔image), `article_id=None`. Le pipeline standard (face_processor +
    identity_audit) qualifie ensuite, et §5.4 purge silencieusement si aucun
    visage exploitable. Idempotent sur `source_url`.

    Retourne {status, image_id?, http_status?, file_size?}.
    """
    from sqlalchemy import select

    from config import STATIC_DIR
    from database import Entity, Image, SessionLocal
    from entity_stats import recompute_counts

    http = session or make_session()
    db = SessionLocal()
    try:
        entity = db.get(Entity, entity_id)
        if entity is None:
            return {"status": "missing_entity"}

        existing = db.scalar(select(Image).where(Image.source_url == url))
        if existing is not None:
            return {"status": "already_ingested", "image_id": existing.id}

        try:
            r = http.get(url, timeout=20)
        except Exception as exc:  # noqa: BLE001 - réseau best-effort
            return {"status": "download_failed", "error": str(exc)}
        if r.status_code != 200 or not r.content:
            return {"status": "download_failed", "http_status": r.status_code}

        img = Image(
            entity_id=entity_id,
            article_id=None,
            source_url=url,
            caption=caption or None,
            copyright_text=copyright_text or None,
            scrape_status="downloaded",
            analysis_status="pending",
            association_status="auto",
            source_provider=source_provider,
            capture_year=capture_year,
            http_status=r.status_code,
        )
        db.add(img)
        db.flush()

        dest = STATIC_DIR / "originals" / f"{img.id}{_guess_extension(url)}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        img.local_path = str(dest)
        db.commit()
        image_id = img.id
        size = len(r.content)
    finally:
        db.close()

    recompute_counts(entity_id)
    return {
        "status": "ok",
        "image_id": image_id,
        "http_status": 200,
        "file_size": size,
    }
