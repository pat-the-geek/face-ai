"""Tests unitaires sur les fonctions pures (pas de DB, pas de réseau)."""
from datetime import date

import numpy as np
import pytest


# ── canonicalize_name (scraper) ─────────────────────────────────────


class TestCanonicalizeName:
    def test_first_last(self):
        from scraper import canonicalize_name

        canonical, slug = canonicalize_name("Sam Altman")
        assert canonical == "Altman, Sam"
        assert slug == "sam-altman"

    def test_three_word_name(self):
        from scraper import canonicalize_name

        canonical, slug = canonicalize_name("Jean Pierre Dupont")
        assert canonical == "Dupont, Jean Pierre"
        assert slug == "jean-pierre-dupont"

    def test_single_word(self):
        from scraper import canonicalize_name

        canonical, slug = canonicalize_name("Madonna")
        assert canonical == "Madonna"
        assert slug == "madonna"

    def test_accented(self):
        from scraper import canonicalize_name

        canonical, slug = canonicalize_name("Émilie Étienne")
        assert canonical == "Étienne, Émilie"
        # python-slugify retire les accents
        assert slug == "emilie-etienne"


# ── classification de pose et estimation des angles ─────────────────


class TestPoseClassification:
    @pytest.mark.parametrize(
        "yaw,expected",
        [
            (0.0, "front"),
            (5.0, "front"),
            (-14.9, "front"),
            (15.0, "right"),
            (30.0, "right"),
            (-15.0, "left"),
            (-45.0, "left"),
        ],
    )
    def test_classify_pose(self, yaw, expected):
        from face_processor import classify_pose

        assert classify_pose(yaw) == expected

    def test_estimate_yaw_centered_nose(self):
        # Nez exactement au milieu des yeux → yaw 0
        from face_processor import _estimate_yaw

        assert _estimate_yaw(left_eye_x=100, right_eye_x=200, nose_x=150) == 0.0

    def test_estimate_yaw_nose_to_right(self):
        from face_processor import _estimate_yaw

        # Nez décalé de 50% de l'écart à droite → yaw ~30°
        yaw = _estimate_yaw(left_eye_x=100, right_eye_x=200, nose_x=200)
        assert 25.0 < yaw < 35.0

    def test_estimate_yaw_degenerate(self):
        from face_processor import _estimate_yaw

        # Yeux confondus → 0 (évite division par zéro)
        assert _estimate_yaw(100, 100, 100) == 0.0


# ── pHash (embeddings) ──────────────────────────────────────────────


class TestEmbeddings:
    def test_distance_identical_zero(self):
        from embeddings import embedding_distance

        h = bytes(8)
        assert embedding_distance(h, h) == 0.0

    def test_distance_all_bits_different(self):
        from embeddings import embedding_distance

        a = bytes(8)
        b = bytes([0xFF] * 8)
        assert embedding_distance(a, b) == 1.0

    def test_distance_one_bit(self):
        from embeddings import embedding_distance

        a = bytes(8)
        b = bytes([0x01]) + bytes(7)
        assert embedding_distance(a, b) == pytest.approx(1 / 64)

    def test_compute_embedding_format(self, static_dir, tmp_path):
        """Une image quelconque → empreinte 8 octets."""
        import cv2

        from embeddings import compute_embedding

        # Image synthétique gradient
        img = np.tile(np.arange(256, dtype=np.uint8), (256, 1))
        path = tmp_path / "test.png"
        cv2.imwrite(str(path), img)

        emb = compute_embedding(path)
        assert isinstance(emb, bytes)
        assert len(emb) == 8

    def test_compute_embedding_missing_file(self, tmp_path):
        from embeddings import compute_embedding

        assert compute_embedding(tmp_path / "nonexistent.jpg") is None


# ── parsing dates Wikidata ──────────────────────────────────────────


class TestWikidataTimeParsing:
    def test_simple_date(self):
        from wikidata import _parse_wikidata_time

        assert _parse_wikidata_time({"time": "+1985-04-22T00:00:00Z"}) == date(
            1985, 4, 22
        )

    def test_string_input(self):
        from wikidata import _parse_wikidata_time

        assert _parse_wikidata_time("+2001-09-11T00:00:00Z") == date(2001, 9, 11)

    def test_zero_month_or_day(self):
        from wikidata import _parse_wikidata_time

        # Wikidata utilise +YYYY-00-00 pour "année seule" — non parseable
        assert _parse_wikidata_time({"time": "+1900-00-00T00:00:00Z"}) is None

    def test_invalid_input(self):
        from wikidata import _parse_wikidata_time

        assert _parse_wikidata_time(None) is None
        assert _parse_wikidata_time({}) is None
        assert _parse_wikidata_time({"time": "garbage"}) is None

    def test_bce_date(self):
        """Date BCE (-XXXX). Conserve l'année comme positive — limite acceptée."""
        from wikidata import _parse_wikidata_time

        # Les dates BCE sont rares dans notre cas (personnes contemporaines).
        # On vérifie qu'on ne crash pas, peu importe le verdict.
        try:
            result = _parse_wikidata_time({"time": "-0044-03-15T00:00:00Z"})
            # Acceptable : None ou date(44, 3, 15) selon implem
            assert result is None or isinstance(result, date)
        except Exception:
            pytest.fail("ne devrait pas lever sur date BCE")


# ── normalisation de la lettre initiale (api) ───────────────────────


class TestLetterBucketing:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Altman, Sam", "A"),
            ("Élysée, Émile", "E"),  # É → E grâce à NFKD
            ("Çağlar, Ali", "C"),  # Ç → C
            ("Über, Hans", "U"),
            ("123 Numéro", "#"),  # premier non-alpha → bucket #
            ("", "#"),
        ],
    )
    def test_bucket_letter(self, name, expected):
        from api import _bucket_letter

        assert _bucket_letter(name) == expected

    def test_letter_variants_includes_accents(self):
        from api import _letter_variants

        a_variants = _letter_variants("A")
        assert "A" in a_variants
        assert "À" in a_variants
        assert "Â" in a_variants

    def test_letter_variants_unknown_letter(self):
        from api import _letter_variants

        # Lettre sans accents enregistrés → singleton
        assert _letter_variants("Z") == ["Z"]
