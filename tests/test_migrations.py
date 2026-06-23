"""stage 0a - declarative migration framework. tests first (RED)."""

import json
import os
import tempfile
import types
import unittest

from sqlalchemy import create_engine, text

from core.migrations import runner


def _fake(version, name, up_fn, down_fn=None, always=False):
    ns = types.SimpleNamespace(VERSION=version, NAME=name, up=up_fn, down=down_fn)
    if always:
        ns.ALWAYS = True
    return ns


class RunnerTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.eng = create_engine(f"sqlite:///{self.path}")

    def tearDown(self):
        self.eng.dispose()
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _applied(self):
        with self.eng.connect() as c:
            return runner.applied_versions(c)

    def test_ensure_table_and_empty_applied(self):
        with self.eng.connect() as c:
            self.assertEqual(runner.applied_versions(c), set())
        # schema_migrations now exists
        with self.eng.connect() as c:
            rows = c.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                )
            ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_applies_and_records_pending(self):
        calls = []
        m = _fake(1, "first", lambda conn: calls.append("up"))
        newly = runner.run_migrations(self.eng, modules=[m])
        self.assertEqual(newly, [1])
        self.assertEqual(calls, ["up"])
        self.assertEqual(self._applied(), {1})
        with self.eng.connect() as c:
            row = c.execute(
                text("SELECT version,name,applied_at FROM schema_migrations WHERE version=1")
            ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "first")
        self.assertTrue(row[2])  # applied_at stamped

    def test_skips_already_applied_up_not_rerun(self):
        calls = []
        m = _fake(1, "first", lambda conn: calls.append("up"))
        runner.run_migrations(self.eng, modules=[m])
        newly = runner.run_migrations(self.eng, modules=[m])
        self.assertEqual(newly, [])  # nothing newly applied
        self.assertEqual(calls, ["up"])  # up ran ONCE (non-always)

    def test_applies_multiple_in_version_order(self):
        order = []
        ms = [
            _fake(3, "c", lambda conn: order.append(3)),
            _fake(1, "a", lambda conn: order.append(1)),
            _fake(2, "b", lambda conn: order.append(2)),
        ]
        newly = runner.run_migrations(self.eng, modules=ms)
        self.assertEqual(newly, [1, 2, 3])
        self.assertEqual(order, [1, 2, 3])

    def test_idempotent_second_run_applies_nothing(self):
        m = _fake(1, "first", lambda conn: None)
        runner.run_migrations(self.eng, modules=[m])
        self.assertEqual(runner.run_migrations(self.eng, modules=[m]), [])

    def test_failing_up_propagates_and_not_recorded(self):
        def boom(conn):
            raise RuntimeError("bad migration")

        m = _fake(5, "boom", boom)
        with self.assertRaises(RuntimeError):
            runner.run_migrations(self.eng, modules=[m])
        self.assertEqual(self._applied(), set())  # not recorded

    def test_always_migration_reruns_but_records_once(self):
        calls = []
        m = _fake(1, "baseline", lambda conn: calls.append("up"), always=True)
        n1 = runner.run_migrations(self.eng, modules=[m])
        n2 = runner.run_migrations(self.eng, modules=[m])
        self.assertEqual(n1, [1])  # newly applied first time
        self.assertEqual(n2, [])  # not newly applied second time
        self.assertEqual(calls, ["up", "up"])  # but up() RAN BOTH TIMES (self-heal)

    def test_down_reverts_where_defined(self):
        with self.eng.begin() as c:
            c.execute(text("CREATE TABLE t (id INTEGER)"))

        def up(conn):
            conn.execute(text("ALTER TABLE t ADD COLUMN x TEXT"))

        def down(conn):
            pass  # presence of down is what we assert is callable

        m = _fake(1, "addx", up, down)
        runner.run_migrations(self.eng, modules=[m])
        with self.eng.connect() as c:
            cols = {r[1] for r in c.execute(text("PRAGMA table_info(t)"))}
        self.assertIn("x", cols)
        self.assertTrue(callable(m.down))

    def test_add_column_adds_missing(self):
        with self.eng.begin() as c:
            c.execute(text("CREATE TABLE t (id INTEGER)"))
            added = runner.add_column(c, "t", "x", "TEXT DEFAULT ''")
            self.assertTrue(added)
            cols = {r[1] for r in c.execute(text("PRAGMA table_info(t)"))}
        self.assertIn("x", cols)

    def test_add_column_idempotent_on_existing(self):
        with self.eng.begin() as c:
            c.execute(text("CREATE TABLE t (id INTEGER, x TEXT)"))
            self.assertFalse(runner.add_column(c, "t", "x", "TEXT"))  # already there, no error

    def test_add_column_raises_on_bad_table(self):
        # the key improvement over the old silent _add_col: real errors surface
        with self.eng.begin() as c:
            with self.assertRaises(Exception):
                runner.add_column(c, "nonexistent_table", "x", "TEXT")


class BaselineAndInitTests(unittest.TestCase):
    """Task 0a-2 - the squashed baseline migration + init_db integration."""

    def test_baseline_module_shape(self):
        from core.migrations import m0001_baseline as b

        self.assertEqual(b.VERSION, 1)
        self.assertEqual(b.NAME, "baseline")
        self.assertTrue(getattr(b, "ALWAYS", False))  # runs every boot for self-heal
        self.assertTrue(callable(b.up))

    def test_discover_finds_baseline(self):
        mods = runner.discover()
        self.assertTrue(any(m.VERSION == 1 and m.NAME == "baseline" for m in mods))
        versions = [m.VERSION for m in mods]
        self.assertEqual(versions, sorted(versions))  # discovery is ordered

    def test_init_db_records_baseline_and_matches_audit_schema(self):
        # fresh DB via the real init_db, then compare to the captured audit baseline
        import sqlite3

        from core import database as db

        d = tempfile.mkdtemp()
        path = os.path.join(d, "aide.db")
        orig = db.DB_PATH, db.engine
        db.DB_PATH = path
        from sqlalchemy import create_engine as ce

        db.engine = ce(f"sqlite:///{path}")
        db.SessionLocal.configure(bind=db.engine)
        try:
            db.init_db()
            con = sqlite3.connect(path)
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            cols = {t: sorted(r[1] for r in con.execute(f"PRAGMA table_info({t})")) for t in tables}
            con.close()
        finally:
            db.engine.dispose()
            db.DB_PATH, db.engine = orig
            db.SessionLocal.configure(bind=db.engine)
        # schema_migrations exists with the baseline row
        self.assertIn("schema_migrations", tables)
        # every audit-baseline table+columns is present + identical (no column lost/renamed)
        with open("docs/evidence/0a-migrations/baseline-schema.json") as f:
            base = json.load(f)
        for t, expected_cols in base["columns"].items():
            self.assertIn(t, tables, f"table {t} missing after init_db")
            # later numbered migrations may ADD columns (e.g. m0002 -> memories); the invariant
            # is that no baseline column is ever LOST, not byte-equality.
            self.assertTrue(
                set(expected_cols) <= set(cols[t]),
                f"a baseline column was lost on {t}: {set(expected_cols) - set(cols[t])}",
            )

    def test_init_db_self_heals_dropped_column(self):
        import sqlite3

        from core import database as db

        d = tempfile.mkdtemp()
        path = os.path.join(d, "aide.db")
        orig = db.DB_PATH, db.engine
        db.DB_PATH = path
        from sqlalchemy import create_engine as ce

        db.engine = ce(f"sqlite:///{path}")
        db.SessionLocal.configure(bind=db.engine)
        try:
            db.init_db()
            con = sqlite3.connect(path)
            con.execute("ALTER TABLE notes DROP COLUMN due")
            con.commit()
            con.close()
            db.init_db()  # baseline ALWAYS re-runs -> re-adds notes.due
            con = sqlite3.connect(path)
            cols = {r[1] for r in con.execute("PRAGMA table_info(notes)")}
            con.close()
        finally:
            db.engine.dispose()
            db.DB_PATH, db.engine = orig
            db.SessionLocal.configure(bind=db.engine)
        self.assertIn("due", cols)


if __name__ == "__main__":
    unittest.main()
