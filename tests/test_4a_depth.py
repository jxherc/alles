"""stage 4a - contact relationship graph + calendar conflict detection. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import cal_conflict, contacts_graph as cg


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.a = db.Contact(name="Ann")
        self.b = db.Contact(name="Bob")
        self.c = db.Contact(name="Cara")
        self.s.add_all([self.a, self.b, self.c])
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_link_creates_reciprocal(self):
        cg.link(self.s, self.a.id, self.b.id, "spouse")
        self.assertEqual(len(self.s.query(db.ContactLink).all()), 2)  # both directions

    def test_inverse_kind(self):
        cg.link(self.s, self.a.id, self.b.id, "manager")  # a manages b
        back = next(n for n in cg.neighbors(self.s, self.b.id) if n["id"] == self.a.id)
        self.assertEqual(back["kind"], "report")  # b's view of a is "report"

    def test_neighbors_and_kind_filter(self):
        cg.link(self.s, self.a.id, self.b.id, "colleague")
        cg.link(self.s, self.a.id, self.c.id, "friend")
        self.assertEqual(len(cg.neighbors(self.s, self.a.id)), 2)
        self.assertEqual(
            [n["id"] for n in cg.neighbors(self.s, self.a.id, kind="friend")], [self.c.id]
        )

    def test_unlink_both_directions(self):
        cg.link(self.s, self.a.id, self.b.id, "spouse")
        cg.unlink(self.s, self.a.id, self.b.id)
        self.assertEqual(self.s.query(db.ContactLink).count(), 0)

    def test_no_self_link(self):
        with self.assertRaises(ValueError):
            cg.link(self.s, self.a.id, self.a.id, "friend")

    def test_dup_link_idempotent(self):
        cg.link(self.s, self.a.id, self.b.id, "friend")
        cg.link(self.s, self.a.id, self.b.id, "friend")  # again
        self.assertEqual(len(cg.neighbors(self.s, self.a.id)), 1)

    def test_related_for_invite(self):
        cg.link(self.s, self.a.id, self.b.id, "spouse")
        cg.link(self.s, self.c.id, self.a.id, "colleague")
        rel = cg.related_for_invite(self.s, [self.a.id])
        ids = {r["id"] for r in rel}
        self.assertEqual(ids, {self.b.id, self.c.id})  # not the invitee herself


class ConflictTests(unittest.TestCase):
    def _ev(self, s, e, all_day=False, title="x"):
        return {"title": title, "start_dt": s, "end_dt": e, "all_day": all_day}

    def test_overlap_detected(self):
        evs = [
            self._ev("2026-06-23T10:00", "2026-06-23T11:00", title="A"),
            self._ev("2026-06-23T10:30", "2026-06-23T11:30", title="B"),
        ]
        c = cal_conflict.conflicts(evs)
        self.assertEqual(len(c), 1)
        self.assertEqual({c[0]["a"], c[0]["b"]}, {"A", "B"})

    def test_touching_not_overlap(self):
        evs = [
            self._ev("2026-06-23T10:00", "2026-06-23T11:00"),
            self._ev("2026-06-23T11:00", "2026-06-23T12:00"),  # starts exactly when first ends
        ]
        self.assertEqual(cal_conflict.conflicts(evs), [])

    def test_all_day_ignored(self):
        evs = [
            self._ev("2026-06-23", "2026-06-23", all_day=True),
            self._ev("2026-06-23T10:00", "2026-06-23T11:00"),
        ]
        self.assertEqual(cal_conflict.conflicts(evs), [])

    def test_different_days_no_conflict(self):
        evs = [
            self._ev("2026-06-23T10:00", "2026-06-23T11:00"),
            self._ev("2026-06-24T10:00", "2026-06-24T11:00"),
        ]
        self.assertEqual(cal_conflict.conflicts(evs), [])

    def test_free_slots(self):
        evs = [
            self._ev("2026-06-23T09:00", "2026-06-23T10:00"),
            self._ev("2026-06-23T11:00", "2026-06-23T12:00"),
        ]
        slots = cal_conflict.free_slots(
            evs, "2026-06-23", day_start="09:00", day_end="17:00", duration_min=30
        )
        # a 30-min slot fits between 10:00 and 11:00, and after 12:00
        self.assertTrue(any(s["start"] == "10:00" for s in slots))

    def test_free_slots_full_day(self):
        evs = [self._ev("2026-06-23T09:00", "2026-06-23T17:00")]
        slots = cal_conflict.free_slots(
            evs, "2026-06-23", day_start="09:00", day_end="17:00", duration_min=30
        )
        self.assertEqual(slots, [])

    def test_free_slots_bad_day_no_crash(self):
        # a malformed day must not raise (was a 500 via datetime.fromisoformat)
        for bad in ("notadate", "2026-13-99", ""):
            self.assertEqual(cal_conflict.free_slots([], bad), [])


if __name__ == "__main__":
    unittest.main()
