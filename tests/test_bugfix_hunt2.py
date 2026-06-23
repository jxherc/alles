"""regression tests for bugs found in the 2nd bug-hunt iteration:
- non-finite (nan/inf) amounts must be rejected + must not brick money/health reads
- the secret-store guard must cover grep/glob/list/code_symbols, not just read_file
- the journal passcode lock must hide journal content from the timeline feed
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db


def _client():
    from fastapi.testclient import TestClient

    from app import app

    return TestClient(app)


class MoneyFiniteTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        s = db.SessionLocal()
        self.acc = db.Account(name="chk", kind="checking", opening=0.0)
        s.add(self.acc)
        s.commit()
        self.aid = self.acc.id
        s.close()
        self.c = _client()

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_create_rejects_infinity(self):
        # 1e400 is a valid JSON number literal that parses to float('inf') - the real attack vector
        body = '{"account_id": "%s", "date": "2026-06-01", "amount": 1e400}' % self.aid
        r = self.c.post(
            "/api/money/transactions", content=body, headers={"content-type": "application/json"}
        )
        self.assertEqual(r.status_code, 400)

    def test_poison_row_does_not_brick_reads(self):
        # simulate an already-stored non-finite amount (e.g. from an old import)
        s = db.SessionLocal()
        s.add(db.Transaction(account_id=self.aid, date="2026-06-01", amount=float("inf")))
        s.commit()
        s.close()
        # the read endpoints must still respond (coerced to 0), not 500
        self.assertEqual(self.c.get("/api/money/accounts").status_code, 200)
        self.assertEqual(self.c.get("/api/money/transactions").status_code, 200)

    def test_csv_import_skips_non_finite(self):
        body = {"account_id": self.aid, "csv": "date,amount\n2026-06-01,inf\n2026-06-02,-10"}
        r = self.c.post("/api/money/transactions/import.csv", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 1)  # the inf row skipped, the -10 row kept

    def test_transfer_rejects_non_finite(self):
        s = db.SessionLocal()
        b = db.Account(name="sav", kind="savings", opening=0.0)
        s.add(b)
        s.commit()
        bid = b.id
        s.close()
        body = (
            '{"from_account": "%s", "to_account": "%s", "amount": 1e400, "date": "2026-06-01"}'
            % (self.aid, bid)
        )
        r = self.c.post(
            "/api/money/transfer", content=body, headers={"content-type": "application/json"}
        )
        self.assertEqual(r.status_code, 400)


class HealthFiniteTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.c = _client()

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_health_rejects_infinity(self):
        body = '{"kind": "weight", "value": 1e400, "date": "2026-06-20"}'
        r = self.c.post("/api/health", content=body, headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 400)


class GrepSecretGuardTests(unittest.TestCase):
    def test_skip_secret_paths(self):
        from services import agent_tools as at

        with mock.patch.object(at, "_settings", return_value={}):
            self.assertTrue(at._skip_secret(Path("/home/u/.ssh/id_rsa")))
            self.assertTrue(at._skip_secret(Path("project/.env")))
            self.assertFalse(at._skip_secret(Path("project/main.py")))

    def test_grep_excludes_secret_file(self):
        from services import agent_tools as at

        d = Path(tempfile.mkdtemp())
        (d / "app.py").write_text("api usage here\n", "utf-8")
        (d / ".env").write_text("SECRET_KEY=topsecret123\n", "utf-8")
        with mock.patch.object(at, "_settings", return_value={"agent_cwd": str(d)}):
            out = asyncio.run(at._grep_files("topsecret123", path=str(d)))
        self.assertNotIn("topsecret123", out["output"])  # secret file skipped


class TimelineLockTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        s = db.SessionLocal()
        from datetime import datetime

        s.add(
            db.JournalEntry(
                date="2026-06-23",
                content="SECRETMARKER private stuff",
                mood="calm",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        s.commit()
        s.close()
        self.c = _client()

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_locked_journal_hidden_from_timeline(self):
        from core.settings import _defaults

        cfg = dict(_defaults)
        cfg["journal_passcode"] = "1234"
        with mock.patch("core.settings.load_settings", return_value=cfg):
            r = self.c.get("/api/timeline")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("SECRETMARKER", r.text)

    def test_unlocked_journal_shown(self):
        from core.settings import _defaults

        cfg = dict(_defaults)
        cfg["journal_passcode"] = ""
        with mock.patch("core.settings.load_settings", return_value=cfg):
            r = self.c.get("/api/timeline")
        self.assertIn("SECRETMARKER", r.text)


if __name__ == "__main__":
    unittest.main()
