"""Tests de régression sur entity_merge.

Couvre en priorité le bug PK ORM corrigé en mai 2026 : quand canonical ET
duplicate ont tous deux des `ArticleEntity` pré-existants, l'ancienne
implémentation modifiait `link.entity_id` via l'ORM puis appelait
`db.delete(duplicate)`. SQLAlchemy tentait alors de "blank-out" la PK
composite (article_id, entity_id) en mémoire et levait :

    AssertionError: Dependency rule on column 'entities.id' tried to
    blank-out primary key column 'article_entities.entity_id'

Le worker s'est retrouvé avec 7 groupes QID accumulés en silence parce que
ce code path n'avait aucune couverture de test. Les tests ci-dessous
recréent exactement ce scénario.

**Pattern de test.** `merge_entities` ouvre sa propre `SessionLocal()` ;
si la session de setup reste ouverte, SQLite verrouille la DB sur write.
On utilise donc un context manager `_session()` pour setup ET vérifs, et
on ne tient jamais deux sessions en parallèle au moment des appels merge.
"""
from contextlib import contextmanager
from datetime import date, datetime


@contextmanager
def _session():
    """Session SQLAlchemy à scope explicite, fermée à la sortie du bloc."""
    from database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_entity(db, name, slug, **kw):
    from database import Entity

    e = Entity(name=name, slug=slug, first_seen=datetime(2024, 1, 1), **kw)
    db.add(e)
    db.flush()
    return e


def _make_article(db, url, title="t"):
    from database import Article

    a = Article(url=url, title=title, published_at=date(2024, 6, 1))
    db.add(a)
    db.flush()
    return a


def _link(db, article, entity):
    from database import ArticleEntity

    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    db.flush()


def _make_image(db, entity, url, **kw):
    from database import Image

    img = Image(entity_id=entity.id, source_url=url, scrape_status="downloaded", **kw)
    db.add(img)
    db.flush()
    return img


class TestPKBlankOutRegression:
    """Cas qui faisait planter le worker (bug PK ORM)."""

    def test_canonical_has_articles_duplicate_has_disjoint_articles(self):
        """Canonical a déjà des links, duplicate a des links sur d'autres
        articles → tous les links du duplicate sont déplacés (move), aucun
        collapse. C'est le cas qui crashait avec blank-out PK."""
        from entity_merge import merge_entities

        with _session() as s:
            canonical = _make_entity(s, "Zelensky, Volodymyr", "zelensky", wikidata_qid="Q3874799")
            duplicate = _make_entity(s, "Zelenskyy, Volodymyr", "zelenskyy", wikidata_qid="Q3874799")
            a1 = _make_article(s, "https://ex.com/1")
            a2 = _make_article(s, "https://ex.com/2")
            a3 = _make_article(s, "https://ex.com/3")
            _link(s, a1, canonical)
            _link(s, a2, canonical)
            _link(s, a3, duplicate)
            s.commit()
            canon_id = canonical.id
            dup_id = duplicate.id
            a_ids = {a1.id, a2.id, a3.id}

        result = merge_entities(canon_id, dup_id)
        assert result["status"] == "merged"
        assert result["article_links_moved"] == 1
        assert result["article_links_collapsed"] == 0

        with _session() as s:
            from database import ArticleEntity, Entity

            assert s.get(Entity, dup_id) is None
            links = s.query(ArticleEntity).filter_by(entity_id=canon_id).all()
            assert {l.article_id for l in links} == a_ids

    def test_canonical_and_duplicate_share_article_collapse(self):
        """Article lié aux deux entités → on supprime le lien duplicate
        (collapse, sinon viol UNIQUE sur PK composite)."""
        from entity_merge import merge_entities

        with _session() as s:
            canonical = _make_entity(s, "Trump, Donald", "donald-trump")
            duplicate = _make_entity(s, "Trump", "trump")
            a_shared = _make_article(s, "https://ex.com/shared")
            a_dup_only = _make_article(s, "https://ex.com/dup-only")
            _link(s, a_shared, canonical)
            _link(s, a_shared, duplicate)  # le link à collapse
            _link(s, a_dup_only, duplicate)
            s.commit()
            canon_id = canonical.id
            dup_id = duplicate.id
            shared_id = a_shared.id
            dup_only_id = a_dup_only.id

        result = merge_entities(canon_id, dup_id)
        assert result["status"] == "merged"
        assert result["article_links_collapsed"] == 1
        assert result["article_links_moved"] == 1

        with _session() as s:
            from database import ArticleEntity

            links = s.query(ArticleEntity).filter_by(entity_id=canon_id).all()
            assert {l.article_id for l in links} == {shared_id, dup_only_id}
            assert (
                s.query(ArticleEntity).filter_by(entity_id=dup_id).count() == 0
            )

    def test_zelensky_3_way_merge(self):
        """Régression directe du cas observé en prod : 3 entités même QID
        (Zelensky, Zelenskyy, Vladimir Zelensky), canonical avec ~10
        article_links. Le worker plantait sur ce scénario. On valide
        qu'après merge, les 3 sont consolidées."""
        from entity_merge import auto_merge_by_qid

        with _session() as s:
            # wikidata_score=1.0 requis par le garde-fou auto-merge (cf.
            # TestAutoMergeSafeguards). Les 3 variantes Zelensky ont bien
            # un score 1.0 en pratique (labels Wikidata exacts).
            z1 = _make_entity(
                s, "Zelensky, Volodymyr", "z1",
                wikidata_qid="Q3874799", wikidata_score=1.0,
            )
            z2 = _make_entity(
                s, "Zelenskyy, Volodymyr", "z2",
                wikidata_qid="Q3874799", wikidata_score=1.0,
            )
            z3 = _make_entity(
                s, "Zelensky, Vladimir", "z3",
                wikidata_qid="Q3874799", wikidata_score=1.0,
            )

            for i in range(10):
                art = _make_article(s, f"https://ex.com/canon-{i}")
                _link(s, art, z1)
            a_z2 = _make_article(s, "https://ex.com/z2")
            _link(s, a_z2, z2)
            a_z3 = _make_article(s, "https://ex.com/z3")
            _link(s, a_z3, z3)
            # z1 a aussi le plus d'images → sera élu canonical
            for i in range(5):
                _make_image(s, z1, f"https://ex.com/img-{i}")
            s.commit()
            z1_id, z2_id, z3_id = z1.id, z2.id, z3.id

        # recompute pour que image_count soit à jour avant find_qid_duplicate_groups
        from entity_stats import recompute_counts

        for eid in (z1_id, z2_id, z3_id):
            recompute_counts(eid)

        summary = auto_merge_by_qid()
        assert summary["groups"] == 1
        assert summary["merged"] == 2

        with _session() as s:
            from database import ArticleEntity, Entity

            assert s.get(Entity, z2_id) is None
            assert s.get(Entity, z3_id) is None
            links = s.query(ArticleEntity).filter_by(entity_id=z1_id).count()
            assert links == 12  # 10 + 1 + 1


class TestMergeMechanics:
    """Mécanique générale de fusion."""

    def test_images_moved(self):
        from entity_merge import merge_entities

        with _session() as s:
            canonical = _make_entity(s, "A, X", "a-x")
            duplicate = _make_entity(s, "A, Y", "a-y")
            _make_image(s, duplicate, "https://ex.com/i1")
            _make_image(s, duplicate, "https://ex.com/i2")
            s.commit()
            canon_id, dup_id = canonical.id, duplicate.id

        result = merge_entities(canon_id, dup_id)
        assert result["images_moved"] == 2

        with _session() as s:
            from database import Image

            assert s.query(Image).filter_by(entity_id=canon_id).count() == 2

    def test_aliases_propagated(self):
        """Le nom du duplicate + ses aliases deviennent aliases du canonical."""
        from entity_merge import merge_entities
        from database import EntityAlias

        with _session() as s:
            canonical = _make_entity(s, "Macron, Emmanuel", "macron")
            duplicate = _make_entity(s, "Macron", "macron-short")
            s.add(EntityAlias(entity_id=duplicate.id, alias="E. Macron", source="scraper"))
            s.commit()
            canon_id, dup_id = canonical.id, duplicate.id

        merge_entities(canon_id, dup_id)

        with _session() as s:
            from database import Entity

            canon = s.get(Entity, canon_id)
            alias_strs = {a.alias for a in canon.aliases}
            assert "Macron" in alias_strs  # nom du duplicate
            assert "E. Macron" in alias_strs  # alias hérité

    def test_aliases_deduplicated(self):
        """Un alias déjà présent dans canonical n'est pas ré-inséré (sinon
        UniqueConstraint(entity_id, alias) violé)."""
        from entity_merge import merge_entities
        from database import EntityAlias

        with _session() as s:
            canonical = _make_entity(s, "Macron, Emmanuel", "macron")
            duplicate = _make_entity(s, "Macron", "macron-short")
            s.add(EntityAlias(entity_id=canonical.id, alias="Macron", source="other"))
            s.commit()
            canon_id, dup_id = canonical.id, duplicate.id

        result = merge_entities(canon_id, dup_id)
        assert result["status"] == "merged"

        with _session() as s:
            from database import Entity

            canon = s.get(Entity, canon_id)
            macron_aliases = [a for a in canon.aliases if a.alias == "Macron"]
            assert len(macron_aliases) == 1

    def test_centroid_reset(self):
        """Après fusion, le centroïde de canonical est invalidé pour forcer
        un recalcul par le worker (les nouvelles images du duplicate doivent
        être intégrées dans la moyenne L2)."""
        import numpy as np
        from entity_merge import merge_entities

        with _session() as s:
            canonical = _make_entity(s, "A, X", "a-x")
            canonical.identity_centroid = np.ones(512, dtype=np.float32).tobytes()
            canonical.identity_count = 7
            duplicate = _make_entity(s, "A, Y", "a-y")
            s.commit()
            canon_id, dup_id = canonical.id, duplicate.id

        merge_entities(canon_id, dup_id)

        with _session() as s:
            from database import Entity

            canon = s.get(Entity, canon_id)
            assert canon.identity_centroid is None
            assert canon.identity_count == 0

    def test_counts_recomputed(self):
        """Les compteurs dénormalisés du canonical reflètent les images et
        articles déplacés (recompute_counts est appelé en fin de merge)."""
        from entity_merge import merge_entities

        with _session() as s:
            canonical = _make_entity(s, "A, X", "a-x")
            duplicate = _make_entity(s, "A, Y", "a-y")
            a1 = _make_article(s, "https://ex.com/1")
            _link(s, a1, duplicate)
            _make_image(s, duplicate, "https://ex.com/img")
            s.commit()
            canon_id, dup_id = canonical.id, duplicate.id

        merge_entities(canon_id, dup_id)

        with _session() as s:
            from database import Entity

            canon = s.get(Entity, canon_id)
            assert canon.image_count == 1
            assert canon.article_count == 1


class TestMergeGuards:
    def test_same_id_noop(self):
        from entity_merge import merge_entities

        with _session() as s:
            e = _make_entity(s, "X, Y", "x-y")
            s.commit()
            eid = e.id
        assert merge_entities(eid, eid) == {"status": "noop_same_entity"}

    def test_missing_canonical(self):
        from entity_merge import merge_entities

        with _session() as s:
            e = _make_entity(s, "X, Y", "x-y")
            s.commit()
            eid = e.id
        r = merge_entities(99999, eid)
        assert r["status"] == "missing_entity"

    def test_missing_duplicate(self):
        from entity_merge import merge_entities

        with _session() as s:
            e = _make_entity(s, "X, Y", "x-y")
            s.commit()
            eid = e.id
        r = merge_entities(eid, 99999)
        assert r["status"] == "missing_entity"


class TestFindQidDuplicateGroups:
    def test_returns_canonical_first_by_image_count(self):
        """Au sein d'un groupe QID, l'entité avec le plus d'images est canonical."""
        from entity_merge import find_qid_duplicate_groups
        from entity_stats import recompute_counts

        with _session() as s:
            small = _make_entity(s, "X, A", "x-a", wikidata_qid="Q1")
            big = _make_entity(s, "X, B", "x-b", wikidata_qid="Q1")
            for i in range(3):
                _make_image(s, big, f"https://ex.com/{i}")
            s.commit()
            small_id, big_id = small.id, big.id

        recompute_counts(big_id)
        recompute_counts(small_id)

        groups = find_qid_duplicate_groups()
        assert len(groups) == 1
        canonical_id, dup_ids = groups[0]
        assert canonical_id == big_id
        assert dup_ids == [small_id]

    def test_ignores_null_qid(self):
        """Deux entités sans QID ne sont pas un groupe (on ne fusionne pas
        à l'aveugle, seulement sur preuve Wikidata)."""
        from entity_merge import find_qid_duplicate_groups

        with _session() as s:
            _make_entity(s, "X, A", "x-a", wikidata_qid=None)
            _make_entity(s, "X, B", "x-b", wikidata_qid=None)
            s.commit()
        assert find_qid_duplicate_groups() == []

    def test_idempotent_after_merge(self):
        """Après auto_merge, plus aucun groupe ne ressort — sinon le worker
        boucle indéfiniment sur les mêmes paires."""
        from entity_merge import auto_merge_by_qid, find_qid_duplicate_groups

        with _session() as s:
            _make_entity(
                s, "X, A", "x-a", wikidata_qid="Q1", wikidata_score=1.0
            )
            _make_entity(
                s, "X, B", "x-b", wikidata_qid="Q1", wikidata_score=1.0
            )
            s.commit()

        auto_merge_by_qid()
        assert find_qid_duplicate_groups() == []


class TestAutoMergeSafeguards:
    """Garde-fous post-incident 2026-05-11. Une réindexation a écrasé les
    QIDs de Musk/Zuckerberg/McCartney par celui d'Altman (Q7407093), et
    `auto_merge_by_qid` les a tous fusionnés dans Altman avant que personne
    ne s'en rende compte. Ces tests verrouillent les deux invariants qui
    auraient bloqué l'incident.
    """

    def test_blocks_when_growth_ratio_exceeded(self):
        """Si fusionner ferait grossir le canonical de plus de 50%, refus.

        Le canonical est élu par tri image_count desc, donc on inverse les
        comptes (10 vs 8) pour que canon=10 grandisse à 18 → ratio 1.8 > 1.5.
        Reproduit exactement la mécanique de l'incident Altman 2026-05-11 :
        30 + 26 (Musk) = 56, ratio 1.87.
        """
        from entity_merge import auto_merge_by_qid

        with _session() as s:
            canon = _make_entity(
                s, "Altman, Sam", "altman", wikidata_qid="Q7", wikidata_score=1.0
            )
            dup = _make_entity(
                s, "Musk, Elon", "musk", wikidata_qid="Q7", wikidata_score=1.0
            )
            for i in range(10):
                _make_image(s, canon, f"https://ex.com/c-{i}")
            for i in range(8):
                _make_image(s, dup, f"https://ex.com/d-{i}")
            s.commit()
            canon_id, dup_id = canon.id, dup.id

        from entity_stats import recompute_counts

        recompute_counts(canon_id)
        recompute_counts(dup_id)

        summary = auto_merge_by_qid()
        assert summary["merged"] == 0
        assert summary["blocked"] == 1
        assert "growth_ratio" in summary["blocks"][0]["reason"]

        with _session() as s:
            from database import Entity

            assert s.get(Entity, dup_id) is not None  # toujours là

    def test_blocks_when_wikidata_score_below_threshold(self):
        """Score 0.7 = label inexact → trop d'incertitude pour fusion auto."""
        from entity_merge import auto_merge_by_qid

        with _session() as s:
            canon = _make_entity(
                s, "X, A", "x-a", wikidata_qid="Q1", wikidata_score=1.0
            )
            dup = _make_entity(
                s, "X, B", "x-b", wikidata_qid="Q1", wikidata_score=0.7
            )
            s.commit()
            dup_id = dup.id

        summary = auto_merge_by_qid()
        assert summary["merged"] == 0
        assert summary["blocked"] == 1
        assert "wikidata_score" in summary["blocks"][0]["reason"]

        with _session() as s:
            from database import Entity

            assert s.get(Entity, dup_id) is not None

    def test_allows_when_both_safe(self):
        """Le cas Vance, J.D. / Vance, JD : QIDs identiques avec score 1.0
        de part et d'autre et tailles comparables doit fusionner sans blocage.
        """
        from entity_merge import auto_merge_by_qid

        with _session() as s:
            canon = _make_entity(
                s, "Vance, J.D.", "vance-jd",
                wikidata_qid="Q28935729", wikidata_score=1.0,
            )
            dup = _make_entity(
                s, "Vance, JD", "vance-jd-2",
                wikidata_qid="Q28935729", wikidata_score=1.0,
            )
            _make_image(s, canon, "https://ex.com/c1")
            s.commit()

        summary = auto_merge_by_qid()
        assert summary["merged"] == 1
        assert summary["blocked"] == 0

    def test_find_blocked_lists_conflict(self):
        """`find_blocked_merge_conflicts` rend les blocages visibles pour
        l'admin (endpoint `/admin/merge-conflicts`)."""
        from entity_merge import find_blocked_merge_conflicts

        with _session() as s:
            canon = _make_entity(
                s, "Altman, Sam", "altman",
                wikidata_qid="Q7407093", wikidata_score=1.0,
            )
            dup = _make_entity(
                s, "Musk, Elon", "musk",
                wikidata_qid="Q7407093", wikidata_score=1.0,
            )
            for i in range(10):
                _make_image(s, canon, f"https://ex.com/c-{i}")
            for i in range(8):
                _make_image(s, dup, f"https://ex.com/d-{i}")
            s.commit()
            canon_id, dup_id = canon.id, dup.id

        from entity_stats import recompute_counts

        recompute_counts(canon_id)
        recompute_counts(dup_id)

        blocked = find_blocked_merge_conflicts()
        assert len(blocked) == 1
        assert blocked[0]["canonical"]["slug"] == "altman"
        assert blocked[0]["duplicate"]["slug"] == "musk"
        assert "growth_ratio" in blocked[0]["reason"]
