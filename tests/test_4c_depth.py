"""stage 4c - share expiry/password + smart albums. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"

import core.database as db
from services import share
from services import smart_albums as sa


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
        self.assertEqual(sh.expires_at, "2026-12-31T00:00:00Z")
        self.assertTrue(sh.password_hash)
        self.assertNotEqual(sh.password_hash, "secret")  # hashed
        self.assertTrue(sh.password_hash.startswith("v2-bcrypt:$2"))

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

    def test_expiry_normalizes_offsets_and_rejects_invalid_text(self):
        sh = share.mint(self.s, "photo", "offset", expires_at="2026-01-01T08:00:00+08:00")
        self.assertEqual(sh.expires_at, "2026-01-01T00:00:00Z")
        self.assertFalse(share.is_expired(sh, now="2025-12-31T23:59:59Z"))
        self.assertTrue(share.is_expired(sh, now="2026-01-01T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "valid ISO"):
            share.mint(self.s, "photo", "invalid", expires_at="not-a-date")

    def test_malformed_stored_expiry_fails_closed(self):
        sh = share.mint(self.s, "photo", "malformed")
        sh.expires_at = "not-a-date"
        self.s.commit()
        self.assertTrue(share.is_expired(sh))

    def test_legacy_sha_password_upgrades_after_success(self):
        sh = share.mint(self.s, "photo", "legacy")
        sh.password_hash = share._legacy_pw_hash("hunter2")
        self.s.commit()
        self.assertIsNotNone(share.resolve(self.s, sh.token, password="hunter2"))
        self.s.refresh(sh)
        self.assertTrue(sh.password_hash.startswith("v2-bcrypt:$2"))

    def test_migration_wraps_dormant_legacy_hash_without_plaintext(self):
        from core.migrations import m0024_share_password_hashes as migration

        sh = share.mint(self.s, "photo", "dormant")
        sh.password_hash = share._legacy_pw_hash("old-password")
        share_id = sh.id
        self.s.commit()
        self.s.close()
        with self.eng.begin() as conn:
            migration.up(conn)
            migration.up(conn)
        self.s = db.SessionLocal()
        migrated = self.s.get(db.Share, share_id)
        self.assertTrue(migrated.password_hash.startswith("legacy-bcrypt:$2"))
        self.assertTrue(share.check_password(migrated, "old-password"))
        self.assertFalse(share.check_password(migrated, "wrong"))
        self.assertIsNotNone(share.resolve(self.s, migrated.token, password="old-password"))
        self.s.refresh(migrated)
        self.assertTrue(migrated.password_hash.startswith("v2-bcrypt:$2"))

    def test_legacy_upgrade_cannot_overwrite_concurrent_password_change(self):
        sh = share.mint(self.s, "photo", "legacy-race")
        sh.password_hash = share._legacy_pw_hash("old-password")
        self.s.commit()
        stale = self.s.get(db.Share, sh.id)
        self.assertTrue(share._is_legacy_hash(stale.password_hash))

        other = db.SessionLocal()
        try:
            current = other.get(db.Share, sh.id)
            current.password_hash = share._pw_hash("new-password")
            other.commit()
        finally:
            other.close()

        self.assertFalse(share.upgrade_password_hash(stale, "old-password", self.s))
        self.assertFalse(share.check_password(stale, "old-password"))
        self.assertTrue(share.check_password(stale, "new-password"))

    def test_password_change_revokes_existing_unlock_grants(self):
        sh = share.mint(self.s, "photo", "grant", password="first")
        grant = share.new_grant(sh.token, sh.password_hash)
        self.assertTrue(share.check_grant(sh.token, sh.password_hash, grant))
        share.mint(self.s, "photo", "grant", password="second")
        self.assertFalse(share.check_grant(sh.token, sh.password_hash, grant))

    def test_long_passwords_are_rejected_without_bcrypt_truncation(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            share.mint(self.s, "photo", "long-password", password="x" * 1025)

    def test_unlock_grant_expires(self):
        grant = share.new_grant("token", "hash", now=10)
        self.assertTrue(share.check_grant("token", "hash", grant, now=10 + share.GRANT_SECONDS - 1))
        self.assertFalse(share.check_grant("token", "hash", grant, now=10 + share.GRANT_SECONDS))

    def test_unlock_grant_is_bound_to_one_share(self):
        grant = share.new_grant("share-a", "hash-a")
        self.assertTrue(share.check_grant("share-a", "hash-a", grant))
        self.assertFalse(share.check_grant("share-b", "hash-a", grant))

    def test_late_grant_from_old_password_version_is_rejected(self):
        sh = share.mint(self.s, "photo", "race", password="first")
        old_hash = sh.password_hash
        share.mint(self.s, "photo", "race", password="second")
        late_grant = share.new_grant(sh.token, old_hash)
        self.assertFalse(share.check_grant(sh.token, sh.password_hash, late_grant))


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
        locked = self.c.get(f"/s/{tok}")
        self.assertEqual(locked.status_code, 401)  # no password
        self.assertIn("no-store", locked.headers["cache-control"])
        wrong = self.c.post(f"/s/{tok}/unlock", data={"password": "wrong"})
        self.assertEqual(wrong.status_code, 401)
        self.assertIn("wrong password", wrong.text)

    def test_correct_password_passes_gate(self):
        tok = self._mint(password="hunter2")
        unlocked = self.c.post(
            f"/s/{tok}/unlock", data={"password": "hunter2"}, follow_redirects=False
        )
        self.assertEqual(unlocked.status_code, 303)
        self.assertIn("httponly", unlocked.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", unlocked.headers["set-cookie"].lower())
        r = self.c.get(f"/s/{tok}")
        # gate passed -> not 401/410 (content read may 404 since the doc doesn't exist, that's fine)
        self.assertNotIn(r.status_code, (401, 410))
        if r.status_code == 200:
            self.assertIn("no-store", r.headers["cache-control"])

    def test_unlock_attempts_are_rate_limited(self):
        tok = self._mint(password="hunter2")
        for _ in range(10):
            self.assertEqual(
                self.c.post(f"/s/{tok}/unlock", data={"password": "wrong"}).status_code,
                401,
            )
        blocked = self.c.post(f"/s/{tok}/unlock", data={"password": "wrong"})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["code"], "rate_limited")
        self.assertIn("retry-after", blocked.headers)

    def test_https_unlock_cookie_is_secure(self):
        from fastapi.testclient import TestClient

        from app import app

        tok = self._mint(password="hunter2")
        secure_client = TestClient(app, base_url="https://testserver")
        unlocked = secure_client.post(
            f"/s/{tok}/unlock", data={"password": "hunter2"}, follow_redirects=False
        )
        self.assertEqual(unlocked.status_code, 303)
        self.assertIn("secure", unlocked.headers["set-cookie"].lower())

    def test_password_change_expiry_and_revoke_invalidate_unlocked_access(self):
        tok = self._mint(password="first")
        self.assertEqual(
            self.c.post(
                f"/s/{tok}/unlock", data={"password": "first"}, follow_redirects=False
            ).status_code,
            303,
        )
        changed = self.c.post(
            "/api/share", json={"kind": "doc", "ref": "note.md", "password": "second"}
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.c.get(f"/s/{tok}").status_code, 401)

        self.assertEqual(
            self.c.post(
                f"/s/{tok}/unlock", data={"password": "second"}, follow_redirects=False
            ).status_code,
            303,
        )
        expired = self.c.post(
            "/api/share",
            json={"kind": "doc", "ref": "note.md", "expires_at": "2000-01-01T00:00:00Z"},
        )
        self.assertEqual(expired.status_code, 200)
        self.assertEqual(self.c.get(f"/s/{tok}").status_code, 410)

        self.assertTrue(
            self.c.request("DELETE", "/api/share", json={"kind": "doc", "ref": "note.md"}).json()[
                "ok"
            ]
        )
        self.assertEqual(self.c.get(f"/s/{tok}").status_code, 404)

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
