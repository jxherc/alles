"""phase 7a — people & faces: clustering math, endpoints, and (with models present) detection."""

from unittest import mock, skipUnless

import numpy as np

from core.database import Face, Person, Photo
from services import faces
from tests._client import ApiTest


def _vec(i):  # a 512-dim unit basis vector — orthogonal ones read as "different people"
    v = np.zeros(faces.DIM, dtype=np.float32)
    v[i] = 1.0
    return v


class FacesTests(ApiTest):
    def _photo(self, name="p.jpg", **kw):
        db = self.db()
        p = Photo(filename="s-" + name, original_name=name, **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def _face(self, photo_id, vec, person_id=None, score=0.9):
        db = self.db()
        f = Face(
            photo_id=photo_id,
            person_id=person_id,
            bbox="0,0,10,10",
            det_score=score,
            embedding=faces.to_blob(vec),
        )
        db.add(f)
        db.commit()
        fid = f.id
        db.close()
        return fid

    # ── status / availability ──
    def test_status_shape(self):
        d = self.client.get("/api/photos/faces-status").json()
        for k in ("available", "scanned", "total", "people", "faces"):
            self.assertIn(k, d)

    # ── clustering ──
    def test_cluster_groups_same_face_only(self):
        # two matching faces form a person; a lone different face stays unassigned (min_size=2)
        self._face(self._photo(), _vec(0))
        self._face(self._photo(), _vec(0))
        self._face(self._photo(), _vec(7))  # singleton
        db = self.db()
        faces.cluster(db)
        people = db.query(Person).all()
        sizes = {p.id: db.query(Face).filter(Face.person_id == p.id).count() for p in people}
        unassigned = db.query(Face).filter(Face.person_id == None).count()  # noqa: E711
        db.close()
        self.assertEqual(len(people), 1)
        self.assertEqual(list(sizes.values()), [2])
        self.assertEqual(unassigned, 1)

    def test_cluster_joins_existing_named_person(self):
        # a new face near a named cluster joins it (keeps the name), no new person spawned
        pid = self._photo()
        db = self.db()
        per = Person(name="Ann")
        db.add(per)
        db.flush()
        f0 = Face(
            photo_id=pid,
            person_id=per.id,
            bbox="0,0,10,10",
            det_score=0.9,
            embedding=faces.to_blob(_vec(1)),
        )
        db.add(f0)
        per.cover_face_id = f0.id
        db.commit()
        per_id = per.id
        db.close()
        free = self._face(self._photo(), _vec(1))  # same direction → should join Ann
        db = self.db()
        faces.cluster(db)
        self.assertEqual(db.query(Person).count(), 1)
        self.assertEqual(db.get(Face, free).person_id, per_id)
        self.assertEqual(db.get(Person, per_id).name, "Ann")
        db.close()

    # ── people / person endpoints ──
    def test_people_lists_named_first_with_counts(self):
        named = self._photo()
        db = self.db()
        per = Person(name="Zoe")
        db.add(per)
        db.flush()
        per_id = per.id
        db.add(
            Face(
                photo_id=named,
                person_id=per_id,
                bbox="0,0,9,9",
                det_score=0.8,
                embedding=faces.to_blob(_vec(2)),
            )
        )
        # an unnamed cluster across two photos
        un = Person()
        db.add(un)
        db.flush()
        un_id = un.id
        for _ in range(2):
            ph = Photo(filename="x", original_name="x")
            db.add(ph)
            db.flush()
            db.add(
                Face(
                    photo_id=ph.id,
                    person_id=un_id,
                    bbox="0,0,9,9",
                    det_score=0.8,
                    embedding=faces.to_blob(_vec(3)),
                )
            )
        db.commit()
        db.close()
        d = self.client.get("/api/photos/people").json()
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["people"][0]["name"], "Zoe")  # named first
        self.assertEqual(d["people"][0]["count"], 1)
        self.assertEqual(d["people"][1]["name"], "")  # unnamed second
        self.assertEqual(d["people"][1]["count"], 2)

    def test_person_photos_returns_their_timeline(self):
        p1, p2, _ = self._photo(), self._photo(), self._photo()
        db = self.db()
        per = Person(name="Bo")
        db.add(per)
        db.flush()
        per_id = per.id
        for ph in (p1, p2):
            db.add(
                Face(
                    photo_id=ph,
                    person_id=per_id,
                    bbox="0,0,9,9",
                    det_score=0.8,
                    embedding=faces.to_blob(_vec(4)),
                )
            )
        db.commit()
        db.close()
        d = self.client.get(f"/api/photos/person/{per_id}").json()
        self.assertEqual(d["count"], 2)  # only the two photos Bo is in, not `other`
        self.assertEqual(d["person"]["name"], "Bo")

    def test_name_and_hide(self):
        pid = self._photo()
        db = self.db()
        per = Person()
        db.add(per)
        db.flush()
        per_id = per.id
        db.add(
            Face(
                photo_id=pid,
                person_id=per_id,
                bbox="0,0,9,9",
                det_score=0.8,
                embedding=faces.to_blob(_vec(5)),
            )
        )
        db.commit()
        db.close()
        self.client.post(f"/api/photos/person/{per_id}/name", json={"name": "  Cleo "})
        self.assertEqual(self.client.get("/api/photos/people").json()["people"][0]["name"], "Cleo")
        self.client.post(f"/api/photos/person/{per_id}/hide")
        self.assertEqual(self.client.get("/api/photos/people").json()["count"], 0)

    def test_merge_folds_clusters_and_adopts_name(self):
        pa, pb = self._photo(), self._photo()
        db = self.db()
        a = Person()  # unnamed
        b = Person(name="Dee")
        db.add_all([a, b])
        db.flush()
        a_id, b_id = a.id, b.id
        db.add(
            Face(
                photo_id=pa,
                person_id=a_id,
                bbox="0,0,9,9",
                det_score=0.8,
                embedding=faces.to_blob(_vec(6)),
            )
        )
        db.add(
            Face(
                photo_id=pb,
                person_id=b_id,
                bbox="0,0,9,9",
                det_score=0.8,
                embedding=faces.to_blob(_vec(6)),
            )
        )
        db.commit()
        db.close()
        r = self.client.post("/api/photos/people/merge", json={"ids": [a_id, b_id]}).json()
        self.assertEqual(r["id"], a_id)
        self.assertEqual(r["name"], "Dee")  # adopted the named one's name
        db = self.db()
        self.assertIsNone(db.get(Person, b_id))
        self.assertEqual(db.query(Face).filter(Face.person_id == a_id).count(), 2)
        db.close()

    def test_photo_faces_chips(self):
        pid = self._photo()
        db = self.db()
        per = Person(name="Eli")
        db.add(per)
        db.flush()
        per_id = per.id
        db.add(
            Face(
                photo_id=pid,
                person_id=per_id,
                bbox="0,0,9,9",
                det_score=0.9,
                embedding=faces.to_blob(_vec(0)),
            )
        )
        db.add(
            Face(
                photo_id=pid,
                person_id=None,
                bbox="1,1,9,9",
                det_score=0.7,
                embedding=faces.to_blob(_vec(1)),
            )
        )  # unclustered
        db.commit()
        db.close()
        d = self.client.get(f"/api/photos/photo/{pid}/faces").json()
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["faces"][0]["name"], "Eli")  # higher score first
        self.assertEqual(d["faces"][1]["person_id"], None)

    # ── indexing (DB path mocked; no real model needed) ──
    def test_index_pending_marks_scanned(self):
        pid = self._photo()
        fake = [{"bbox": (0, 0, 10, 10), "score": 0.9, "emb": _vec(3)}]
        with (
            mock.patch.object(faces, "available", return_value=True),
            mock.patch.object(faces, "detect_embed", return_value=fake),
            mock.patch("services.photos_store.original_path") as op,
        ):
            op.return_value.read_bytes.return_value = b"x"
            db = self.db()
            n = faces.index_pending(db, limit=5)
            db.close()
        self.assertEqual(n, 1)
        db = self.db()
        p = db.get(Photo, pid)
        fc = db.query(Face).filter(Face.photo_id == pid).count()
        db.close()
        self.assertIsNotNone(p.faces_at)
        self.assertEqual(fc, 1)

    # ── real model (only when buffalo_l is installed) ──
    @skipUnless(faces.available(), "face models not present")
    def test_detect_real_face(self):
        import io as _io

        from insightface.data import get_image as ins
        from PIL import Image

        arr = ins("t1")[:, :, ::-1]  # bundled sample, BGR -> RGB
        buf = _io.BytesIO()
        Image.fromarray(arr).save(buf, "JPEG")
        res = faces.detect_embed(buf.getvalue())
        self.assertGreaterEqual(len(res), 1)
        self.assertEqual(res[0]["emb"].shape[0], faces.DIM)
        self.assertAlmostEqual(float(np.linalg.norm(res[0]["emb"])), 1.0, places=3)
