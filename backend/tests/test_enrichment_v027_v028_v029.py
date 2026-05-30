"""Tests des enrichissements v027/v028/v029 (blocs A + B).

Couvre, sans réseau ni modèle vision lourd :
- photo_credit.parse_agency (A4)
- face_processor.compute_quality_score / compute_expression (A6 / B2)
- wikidata helpers + enrich_entity étendu (A1/A3/B3) avec mocks
- cooccurrence.recompute / top / behavioral_profile (A5 / B4)
- âge dérivé + /corpus/demographics (A2 + agrégats)
"""
import numpy as np


# ──────────────────────────────────────────────────────────────────────
# A4 — crédit photo / agence
# ──────────────────────────────────────────────────────────────────────
class TestPhotoCredit:
    def test_getty_from_copyright(self):
        from photo_credit import parse_agency

        assert parse_agency("© Getty Images", None, None) == "Getty Images"

    def test_reuters_from_caption(self):
        from photo_credit import parse_agency

        assert parse_agency(None, None, "Le sommet (REUTERS/Carlos Barria)") == "Reuters"

    def test_afp_word_boundary(self):
        from photo_credit import parse_agency

        assert parse_agency("Photo AFP", None, None) == "AFP"
        # pas de faux positif sur un mot contenant 'afp' (aucun ici, contrôle négatif)
        assert parse_agency("graphique maison", None, None) is None

    def test_keystone_swiss(self):
        from photo_credit import parse_agency

        assert parse_agency("KEYSTONE-ATS", None, None) == "Keystone-ATS"

    def test_wikimedia_from_url(self):
        from photo_credit import parse_agency

        url = "https://upload.wikimedia.org/wikipedia/commons/x.jpg"
        assert parse_agency(None, url, None) == "Wikimedia Commons"

    def test_unknown_returns_none(self):
        from photo_credit import parse_agency

        assert parse_agency("© Jean Dupont", "https://example.com/a.jpg", "une photo") is None

    def test_empty_returns_none(self):
        from photo_credit import parse_agency

        assert parse_agency(None, None, None) is None


# ──────────────────────────────────────────────────────────────────────
# A6 / B2 — qualité & expression depuis le mesh
# ──────────────────────────────────────────────────────────────────────
def _mesh(neutral=True):
    """Construit un mesh 468×2 normalisé minimal pour les indices utilisés."""
    m = np.zeros((468, 2), dtype=np.float32)
    # yeux : centres gauche ~0.4, droit ~0.6 (eye_dist ~0.2)
    for i in (33, 133):
        m[i] = (0.40, 0.40)
    for i in (362, 263):
        m[i] = (0.60, 0.40)
    if neutral:
        m[61] = (0.45, 0.70)  # commissures resserrées, au niveau des lèvres
        m[291] = (0.55, 0.70)
        m[13] = (0.50, 0.69)
        m[14] = (0.50, 0.71)
    else:  # sourire : bouche large + commissures relevées
        m[61] = (0.38, 0.66)
        m[291] = (0.62, 0.66)
        m[13] = (0.50, 0.71)
        m[14] = (0.50, 0.73)
    return m


class TestExpression:
    def test_neutral(self):
        from face_processor import compute_expression

        expr, score = compute_expression(_mesh(neutral=True))
        assert expr == "neutral"
        assert 0.0 <= score < 0.5

    def test_smiling(self):
        from face_processor import compute_expression

        expr, score = compute_expression(_mesh(neutral=False))
        assert expr == "smiling"
        assert score >= 0.5

    def test_degenerate_mesh(self):
        from face_processor import compute_expression

        assert compute_expression(np.zeros((10, 2), dtype=np.float32)) == (None, None)


class TestQualityScore:
    def test_frontal_large_beats_profile_small(self):
        from face_processor import compute_quality_score

        good = compute_quality_score(80, 0.0, None)
        bad = compute_quality_score(25, 60.0, None)
        assert good > bad
        assert 0.0 <= bad <= good <= 1.0

    def test_bounded(self):
        from face_processor import compute_quality_score

        assert compute_quality_score(10000, 0.0, None) <= 1.0


# ──────────────────────────────────────────────────────────────────────
# A1/A3/B3 — helpers Wikidata + enrich_entity étendu
# ──────────────────────────────────────────────────────────────────────
class TestWikidataHelpers:
    def test_pipe_join_dedups_and_orders(self):
        from wikidata import _pipe_join

        labels = {"Q1": "Démocrate", "Q2": "Sénateur", "Q3": "Démocrate"}
        assert _pipe_join(["Q1", "Q2", "Q3"], labels) == "Démocrate|Sénateur"

    def test_pipe_join_empty(self):
        from wikidata import _pipe_join

        assert _pipe_join([], {}) is None
        assert _pipe_join(["Q9"], {}) is None  # non résolu

    def test_apply_extended_enrichment(self):
        from database import Entity
        from wikidata import _apply_extended_enrichment

        e = Entity(name="X, Y", slug="x-y")
        ext_qids = {
            "gender": ["Q6581097"],
            "political_party": ["Qp1", "Qp2"],
            "positions_held": ["Qpos"],
            "awards": [],
            "notable_works": ["Qw"],
            "ethnic_group": ["Qeth"],
            "religion": ["Qrel"],
            "sexual_orientation": ["Qso"],
            "medical_condition": ["Qmc"],
        }
        labels = {
            "Q6581097": "homme",
            "Qp1": "Parti A",
            "Qp2": "Parti B",
            "Qpos": "Sénateur",
            "Qw": "Roman",
            "Qeth": "Groupe",
            "Qrel": "Catholicisme",
            "Qso": "hétérosexualité",
            "Qmc": "asthme",
        }
        _apply_extended_enrichment(e, ext_qids, labels)
        assert e.gender == "homme"
        assert e.political_party == "Parti A|Parti B"
        assert e.positions_held == "Sénateur"
        assert e.awards is None
        assert e.notable_works == "Roman"
        assert e.ethnic_group == "Groupe"
        assert e.religion == "Catholicisme"
        assert e.sexual_orientation == "hétérosexualité"
        assert e.medical_condition == "asthme"

    def test_enrich_entity_writes_extended_fields(self, db, monkeypatch):
        """enrich_entity bout-en-bout avec mocks : vérifie l'écriture v027."""
        import wikidata
        from database import Entity

        e = Entity(name="Test, Person", slug="test-person", wikidata_qid="Q42")
        db.add(e)
        db.commit()
        eid = e.id

        statements = {
            "P31": [{"value": {"content": "Q5"}}],  # être humain → pas rejeté
            "P21": [{"value": {"content": "Q6581097"}}],
            "P102": [{"value": {"content": "Qparty"}}],
            "P39": [{"value": {"content": "Qpos"}}],
            "P166": [{"value": {"content": "Qaward"}}],
            "P800": [{"value": {"content": "Qwork"}}],
            "P172": [{"value": {"content": "Qeth"}}],
            "P140": [{"value": {"content": "Qrel"}}],
            "P91": [{"value": {"content": "Qso"}}],
            "P1050": [{"value": {"content": "Qmc"}}],
        }
        labels = {
            "Q6581097": "homme",
            "Qparty": "Parti X",
            "Qpos": "Président",
            "Qaward": "Prix Nobel",
            "Qwork": "Œuvre Z",
            "Qeth": "Groupe E",
            "Qrel": "Religion R",
            "Qso": "orientation O",
            "Qmc": "condition C",
        }
        monkeypatch.setattr(wikidata, "_get_statements", lambda qid: statements)
        monkeypatch.setattr(wikidata, "_resolve_labels", lambda qids, lang="fr": labels)
        monkeypatch.setattr(wikidata, "_get_wikidata_label", lambda qid, lang="fr": "Test Person")
        monkeypatch.setattr(wikidata, "_get_wiki_summary", lambda title, lang="fr": None)

        status = wikidata.enrich_entity(eid)
        assert status == "done"

        db.expire_all()
        refreshed = db.get(Entity, eid)
        assert refreshed.gender == "homme"
        assert refreshed.political_party == "Parti X"
        assert refreshed.awards == "Prix Nobel"
        assert refreshed.notable_works == "Œuvre Z"
        assert refreshed.religion == "Religion R"
        assert refreshed.sexual_orientation == "orientation O"
        assert refreshed.medical_condition == "condition C"


# ──────────────────────────────────────────────────────────────────────
# A5 / B4 — cooccurrence + profil comportemental
# ──────────────────────────────────────────────────────────────────────
def _make_entity(db, name, slug):
    from database import Entity

    e = Entity(name=name, slug=slug, wikidata_status="done")
    db.add(e)
    db.commit()
    return e


def _link(db, article, entity):
    from database import ArticleEntity

    db.add(ArticleEntity(article_id=article.id, entity_id=entity.id))
    db.commit()


class TestCooccurrence:
    def _graph(self, db):
        from database import Article

        a = _make_entity(db, "A, A", "a")
        b = _make_entity(db, "B, B", "b")
        c = _make_entity(db, "C, C", "c")
        arts = []
        for i in range(3):
            art = Article(url=f"http://x/{i}", title=f"t{i}")
            db.add(art)
            db.commit()
            arts.append(art)
        # art0,art1 : A+B ; art2 : A+C
        for art in (arts[0], arts[1]):
            _link(db, art, a)
            _link(db, art, b)
        _link(db, arts[2], a)
        _link(db, arts[2], c)
        return a, b, c

    def test_recompute_respects_min_shared(self, db):
        from cooccurrence import recompute_cooccurrence

        a, b, c = self._graph(db)
        result = recompute_cooccurrence(min_shared=2)
        # Seule la paire A-B atteint 2 articles partagés.
        assert result["edges"] == 1

    def test_top_cooccurrences(self, db):
        from cooccurrence import recompute_cooccurrence, top_cooccurrences

        a, b, c = self._graph(db)
        recompute_cooccurrence(min_shared=2)
        partners = top_cooccurrences(a.id)
        assert len(partners) == 1
        assert partners[0]["slug"] == "b"
        assert partners[0]["shared_articles"] == 2

    def test_behavioral_profile(self, db):
        from cooccurrence import behavioral_profile, recompute_cooccurrence

        a, b, c = self._graph(db)
        recompute_cooccurrence(min_shared=2)
        prof = behavioral_profile(a.id)
        assert prof["network_degree"] == 1
        assert prof["top_partners"][0]["slug"] == "b"
        assert "interpretation_note" in prof

    def test_excludes_min_below_threshold(self, db):
        from cooccurrence import recompute_cooccurrence, top_cooccurrences

        a, b, c = self._graph(db)
        recompute_cooccurrence(min_shared=2)
        # A-C n'a qu'un article partagé → pas d'arête.
        assert all(p["slug"] != "c" for p in top_cooccurrences(a.id))


# ──────────────────────────────────────────────────────────────────────
# A2 — âge dérivé + agrégats démographiques (via API)
# ──────────────────────────────────────────────────────────────────────
class TestAgeAndDemographics:
    def test_current_age_for_living(self, db, client):
        from datetime import date

        from database import Entity

        born = date(1990, 1, 1)
        db.add(
            Entity(
                name="Vivant, Test",
                slug="vivant-test",
                wikidata_status="done",
                birth_date=born,
                gender="homme",
            )
        )
        db.commit()
        r = client.get("/entities/vivant-test")
        assert r.status_code == 200
        body = r.json()
        expected = date.today().year - 1990 - (
            (date.today().month, date.today().day) < (1, 1)
        )
        assert body["current_age"] == expected
        assert body["gender"] == "homme"

    def test_no_current_age_for_deceased(self, db, client):
        from datetime import date

        from database import Entity

        db.add(
            Entity(
                name="Defunt, Test",
                slug="defunt-test",
                wikidata_status="done",
                birth_date=date(1930, 5, 1),
                death_date=date(2000, 5, 1),
            )
        )
        db.commit()
        body = client.get("/entities/defunt-test").json()
        assert body["current_age"] is None
        assert body["age_at_death"] == 70

    def test_demographics_endpoint(self, db, client):
        from datetime import date

        from database import Entity

        db.add(
            Entity(
                name="A, A",
                slug="a",
                wikidata_status="done",
                gender="femme",
                nationalities="France|Suisse",
                birth_date=date(1980, 6, 1),
            )
        )
        db.commit()
        body = client.get("/corpus/demographics").json()
        assert body["gender_factual"].get("femme") == 1
        assert body["nationalities"].get("France") == 1
        assert "age_distribution" in body
