"""Notifications Discord — veille proactive (v030).

Chaque alerte joint une **fiche de veille typographiée** (cf. `synthesis_card`)
envoyée en octets multipart (`static/` est en LAN, pas d'URL d'embed
accessible à Discord). La fiche contient : le portrait annoté des **landmarks
faciaux**, une **synthèse rédigée par l'IA locale Ollama** (repli déterministe
si injoignable), des chapitres de **repères** factuels + **corpus & médias**,
et le **heatmap d'activité presse** quand il est pertinent.

Quatre scénarios :
- **A — pic de visibilité** : flambée d'articles vs la période précédente.
- **B — photo inhabituelle** : image fraîchement ingérée flaggée par l'audit
  ArcFace (distance élevée au centroïde d'identité).
- **C — nouvelle personne** : entité PERSON récemment créée disposant déjà
  d'un portrait.
- **D — palier corpus** : franchissement d'un bloc de N personnalités gérées.

Dédup : marqueur dans `worker_events` (rotation 7 j → les fenêtres de
détection restent < 7 j). Le palier (rare, doit survivre > 7 j) utilise un
fichier d'état persistant sous `data/`.

**Périmètre** : la synthèse n'inclut **que des données factuelles publiques**
+ signaux corpus — **jamais** les attributs sensibles RGPD art. 9 (la notif
sort hors LAN, hors du cadre d'atténuation §1.5/v027).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

import config
from database import (
    Article,
    ArticleEntity,
    Entity,
    FaceAnalysis,
    Image,
    SessionLocal,
    WorkerEvent,
)
from synthesis_card import render_synthesis_card

log = logging.getLogger("notifications")

NOT_PERSON = "not_person"
_USERNAME = "FACE.ai · veille"
_STATE_PATH = config.DB_PATH.parent / "notify_state.json"

ACCENT_NEW = (70, 150, 95)
ACCENT_FLAG = (200, 45, 45)
ACCENT_SPIKE = (220, 120, 30)
ACCENT_MILESTONE = (190, 150, 45)
ACCENT_TEST = (120, 120, 120)


# ── Webhook ─────────────────────────────────────────────────────────────


def send_discord(
    content: str, *, image_bytes: bytes | None = None, filename: str = "face_ai.jpg"
) -> bool:
    """Poste un message Discord, image jointe en multipart. Ne lève jamais."""
    url = config.DISCORD_WEBHOOK_URL
    if not url:
        return False
    payload = {"username": _USERNAME, "content": content[:1900]}
    try:
        if image_bytes:
            resp = requests.post(
                url,
                data={"payload_json": json.dumps(payload)},
                files={"file": (filename, image_bytes, "image/jpeg")},
                timeout=20,
            )
        else:
            resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception:
        log.exception("webhook Discord en échec")
        return False


def render_landmark_jpg(aligned_path, landmarks_blob) -> bytes | None:
    """Portrait aligné + mesh dessiné (repli si la fiche ne se rend pas)."""
    if not aligned_path:
        return None
    try:
        import cv2
        import numpy as np

        image = cv2.imread(str(aligned_path))
        if image is None:
            return None
        if landmarks_blob:
            pts = np.frombuffer(landmarks_blob, dtype=np.float32).reshape(-1, 2)
            h, w = image.shape[:2]
            for x, y in pts:
                cv2.circle(image, (int(x * w), int(y * h)), 1, (90, 220, 255), -1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return buf.tobytes() if ok else None
    except Exception:
        log.exception("rendu landmarks échec (%s)", aligned_path)
        return None


# ── Dédup via worker_events ─────────────────────────────────────────────


def _already_sent(db, key: str) -> bool:
    return bool(
        db.scalar(
            select(func.count()).select_from(WorkerEvent).where(WorkerEvent.kind == key)
        )
    )


def _mark_sent(db, key: str, summary: dict | None = None) -> None:
    db.add(
        WorkerEvent(
            kind=key,
            loop_name="notify",
            summary=json.dumps(summary, ensure_ascii=False) if summary else None,
        )
    )
    db.commit()


# ── État persistant (palier) ────────────────────────────────────────────


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        log.exception("écriture état notify échec (%s)", _STATE_PATH)


# ── Helpers données ─────────────────────────────────────────────────────


def _person_filter():
    return (Entity.wikidata_status.is_(None)) | (Entity.wikidata_status != NOT_PERSON)


def _first(piped: str | None) -> str | None:
    if not piped:
        return None
    head = piped.split("|")[0].strip()
    return head or None


def _years(d, ref: date) -> int:
    return ref.year - d.year - ((ref.month, ref.day) < (d.month, d.day))


def _best_portrait(db, entity_id: int):
    return (
        db.execute(
            select(Image)
            .options(joinedload(Image.face_analysis))
            .join(FaceAnalysis, FaceAnalysis.image_id == Image.id, isouter=True)
            .where(
                Image.entity_id == entity_id,
                Image.aligned_path.is_not(None),
                Image.is_duplicate.is_(False),
                Image.association_status != "flagged",
            )
            .order_by(FaceAnalysis.quality_score.desc().nulls_last())
            .limit(1)
        )
        .unique()
        .scalars()
        .first()
    )


def _heatmap_grid(db, entity_id: int | None = None, weeks: int = 53) -> dict:
    """Grille semaines × 7 jours du nombre d'articles/jour (12 mois).

    `entity_id=None` → activité presse de tout le corpus. Cellule -1 = hors
    fenêtre, sinon nombre d'articles distincts ce jour-là.
    """
    end = date.today()
    start = end - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())  # remonter au lundi

    q = select(Article.published_at, func.count(func.distinct(Article.id)))
    if entity_id is not None:
        q = q.join(ArticleEntity, ArticleEntity.article_id == Article.id).where(
            ArticleEntity.entity_id == entity_id
        )
    q = q.where(
        Article.published_at.is_not(None),
        Article.published_at >= start,
        Article.published_at <= end,
    ).group_by(Article.published_at)
    counts = {d: int(n) for d, n in db.execute(q).all()}

    ncols = ((end - start).days // 7) + 1
    grid = [[-1] * 7 for _ in range(ncols)]
    total = active = mx = 0
    d = start
    while d <= end:
        col = (d - start).days // 7
        c = counts.get(d, 0)
        grid[col][d.weekday()] = c
        if c > 0:
            active += 1
            total += c
        mx = max(mx, c)
        d += timedelta(days=1)
    return {
        "grid": grid,
        "max": mx,
        "total": total,
        "active_days": active,
        "label": (
            "Activité presse · 12 mois"
            if entity_id is not None
            else "Activité presse du corpus · 12 mois"
        ),
    }


def _entity_card_data(db, entity):
    """(subtitle, reperes, corpus, fact_lines) — données factuelles publiques."""
    subtitle = " · ".join(
        filter(None, [_first(entity.occupations), _first(entity.nationalities)])
    )
    reperes: list[str] = []
    if entity.birth_date:
        try:
            label = entity.birth_date.isoformat()
            age = _years(entity.birth_date, date.today())
            if entity.death_date is None and 0 <= age <= 130:
                label += f" ({age} ans)"
        except Exception:
            label = str(entity.birth_date)
        if entity.birth_place:
            label += f" — {entity.birth_place}"
        reperes.append(f"Naissance : {label}")
    if entity.death_date:
        reperes.append(f"Décès : {entity.death_date.isoformat()}")
    if _first(entity.political_party):
        reperes.append(f"Parti : {_first(entity.political_party)}")
    if _first(entity.positions_held):
        reperes.append(f"Fonction : {_first(entity.positions_held)}")
    if entity.employer:
        reperes.append(f"Employeur : {entity.employer}")
    if _first(entity.awards):
        reperes.append(f"Distinction : {_first(entity.awards)}")

    corpus: list[str] = []
    line = f"Présence : {entity.image_count or 0} images · {entity.article_count or 0} articles"
    if entity.diversity_score:
        line += f" · diversité {entity.diversity_score:.2f}"
    corpus.append(line)
    try:
        from cooccurrence import behavioral_profile

        prof = behavioral_profile(entity.id)
    except Exception:
        prof = None
    if prof:
        srcs = prof.get("dominant_sources") or []
        if srcs:
            corpus.append(
                "Sources : " + " · ".join(f"{s['domain']} ({s['images']})" for s in srcs[:3])
            )
        parts = prof.get("top_partners") or []
        if parts:
            corpus.append("Réseau : " + " · ".join(p["name"] for p in parts[:3]))
        vol, peak = prof.get("visibility_volatility"), prof.get("peak_month")
        bits = []
        if peak:
            bits.append(f"pic {peak}")
        if vol is not None:
            bits.append(
                "présence en pics"
                if vol >= 0.6
                else "présence régulière"
                if vol <= 0.3
                else f"volatilité {vol:.2f}"
            )
        if bits:
            corpus.append("Visibilité : " + " · ".join(bits))

    fact_lines = list(reperes) + list(corpus)
    if entity.wiki_summary:
        fact_lines.append("Résumé Wikipédia : " + entity.wiki_summary.strip()[:400])
    return subtitle, reperes, corpus, fact_lines


def _llm_synthesis(title: str, fact_lines: list[str]) -> str | None:
    """Synthèse de veille rédigée par Ollama à partir des seuls faits fournis."""
    if not config.OLLAMA_SYNTHESIS_ENABLED or not fact_lines:
        return None
    try:
        from llm import chat
    except Exception:
        return None
    sheet = "\n".join(f"- {line}" for line in fact_lines)
    system = (
        "Tu es analyste de veille médiatique. Rédige en français une synthèse "
        "factuelle et fluide (3 à 4 phrases) à partir UNIQUEMENT des informations "
        "fournies. N'invente rien, n'ajoute aucune donnée absente. Ton neutre et "
        "professionnel, sans listes ni titres."
    )
    prompt = (
        f"Sujet : {title}\n\nInformations disponibles :\n{sheet}\n\nSynthèse de veille :"
    )
    return chat(prompt, system=system, max_tokens=320)


def _send_entity_card(
    db,
    entity,
    *,
    badge: str,
    accent: tuple[int, int, int],
    portrait_img,
    header: str,
    extra_corpus: list[str] | None = None,
    force_heatmap: bool = False,
) -> bool:
    subtitle, reperes, corpus, fact_lines = _entity_card_data(db, entity)
    if extra_corpus:
        corpus = list(extra_corpus) + corpus
        fact_lines = list(extra_corpus) + fact_lines
    synthesis = _llm_synthesis(entity.name, fact_lines) or (
        entity.wiki_summary.strip()[:300] if entity.wiki_summary else None
    )

    heat = _heatmap_grid(db, entity.id)
    include_heat = force_heatmap or (heat["total"] >= 6 and heat["active_days"] >= 3)

    fa = portrait_img.face_analysis if portrait_img else None
    card = render_synthesis_card(
        name=entity.name,
        subtitle=subtitle,
        badge=badge,
        accent_rgb=accent,
        portrait_path=portrait_img.aligned_path if portrait_img else None,
        landmarks_blob=fa.landmarks_blob if fa else None,
        synthesis_text=synthesis,
        reperes=reperes,
        corpus=corpus,
        heatmap=heat if include_heat else None,
        footer_right=f"FACE.ai · {entity.slug}",
    )
    if card:
        return send_discord(header, image_bytes=card, filename=f"veille_{entity.slug}.jpg")
    # Repli : portrait landmarks nu + faits en texte.
    jpg = render_landmark_jpg(
        portrait_img.aligned_path if portrait_img else None,
        fa.landmarks_blob if fa else None,
    )
    return send_discord(
        header + "\n" + "\n".join(fact_lines),
        image_bytes=jpg,
        filename=f"veille_{entity.slug}.jpg",
    )


# ── Scénario B : photo inhabituelle ─────────────────────────────────────


def _notify_flagged(db) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=config.NOTIFY_FLAGGED_LOOKBACK_HOURS)
    rows = (
        db.execute(
            select(Image)
            .options(
                joinedload(Image.face_analysis),
                joinedload(Image.article),
                joinedload(Image.entity),
            )
            .where(Image.association_status == "flagged", Image.scraped_at >= cutoff)
            .order_by(Image.identity_match_score.desc().nulls_last())
            .limit(config.NOTIFY_FLAGGED_MAX_PER_CYCLE * 3)
        )
        .unique()
        .scalars()
        .all()
    )
    sent = 0
    for img in rows:
        if sent >= config.NOTIFY_FLAGGED_MAX_PER_CYCLE:
            break
        key = f"notif_flag:{img.id}"
        if _already_sent(db, key):
            continue
        entity = img.entity
        if entity is None or entity.wikidata_status == NOT_PERSON:
            continue
        score = img.identity_match_score or 0.0
        fc = img.face_analysis.face_count if img.face_analysis else None
        multi = bool(fc and fc > 1)
        header = (
            f"🔎 **Photo inhabituelle — {entity.name}** · audit ArcFace distance "
            f"{score:.2f}" + (f", {fc} visages détectés" if multi else "") + " — fiche jointe, à vérifier dans /audit."
        )
        extra = [
            "Image signalée : distance "
            f"{score:.2f} au centroïde"
            + (" · composition multi-personnes probable" if multi else "")
        ]
        if img.caption:
            extra.append(f"Légende : {img.caption.strip()[:160]}")
        if send := _send_entity_card(
            db,
            entity,
            badge="Photo inhabituelle",
            accent=ACCENT_FLAG,
            portrait_img=img,
            header=header,
            extra_corpus=extra,
        ):
            _mark_sent(db, key, {"image_id": img.id, "score": score})
            sent += 1
    return sent


# ── Scénario A : pic de visibilité ──────────────────────────────────────


def _window_counts(db, start: date, end: date) -> dict[int, int]:
    rows = db.execute(
        select(
            ArticleEntity.entity_id,
            func.count(func.distinct(ArticleEntity.article_id)),
        )
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(Entity, Entity.id == ArticleEntity.entity_id)
        .where(
            Article.published_at.is_not(None),
            Article.published_at >= start,
            Article.published_at <= end,
            _person_filter(),
        )
        .group_by(ArticleEntity.entity_id)
    ).all()
    return {eid: n for eid, n in rows}


def _notify_spikes(db) -> int:
    w = config.NOTIFY_SPIKE_WINDOW_DAYS
    today = date.today()
    cur_start = today - timedelta(days=w - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=w - 1)

    cur = _window_counts(db, cur_start, today)
    prev = _window_counts(db, prev_start, prev_end)

    candidates = []
    for eid, n in cur.items():
        if n < config.NOTIFY_SPIKE_MIN_ARTICLES:
            continue
        p = prev.get(eid, 0)
        if n >= config.NOTIFY_SPIKE_RATIO * max(p, 1):
            candidates.append((eid, n, p))
    candidates.sort(key=lambda c: c[1], reverse=True)

    sent = 0
    for eid, n, p in candidates:
        if sent >= config.NOTIFY_SPIKE_MAX_PER_CYCLE:
            break
        key = f"notif_spike:{eid}:{today.isoformat()}"
        if _already_sent(db, key):
            continue
        entity = db.get(Entity, eid)
        if entity is None:
            continue
        ratio = "∞" if p == 0 else f"×{n / p:.1f}"
        header = (
            f"📈 **Pic de visibilité — {entity.name}** · {n} articles en {w} j "
            f"(vs {p} avant, {ratio}) — fiche jointe."
        )
        extra = [f"Pic : {n} articles sur {w} jours (période précédente : {p}, {ratio})"]
        if _send_entity_card(
            db,
            entity,
            badge="Pic de visibilité",
            accent=ACCENT_SPIKE,
            portrait_img=_best_portrait(db, eid),
            header=header,
            extra_corpus=extra,
            force_heatmap=True,
        ):
            _mark_sent(db, key, {"entity_id": eid, "articles": n, "prev": p})
            sent += 1
    return sent


# ── Scénario C : nouvelle personne ──────────────────────────────────────


def _notify_new_persons(db) -> int:
    cutoff = datetime.utcnow() - timedelta(
        hours=config.NOTIFY_NEW_PERSON_LOOKBACK_HOURS
    )
    rows = (
        db.execute(
            select(Entity)
            .where(
                Entity.first_seen.is_not(None),
                Entity.first_seen >= cutoff,
                _person_filter(),
                Entity.images.any(
                    Image.aligned_path.is_not(None)
                    & Image.is_duplicate.is_(False)
                    & (Image.association_status != "flagged")
                ),
            )
            .order_by(Entity.first_seen.desc())
            .limit(config.NOTIFY_NEW_PERSON_MAX_PER_CYCLE * 3)
        )
        .scalars()
        .all()
    )
    sent = 0
    for entity in rows:
        if sent >= config.NOTIFY_NEW_PERSON_MAX_PER_CYCLE:
            break
        key = f"notif_newperson:{entity.id}"
        if _already_sent(db, key):
            continue
        header = (
            f"🆕 **Nouvelle personnalité — {entity.name}** ajoutée au corpus FACE.ai "
            "— fiche de synthèse jointe."
        )
        if _send_entity_card(
            db,
            entity,
            badge="Nouvelle personnalité",
            accent=ACCENT_NEW,
            portrait_img=_best_portrait(db, entity.id),
            header=header,
        ):
            _mark_sent(db, key, {"entity_id": entity.id})
            sent += 1
    return sent


# ── Scénario D : palier corpus ──────────────────────────────────────────


def _notify_milestones(db) -> int:
    block = config.NOTIFY_MILESTONE_BLOCK
    count = (
        db.scalar(
            select(func.count()).select_from(Entity).where(_person_filter())
        )
        or 0
    )
    current = (count // block) * block
    if current < block:
        return 0

    state = _load_state()
    last = state.get("last_milestone")
    if last is None:
        # Init silencieuse : on ne notifie pas rétroactivement le palier courant.
        state["last_milestone"] = current
        _save_state(state)
        return 0
    if current <= last:
        return 0

    total_images = db.scalar(select(func.count()).select_from(Image)) or 0
    total_articles = db.scalar(select(func.count()).select_from(Article)) or 0
    top = db.execute(
        select(Entity.name, Entity.article_count)
        .where(_person_filter())
        .order_by(Entity.article_count.desc())
        .limit(3)
    ).all()

    reperes = [
        f"Personnalités gérées : {count}",
        f"Images : {total_images}",
        f"Articles : {total_articles}",
    ]
    corpus = ["Plus actifs : " + " · ".join(f"{n} ({a or 0} art)" for n, a in top)]
    synthesis = _llm_synthesis(
        f"corpus FACE.ai ({count} personnalités)", reperes + corpus
    ) or (
        f"Le corpus FACE.ai vient de franchir {current} personnalités suivies, "
        f"pour {total_images} portraits issus de {total_articles} articles."
    )

    recent = (
        db.execute(
            select(Entity)
            .where(_person_filter(), Entity.first_seen.is_not(None))
            .order_by(Entity.first_seen.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    pimg = _best_portrait(db, recent.id) if recent else None
    fa = pimg.face_analysis if pimg else None
    heat = _heatmap_grid(db, None)

    card = render_synthesis_card(
        name=f"{current} personnalités",
        subtitle="Corpus FACE.ai · veille interne",
        badge="Palier franchi",
        accent_rgb=ACCENT_MILESTONE,
        portrait_path=pimg.aligned_path if pimg else None,
        landmarks_blob=fa.landmarks_blob if fa else None,
        synthesis_text=synthesis,
        reperes=reperes,
        corpus=corpus,
        heatmap=heat if heat["total"] > 0 else None,
        footer_right=f"palier · bloc de {block}",
    )
    header = (
        f"🎯 **Cap des {current} personnalités atteint** — FACE.ai suit désormais "
        f"{count} entités PERSON (palier précédent : {last})."
    )
    if send_discord(header, image_bytes=card, filename="palier.jpg"):
        state["last_milestone"] = current
        _save_state(state)
        return 1
    return 0


# ── Digest hebdomadaire (v031) ──────────────────────────────────────────


_TREND_SYMBOL = {"up": "▲", "down": "▼", "flat": "·", "new": "✦"}


def _digest_text() -> str | None:
    """Corps Markdown du digest hebdo, dérivé du share of voice.

    Données **exclusivement corpus** (mentions presse) — aucun attribut
    sensible art. 9. Retourne None s'il n'y a aucune mention sur la fenêtre."""
    from presence import compute_share_of_voice

    sov = compute_share_of_voice(
        window_days=config.NOTIFY_DIGEST_WINDOW_DAYS, limit=config.NOTIFY_DIGEST_TOP
    )
    entities = sov.get("entities") or []
    if not entities or sov.get("total_mentions", 0) == 0:
        return None

    lines = [
        f"📊 **Veille hebdo FACE.ai** — {config.NOTIFY_DIGEST_WINDOW_DAYS} derniers jours",
        f"_{sov['total_mentions']} mentions presse · {sov['from']} → {sov['to']}_",
        "",
    ]

    # Synthèse éditoriale optionnelle (Ollama, à partir des seuls chiffres).
    movers = [
        f"{e['name']} : {e['share_pct']}% ({e['articles']} art., {e['trend']})"
        for e in entities[:5]
    ]
    synthesis = _llm_synthesis(
        "Veille presse hebdomadaire du corpus", movers
    )
    if synthesis:
        lines += [synthesis, ""]

    lines.append("**Top présence :**")
    for i, e in enumerate(entities, 1):
        sym = _TREND_SYMBOL.get(e["trend"], "·")
        tag = "  🆕" if e["trend"] == "new" else ""
        lines.append(
            f"{i:>2}. {sym} {e['name']} — {e['share_pct']}% ({e['articles']} art.){tag}"
        )

    newcomers = [e["name"] for e in entities if e["trend"] == "new"]
    if newcomers:
        lines += ["", "🆕 Nouveaux entrants : " + " · ".join(newcomers[:6])]

    return "\n".join(lines)


def send_weekly_digest() -> bool:
    """Envoie le digest hebdo (texte, sans image). Ne lève jamais."""
    text = _digest_text()
    if text is None:
        return send_discord("📊 Veille hebdo FACE.ai — aucune mention cette semaine.")
    return send_discord(text)


def _iso_week_key() -> str:
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def maybe_send_digest(*, force: bool = False) -> dict:
    """Émet le digest si on est dans la fenêtre jour/heure configurée et qu'il
    n'a pas déjà été envoyé cette semaine ISO. `force=True` court-circuite la
    planification (endpoint de test). Dédup persistante via notify_state.json
    (clé `last_digest_week`) — survit à la rotation 7 j de worker_events."""
    if not (config.NOTIFY_DIGEST_ENABLED or force):
        return {"skipped": "disabled"}

    week = _iso_week_key()
    if not force:
        now = datetime.utcnow()
        if now.weekday() != config.NOTIFY_DIGEST_DAY or now.hour != config.NOTIFY_DIGEST_HOUR:
            return {"skipped": "not_scheduled"}
        state = _load_state()
        if state.get("last_digest_week") == week:
            return {"skipped": "already_sent", "week": week}

    sent = send_weekly_digest()
    if sent and not force:
        state = _load_state()
        state["last_digest_week"] = week
        _save_state(state)
    return {"sent": sent, "week": week, "forced": force}


# ── Cycle worker + test manuel ──────────────────────────────────────────


def run_notify_cycle() -> dict:
    """Un passage des quatre détecteurs. No-op si les notifications sont OFF."""
    if not config.NOTIFY_ENABLED:
        return {"skipped": "disabled"}
    db = SessionLocal()
    try:
        return {
            "milestone": _notify_milestones(db),
            "new_persons": _notify_new_persons(db),
            "flagged": _notify_flagged(db),
            "spikes": _notify_spikes(db),
        }
    finally:
        db.close()


def send_test_notification() -> bool:
    """Envoie une fiche de test (entité la plus active) pour vérifier le
    webhook, l'upload multipart, la synthèse Ollama et la mise en page."""
    db = SessionLocal()
    try:
        entity = (
            db.execute(
                select(Entity)
                .where(_person_filter())
                .order_by(Entity.article_count.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if entity is None:
            return send_discord("✅ Test FACE.ai — webhook OK (corpus vide).")
        return _send_entity_card(
            db,
            entity,
            badge="Test · veille",
            accent=ACCENT_TEST,
            portrait_img=_best_portrait(db, entity.id),
            header="✅ **Test FACE.ai** — notifications Discord opérationnelles (fiche de synthèse jointe).",
            force_heatmap=True,
        )
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Notifications Discord FACE.ai")
    parser.add_argument("--test", action="store_true", help="Envoie une fiche de test")
    parser.add_argument("--run", action="store_true", help="Lance un cycle de détection")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.test:
        print("envoyé" if send_test_notification() else "échec")
    elif args.run:
        print(run_notify_cycle())
    else:
        parser.print_help()
