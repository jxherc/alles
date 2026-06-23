"""stage 0b - soft-delete / archive polymorphism. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_registry_covers_all_six_models(self):
        names = {m.__name__ for m in lifecycle.LIFECYCLE}
        self.assertEqual(names, {"Session", "Note", "Account", "Habit", "ReadItem", "Photo"})

    def test_is_active_note_flag(self):
        n = db.Note(title="a", content="x")
        self.s.add(n)
        self.s.commit()
        self.assertTrue(lifecycle.is_active(n))
        n.archived = True
        self.assertFalse(lifecycle.is_active(n))

    def test_is_active_photo_timestamp(self):
        p = db.Photo(filename="x.jpg", original_name="x.jpg")
        self.s.add(p)
        self.s.commit()
        self.assertTrue(lifecycle.is_active(p))
        p.deleted_at = datetime.datetime.utcnow()
        self.assertFalse(lifecycle.is_active(p))

    def test_active_query_excludes_archived_notes(self):
        self.s.add_all(
            [db.Note(title="live", content=""), db.Note(title="gone", content="", archived=True)]
        )
        self.s.commit()
        rows = lifecycle.active(self.s.query(db.Note)).all()
        self.assertEqual([r.title for r in rows], ["live"])

    def test_active_query_excludes_deleted_photos(self):
        self.s.add_all(
            [
                db.Photo(filename="a.jpg", original_name="a"),
                db.Photo(
                    filename="b.jpg", original_name="b", deleted_at=datetime.datetime.utcnow()
                ),
            ]
        )
        self.s.commit()
        rows = lifecycle.active(self.s.query(db.Photo)).all()
        self.assertEqual([r.filename for r in rows], ["a.jpg"])

    def test_inactive_query_only_archived_notes(self):
        self.s.add_all(
            [db.Note(title="live", content=""), db.Note(title="gone", content="", archived=True)]
        )
        self.s.commit()
        rows = lifecycle.inactive(self.s.query(db.Note)).all()
        self.assertEqual([r.title for r in rows], ["gone"])

    def test_inactive_query_only_deleted_photos(self):
        self.s.add_all(
            [
                db.Photo(filename="a.jpg", original_name="a"),
                db.Photo(
                    filename="b.jpg", original_name="b", deleted_at=datetime.datetime.utcnow()
                ),
            ]
        )
        self.s.commit()
        rows = lifecycle.inactive(self.s.query(db.Photo)).all()
        self.assertEqual([r.filename for r in rows], ["b.jpg"])

    def test_soft_delete_note_sets_flag(self):
        n = db.Note(title="a", content="x")
        self.s.add(n)
        self.s.commit()
        lifecycle.soft_delete(self.s, n)
        self.assertTrue(n.archived)
        self.assertFalse(lifecycle.is_active(n))

    def test_soft_delete_photo_sets_timestamp(self):
        p = db.Photo(filename="x.jpg", original_name="x")
        self.s.add(p)
        self.s.commit()
        lifecycle.soft_delete(self.s, p)
        self.assertIsNotNone(p.deleted_at)
        self.assertFalse(lifecycle.is_active(p))

    def test_restore_note_clears_flag(self):
        n = db.Note(title="a", content="x", archived=True)
        self.s.add(n)
        self.s.commit()
        lifecycle.restore(self.s, n)
        self.assertFalse(n.archived)
        self.assertTrue(lifecycle.is_active(n))

    def test_restore_photo_clears_timestamp(self):
        p = db.Photo(filename="x.jpg", original_name="x", deleted_at=datetime.datetime.utcnow())
        self.s.add(p)
        self.s.commit()
        lifecycle.restore(self.s, p)
        self.assertIsNone(p.deleted_at)
        self.assertTrue(lifecycle.is_active(p))


class AdoptionIntegrationTests(unittest.TestCase):
    """Task 0b-2 - the helper is adopted in notes + sessions routes; behavior must be identical."""

    def setUp(self):
        from starlette.testclient import TestClient

        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_notes_default_hides_archived_and_filter_shows_only_archived(self):
        live = self.c.post(
            "/api/notes", json={"title": "live", "content": "a", "tags": "keep"}
        ).json()["id"]
        gone = self.c.post(
            "/api/notes", json={"title": "gone", "content": "b", "tags": "drop"}
        ).json()["id"]
        self.c.post(f"/api/notes/{gone}/archive", json={"archived": True})
        default_ids = {n["id"] for n in self.c.get("/api/notes").json()}
        archived_ids = {n["id"] for n in self.c.get("/api/notes?archived=true").json()}
        self.assertEqual(default_ids, {live})
        self.assertEqual(archived_ids, {gone})

    def test_notes_tags_ignore_archived(self):
        keep = self.c.post(
            "/api/notes", json={"title": "k", "content": "", "tags": "alpha"}
        ).json()["id"]
        drop = self.c.post("/api/notes", json={"title": "d", "content": "", "tags": "beta"}).json()[
            "id"
        ]
        self.c.post(f"/api/notes/{drop}/archive", json={"archived": True})
        tags = {t["tag"] for t in self.c.get("/api/notes/tags").json()}
        self.assertIn("alpha", tags)
        self.assertNotIn("beta", tags)  # archived note's tag is excluded
        self.assertTrue(keep)

    def test_sessions_list_excludes_archived(self):
        sid = self.c.post("/api/sessions", json={"name": "s1"}).json()["id"]
        self.c.post(f"/api/sessions/{sid}/archive")
        groups = self.c.get("/api/sessions").json()
        all_ids = {s["id"] for g in groups.values() for s in g}
        self.assertNotIn(sid, all_ids)


if __name__ == "__main__":
    unittest.main()
