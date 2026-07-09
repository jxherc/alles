"""server-hardening: the sqlite connect listener must set busy_timeout (so a write that
collides with a background job waits instead of throwing 'database is locked') and
synchronous=NORMAL (durable under WAL, far fewer fsyncs)."""

import tempfile
import unittest

from sqlalchemy import create_engine, event, text

from core.database import _set_wal


class DbPragmaTest(unittest.TestCase):
    def test_connect_listener_hardens_sqlite(self):
        with tempfile.TemporaryDirectory() as d:
            eng = create_engine(f"sqlite:///{d}/t.db", connect_args={"check_same_thread": False})
            event.listens_for(eng, "connect")(_set_wal)
            try:
                with eng.connect() as c:
                    # wait up to 5s on a lock rather than erroring immediately
                    self.assertGreaterEqual(c.execute(text("pragma busy_timeout")).scalar(), 1000)
                    # 1 == NORMAL (safe with WAL, fast)
                    self.assertEqual(c.execute(text("pragma synchronous")).scalar(), 1)
                    self.assertEqual(c.execute(text("pragma journal_mode")).scalar(), "wal")
                    self.assertEqual(c.execute(text("pragma foreign_keys")).scalar(), 1)
            finally:
                eng.dispose()
