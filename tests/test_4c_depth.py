"""stage 4c - share expiry/password + smart albums. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import share, smart_albums as sa


class ShareTests(unittest.TestCase):
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

    def test_mint_stores_expiry_and_pw(self):
        sh = share.mint(self.s, "photo", "p1", expires_at="2026-12-31T00:00:00", password="secret")
        self.assertEqual(sh.expires_at, "2026-12-31T00:00:00")
        self.assertTrue(sh.password_hash)
        self.assertNotEqual(sh.password_hash, "secret")  # hashed

    def test_resolve_live(self):
        sh = share.mint(self.s, "photo", "p1", expires_at="2099-01-01T00:00:00")
        self.assertIsNotNone(share.resolve(self.s, sh.token, now="2026-06-23T00:00:00"))

    def test_resolve_expired(self):
        sh = share.mint(self.s, "photo", "p1", expires_at="2020-01-01T00:00:00")
        self.assertIsNone(share.resolve(self.s, sh.token, now="2026-06-23T00:00:00"))

    def test_password_required_and_correct(self):
        sh = share.mint(self.s, "photo", "p1", password="hunter2")
        self.assertIsNone(share.resolve(self.s, sh.token, password=""))
        self.assertIsNone(share.resolve(self.s, sh.token, password="wrong"))
        self.assertIsNotNone(share.resolve(self.s, sh.token, password="hunter2"))

    def test_no_password_share_open(self):
        sh = share.mint(self.s, "photo", "p1")
        self.assertIsNotNone(share.resolve(self.s, sh.token))

    def test_resolve_unknown_token(self):
        self.assertIsNone(share.resolve(self.s, "nope"))


class SmartAlbumTests(unittest.TestCase):
    def _p(self, pid, taken_at, keywords=""):
        return {"id": pid, "taken_at": taken_at, "keywords": keywords}

    def test_group_by_month(self):
        photos = [
            self._p("a", "2026-06-01T10:00:00"),
            self._p("b", "2026-06-15T12:00:00"),
            self._p("c", "2026-07-04T09:00:00"),
        ]
        groups = sa.group_by_period(photos, period="month")
        self.assertEqual(len(groups["2026-06"]), 2)
        self.assertEqual(len(groups["2026-07"]), 1)

    def test_group_by_day(self):
        photos = [self._p("a", "2026-06-01T10:00:00"), self._p("b", "2026-06-01T22:00:00")]
        groups = sa.group_by_period(photos, period="day")
        self.assertEqual(len(groups["2026-06-01"]), 2)

    def test_missing_taken_at_unknown_bucket(self):
        photos = [self._p("a", ""), self._p("b", None)]
        groups = sa.group_by_period(photos, period="month")
        self.assertEqual(len(groups["unknown"]), 2)

    def test_in_range(self):
        photos = [
            self._p("a", "2026-06-01T10:00:00"),
            self._p("b", "2026-07-15T10:00:00"),
        ]
        res = sa.in_range(photos, "2026-06-01", "2026-06-30")
        self.assertEqual([p["id"] for p in res], ["a"])

    def test_by_keyword(self):
        photos = [
            self._p("a", "2026-06-01T10:00:00", keywords="beach,summer"),
            self._p("b", "2026-06-02T10:00:00", keywords="work"),
        ]
        self.assertEqual([p["id"] for p in sa.by_keyword(photos, "beach")], ["a"])


class ShareViewerGateTests(unittest.TestCase):
    """the public /s/{token} viewer must enforce expiry + password (was bypassed via lookup())."""

    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _mint(self, **kw):
        s = db.SessionLocal()
        sh = share.mint(s, "doc", "note.md", **kw)
        tok = sh.token
        s.close()
        return tok

    def test_expired_share_blocked(self):
        tok = self._mint(expires_at="2000-01-01T00:00:00")
        r = self.c.get(f"/s/{tok}", follow_redirects=True)
        self.assertEqual(r.status_code, 410)

    def test_password_share_requires_password(self):
        tok = self._mint(password="hunter2")
        self.assertEqual(self.c.get(f"/s/{tok}").status_code, 401)  # no pw
        self.assertEqual(self.c.get(f"/s/{tok}", params={"pw": "wrong"}).status_code, 401)

    def test_correct_password_passes_gate(self):
        tok = self._mint(password="hunter2")
        r = self.c.get(f"/s/{tok}", params={"pw": "hunter2"})
        # gate passed -> not 401/410 (content read may 404 since the doc doesn't exist, that's fine)
        self.assertNotIn(r.status_code, (401, 410))

    def test_open_share_still_works(self):
        tok = self._mint()
        self.assertNotIn(self.c.get(f"/s/{tok}").status_code, (401, 410))


class TxnLimitClampTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_huge_limit_no_overflow(self):
        # a value larger than a 64-bit int used to 500 via sqlite OverflowError
        r = self.c.get("/api/money/transactions", params={"limit": 99999999999999999999})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
