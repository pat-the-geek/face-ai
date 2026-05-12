"""Tests du workflow P9 — correction des associations flagged."""
from datetime import datetime


def _seed_two_with_flagged(db, static_dir):
    """Sam Altman + Macron, avec 1 image flagged sur Altman.

    Crée un fichier réel dans `static_dir` pour pouvoir vérifier la suppression.
    """
    from database import Entity, FaceAnalysis, Image

    altman = Entity(
        name="Altman, Sam",
        slug="sam-altman",
        first_seen=datetime(2024, 1, 1),
    )
    macron = Entity(
        name="Macron, Emmanuel",
        slug="emmanuel-macron",
        first_seen=datetime(2024, 1, 1),
    )
    db.add_all([altman, macron])
    db.flush()

    # Fichier "image" suspect
    fake = static_dir / "originals" / "suspect.jpg"
    fake.write_bytes(b"fake jpeg")
    aligned = static_dir / "aligned" / "suspect.jpg"
    aligned.write_bytes(b"fake")

    img = Image(
        entity_id=altman.id,
        source_url="https://example.com/suspect.jpg",
        local_path=str(fake),
        aligned_path=str(aligned),
        caption="Photo suspecte attribuée à Altman",
        scrape_status="downloaded",
        analysis_status="done",
        association_status="flagged",
        identity_match_score=0.72,
    )
    db.add(img)
    db.flush()
    db.add(FaceAnalysis(image_id=img.id, face_detected=True, pose="front"))

    # Image valide pour Altman (gardée comme témoin)
    img_ok = Image(
        entity_id=altman.id,
        source_url="https://example.com/ok.jpg",
        local_path="/tmp/inexistant-ok.jpg",
        scrape_status="downloaded",
        analysis_status="done",
        association_status="confirmed",
        identity_match_score=0.05,
    )
    db.add(img_ok)
    db.commit()
    return altman, macron, img, img_ok


class TestFlaggedList:
    def test_empty(self, client):
        body = client.get("/flagged").json()
        assert body["total"] == 0
        assert body["flagged"] == []

    def test_lists_flagged_only(self, client, db, static_dir):
        _seed_two_with_flagged(db, static_dir)
        body = client.get("/flagged").json()
        assert body["total"] == 1
        assert body["flagged"][0]["entity_slug"] == "sam-altman"
        assert body["flagged"][0]["identity_match_score"] == 0.72

    def test_ordered_by_distance_desc(self, client, db, static_dir):
        """Les plus suspectes en haut."""
        from database import Entity, Image

        e = Entity(name="X, Y", slug="xy")
        db.add(e)
        db.flush()
        db.add_all(
            [
                Image(
                    entity_id=e.id,
                    source_url="a",
                    local_path="/tmp/a",
                    association_status="flagged",
                    identity_match_score=0.60,
                ),
                Image(
                    entity_id=e.id,
                    source_url="b",
                    local_path="/tmp/b",
                    association_status="flagged",
                    identity_match_score=0.85,
                ),
            ]
        )
        db.commit()
        body = client.get("/flagged").json()
        scores = [img["identity_match_score"] for img in body["flagged"]]
        assert scores == sorted(scores, reverse=True)


class TestDeleteImage:
    def test_delete_existing(self, client, db, static_dir):
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        r = client.delete(f"/images/{img.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["files_removed"] == 2  # original + aligned
        assert body["entity_slug"] == "sam-altman"

    def test_delete_removes_files(self, client, db, static_dir):
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        fake = static_dir / "originals" / "suspect.jpg"
        aligned = static_dir / "aligned" / "suspect.jpg"
        assert fake.exists()
        client.delete(f"/images/{img.id}")
        assert not fake.exists()
        assert not aligned.exists()

    def test_delete_cascades_face_analysis(self, client, db, static_dir):
        from database import FaceAnalysis

        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        assert db.query(FaceAnalysis).filter_by(image_id=img.id).count() == 1
        client.delete(f"/images/{img.id}")
        assert db.query(FaceAnalysis).filter_by(image_id=img.id).count() == 0

    def test_delete_recomputes_counts(self, client, db, static_dir):
        from database import Entity

        altman, _, img, _ = _seed_two_with_flagged(db, static_dir)
        # Compteurs avant : doivent refléter les 2 images
        from entity_stats import recompute_counts

        recompute_counts(altman.id)
        db.refresh(altman)
        before = altman.image_count

        client.delete(f"/images/{img.id}")
        db.refresh(altman)
        assert altman.image_count == before - 1

    def test_delete_unknown_404(self, client):
        assert client.delete("/images/99999").status_code == 404


class TestReassignImage:
    def test_reassign_changes_entity(self, client, db, static_dir):
        from database import Image

        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        r = client.patch(
            f"/images/{img.id}",
            json={"target_slug": "emmanuel-macron"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["from_slug"] == "sam-altman"
        assert body["to_slug"] == "emmanuel-macron"
        assert body["new_status"] == "manual"

        db.refresh(img)
        assert img.entity.slug == "emmanuel-macron"
        assert img.association_status == "manual"

    def test_reassign_resets_centroids(self, client, db, static_dir):
        from database import Entity

        altman, macron, img, _ = _seed_two_with_flagged(db, static_dir)
        # Simule un centroïde précédemment calculé
        altman.identity_centroid = b"\x00" * 2048
        altman.identity_count = 5
        macron.identity_centroid = b"\xff" * 2048
        macron.identity_count = 2
        db.commit()

        client.patch(
            f"/images/{img.id}",
            json={"target_slug": "emmanuel-macron"},
        )
        db.refresh(altman)
        db.refresh(macron)
        # Les 2 centroïdes doivent être reset → le worker les recalculera
        assert altman.identity_centroid is None
        assert macron.identity_centroid is None
        assert altman.identity_count == 0
        assert macron.identity_count == 0

    def test_reassign_unknown_image_404(self, client):
        r = client.patch("/images/99999", json={"target_slug": "sam-altman"})
        assert r.status_code == 404

    def test_reassign_unknown_target_404(self, client, db, static_dir):
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        r = client.patch(
            f"/images/{img.id}",
            json={"target_slug": "personne-inconnue"},
        )
        assert r.status_code == 404

    def test_reassign_to_same_entity_noop(self, client, db, static_dir):
        """Réassocier à l'entité actuelle ne casse rien."""
        from database import Image

        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        original_status = img.association_status
        r = client.patch(
            f"/images/{img.id}",
            json={"target_slug": "sam-altman"},
        )
        assert r.status_code == 200
        db.refresh(img)
        # Le statut ne change PAS dans ce cas (pas de bascule manual)
        assert img.association_status == original_status


class TestManualNotReAudited:
    """Les images en `manual` ne sont pas écrasées par le prochain audit."""

    def test_audit_skips_manual(self, db, static_dir):
        import numpy as np

        from database import Entity, Image
        from identity_audit import audit_entity

        e = Entity(name="Test, Sujet", slug="test-sujet")
        e.identity_centroid = np.zeros(512, dtype=np.float32).tobytes()
        e.identity_count = 3
        db.add(e)
        db.flush()

        # Vecteur très éloigné du centroïde → serait normalement flagged
        far_vector = np.ones(512, dtype=np.float32)
        far_vector /= np.linalg.norm(far_vector)

        img = Image(
            entity_id=e.id,
            source_url="x",
            local_path="/tmp/x",
            identity_embedding=far_vector.tobytes(),
            association_status="manual",
            identity_match_score=None,
        )
        db.add(img)
        db.commit()

        audit_entity(e.id)
        db.refresh(img)
        # Le statut `manual` est préservé malgré la distance énorme
        assert img.association_status == "manual"


class TestFlagImageEndpoint:
    """POST /images/{id}/flag — signalement manuel par l'utilisateur."""

    def test_flag_basic(self, client, db, static_dir):
        """Une image en `auto`/`confirmed` bascule en `human_flagged`."""
        _, _, _, img_ok = _seed_two_with_flagged(db, static_dir)
        assert img_ok.association_status == "confirmed"

        r = client.post(f"/images/{img_ok.id}/flag")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == img_ok.id
        assert body["flagged_by"] == "human"

        db.refresh(img_ok)
        assert img_ok.association_status == "human_flagged"

    def test_flag_appears_in_flagged_list(self, client, db, static_dir):
        """L'image signalée manuellement doit apparaître dans `/flagged`
        avec `flagged_by='human'` pour distinguer l'origine côté UI."""
        _, _, img_arcface, img_ok = _seed_two_with_flagged(db, static_dir)
        client.post(f"/images/{img_ok.id}/flag")

        body = client.get("/flagged").json()
        # Les deux origines doivent coexister
        by_id = {h["id"]: h for h in body["flagged"]}
        assert img_arcface.id in by_id
        assert img_ok.id in by_id
        assert by_id[img_arcface.id]["flagged_by"] == "arcface"
        assert by_id[img_ok.id]["flagged_by"] == "human"
        assert body["total"] == 2

    def test_flag_arcface_image_preserves_origin(self, client, db, static_dir):
        """Re-signaler à la main une image déjà ArcFace-flagged ne doit
        PAS écraser l'origine ArcFace — sinon on perd la trace que c'est
        l'algorithme qui a détecté l'anomalie."""
        _, _, img_arcface, _ = _seed_two_with_flagged(db, static_dir)
        assert img_arcface.association_status == "flagged"

        r = client.post(f"/images/{img_arcface.id}/flag")
        assert r.status_code == 200
        assert r.json()["flagged_by"] == "arcface"  # origine préservée

        db.refresh(img_arcface)
        assert img_arcface.association_status == "flagged"  # statut inchangé

    def test_flag_idempotent_on_human_flagged(self, client, db, static_dir):
        """Re-signaler une image déjà human_flagged → noop, 200."""
        _, _, _, img_ok = _seed_two_with_flagged(db, static_dir)
        client.post(f"/images/{img_ok.id}/flag")
        r = client.post(f"/images/{img_ok.id}/flag")
        assert r.status_code == 200
        assert r.json()["flagged_by"] == "human"

    def test_flag_unknown_404(self, client):
        assert client.post("/images/99999/flag").status_code == 404


class TestHumanFlaggedNotReAudited:
    """Une décision humaine prime sur l'algo dans les deux sens —
    `human_flagged` ne doit pas être ré-évaluée par `audit_entity` au
    prochain cycle (sinon une image avec score sous le seuil serait
    rebasculée en `confirmed`, contre la volonté de l'utilisateur)."""

    def test_audit_skips_human_flagged(self, db):
        import numpy as np

        from database import Entity, Image
        from identity_audit import audit_entity

        e = Entity(name="Test, Sujet", slug="test-sujet-2")
        # Centroïde quelconque
        e.identity_centroid = np.zeros(512, dtype=np.float32).tobytes()
        e.identity_count = 3
        db.add(e)
        db.flush()

        # Vecteur très PROCHE du centroïde (distance ~0) → serait
        # normalement reclassé en `confirmed` par l'audit. On vérifie que
        # le statut `human_flagged` est préservé malgré tout.
        close_vector = np.zeros(512, dtype=np.float32)
        close_vector[0] = 1.0  # un vecteur unitaire trivial

        img = Image(
            entity_id=e.id,
            source_url="x",
            local_path="/tmp/x",
            identity_embedding=close_vector.tobytes(),
            association_status="human_flagged",
            identity_match_score=None,
        )
        db.add(img)
        db.commit()

        audit_entity(e.id)
        db.refresh(img)
        assert img.association_status == "human_flagged"

    def test_centroid_excludes_human_flagged(self, db):
        """Une image signalée par l'humain ne doit pas contribuer au
        centroïde de l'entité (sinon la référence est polluée par les
        mauvaises attributions identifiées)."""
        import numpy as np

        from database import Entity, Image
        from identity_audit import update_centroid

        e = Entity(name="Test, Sujet", slug="test-sujet-3")
        db.add(e)
        db.flush()

        good = np.array([1.0] + [0.0] * 511, dtype=np.float32)
        bad = np.array([0.0] * 511 + [1.0], dtype=np.float32)
        db.add_all(
            [
                Image(
                    entity_id=e.id,
                    source_url="ok",
                    local_path="/tmp/ok",
                    identity_embedding=good.tobytes(),
                    association_status="confirmed",
                ),
                Image(
                    entity_id=e.id,
                    source_url="bad",
                    local_path="/tmp/bad",
                    identity_embedding=bad.tobytes(),
                    association_status="human_flagged",
                ),
            ]
        )
        db.commit()

        n = update_centroid(e.id)
        # Une seule image contributrice (la `confirmed`), pas deux
        assert n == 1
        db.refresh(e)
        # Centroïde = `good` après normalisation L2 — il doit pointer sur
        # la première dimension, pas la dernière (bad).
        centroid = np.frombuffer(e.identity_centroid, dtype=np.float32)
        assert centroid[0] > 0.9
        assert centroid[-1] < 0.1


class TestImageLandmarksEndpoint:
    """GET /images/{id}/landmarks — mesh 478 points (v024)."""

    def test_returns_mesh_when_blob_present(self, client, db, static_dir):
        """L'image flagged `img` a une FaceAnalysis dans la fixture —
        on lui attache un mesh factice et on vérifie l'endpoint."""
        import numpy as np
        from database import FaceAnalysis

        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        mesh = np.random.rand(478, 2).astype(np.float32)
        fa = db.scalar(
            db.query(FaceAnalysis).filter_by(image_id=img.id).statement
        )
        fa.landmarks_blob = mesh.tobytes()
        db.commit()

        r = client.get(f"/images/{img.id}/landmarks")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 478
        assert len(data["points"]) == 478
        # Vérif structure : chaque point = [x, y]
        assert all(
            isinstance(p, list) and len(p) == 2
            for p in data["points"][:5]
        )

    def test_404_when_blob_missing(self, client, db, static_dir):
        """Image analysée avant v024 : landmarks_blob = NULL → 404."""
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        # `img` a face_analysis mais pas de landmarks_blob (NULL par défaut)
        r = client.get(f"/images/{img.id}/landmarks")
        assert r.status_code == 404

    def test_404_unknown_image(self, client):
        r = client.get("/images/99999/landmarks")
        assert r.status_code == 404

    def test_face_out_has_full_mesh_flag(self, client, db, static_dir):
        """L'endpoint /entities/{slug}/images renvoie `has_full_mesh`
        sur chaque image via `face` → permet à l'UI de décider d'appeler
        cet endpoint ou de fallback aux 3 points."""
        import numpy as np
        from database import FaceAnalysis

        altman, _, img, _ = _seed_two_with_flagged(db, static_dir)
        # img a face_analysis, on lui attache le mesh
        fa = db.scalar(
            db.query(FaceAnalysis).filter_by(image_id=img.id).statement
        )
        fa.landmarks_blob = np.zeros((478, 2), dtype=np.float32).tobytes()
        db.commit()

        # L'endpoint /images filtre `association_status != flagged` →
        # img qui est flagged n'apparaît pas. On modifie temporairement
        # le statut pour ce test.
        from database import Image
        img.association_status = "confirmed"
        db.commit()

        body = client.get(f"/entities/{altman.slug}/images").json()
        target = next((i for i in body["images"] if i["id"] == img.id), None)
        assert target is not None
        assert target["face"]["has_full_mesh"] is True


class TestConfirmImageEndpoint:
    """POST /images/{id}/confirm — l'image est correcte, ArcFace s'est
    trompé en la signalant (variation d'âge, profil, lunettes…). On la
    sort de la queue d'audit sans changer d'entité.
    """

    def test_confirm_basic(self, client, db, static_dir):
        """Une image flagged bascule en manual sans changer d'entité."""
        altman, _, img, _ = _seed_two_with_flagged(db, static_dir)
        assert img.association_status == "flagged"

        r = client.post(f"/images/{img.id}/confirm")
        assert r.status_code == 200
        body = r.json()
        assert body["image_id"] == img.id
        assert body["entity_slug"] == "sam-altman"
        assert body["new_status"] == "manual"

        db.refresh(img)
        assert img.association_status == "manual"
        assert img.entity_id == altman.id  # entité inchangée

    def test_confirm_removes_from_flagged_queue(self, client, db, static_dir):
        """L'image confirmée disparaît de /flagged."""
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)

        before = client.get("/flagged").json()
        assert before["total"] == 1

        client.post(f"/images/{img.id}/confirm")

        after = client.get("/flagged").json()
        assert after["total"] == 0

    def test_confirm_idempotent_on_manual(self, client, db, static_dir):
        """Confirmer une image déjà manual = noop, 200."""
        _, _, img, _ = _seed_two_with_flagged(db, static_dir)
        img.association_status = "manual"
        db.commit()

        r = client.post(f"/images/{img.id}/confirm")
        assert r.status_code == 200
        assert r.json()["new_status"] == "manual"

    def test_confirm_works_on_human_flagged(self, client, db, static_dir):
        """Un humain peut revenir sur son propre signalement (bouton
        confirmer après s'être trompé). human_flagged → manual."""
        _, _, _, img_ok = _seed_two_with_flagged(db, static_dir)
        img_ok.association_status = "human_flagged"
        db.commit()

        r = client.post(f"/images/{img_ok.id}/confirm")
        assert r.status_code == 200
        db.refresh(img_ok)
        assert img_ok.association_status == "manual"

    def test_confirm_unknown_404(self, client):
        r = client.post("/images/99999/confirm")
        assert r.status_code == 404

    def test_confirmed_image_survives_re_audit(self, db, static_dir):
        """Une image confirmée résiste à un nouveau cycle audit_entity
        même si sa distance ArcFace est énorme (l'audit exclut `manual`).
        Couvert par TestManualNotReAudited.test_audit_skips_manual,
        on duplique ici pour blinder le contrat de l'endpoint confirm.
        """
        import numpy as np

        from database import Entity, Image
        from identity_audit import audit_entity

        e = Entity(name="Test, Confirm", slug="test-confirm")
        e.identity_centroid = np.zeros(512, dtype=np.float32).tobytes()
        e.identity_count = 5
        db.add(e)
        db.flush()

        far = np.ones(512, dtype=np.float32)
        far /= np.linalg.norm(far)

        img = Image(
            entity_id=e.id,
            source_url="x",
            local_path="/tmp/x",
            identity_embedding=far.tobytes(),
            association_status="flagged",
            identity_match_score=0.95,
        )
        db.add(img)
        db.commit()

        # Confirm via une session séparée (l'endpoint commit puis ferme)
        img.association_status = "manual"
        db.commit()

        audit_entity(e.id)
        db.refresh(img)
        assert img.association_status == "manual"
