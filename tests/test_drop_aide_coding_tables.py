import importlib
import unittest

from sqlalchemy import create_engine, text

m0082 = importlib.import_module("core.migrations.m0082_drop_aide_coding_tables")


def _tables(conn):
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
    return {row[0] for row in rows}


class DropAideCodingTablesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def _make(self, conn):
        conn.execute(text("CREATE TABLE aide_coding_runs (id VARCHAR PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE aide_coding_run_events (id VARCHAR PRIMARY KEY, run_id VARCHAR, "
                "FOREIGN KEY(run_id) REFERENCES aide_coding_runs(id))"
            )
        )
        conn.execute(text("CREATE TABLE dsh_connections (id VARCHAR PRIMARY KEY)"))

    def test_empty_tables_are_dropped(self):
        with self.engine.begin() as conn:
            self._make(conn)
            m0082.up(conn)
            self.assertFalse(set(m0082.TABLES) & _tables(conn))

    def test_a_table_with_rows_is_left_alone(self):
        with self.engine.begin() as conn:
            self._make(conn)
            conn.execute(text("INSERT INTO dsh_connections (id) VALUES ('default')"))
            conn.execute(text("INSERT INTO aide_coding_runs (id) VALUES ('r1')"))
            m0082.up(conn)
            left = _tables(conn)
            self.assertIn("dsh_connections", left)
            self.assertIn("aide_coding_runs", left)
            self.assertNotIn("aide_coding_run_events", left)

    def test_missing_tables_are_fine_and_a_second_run_changes_nothing(self):
        with self.engine.begin() as conn:
            m0082.up(conn)
            self._make(conn)
            m0082.up(conn)
            m0082.up(conn)
            self.assertFalse(set(m0082.TABLES) & _tables(conn))
