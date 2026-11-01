import logging
import sqlite3
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from core import database
from core.api_errors import database_busy_handler


def _app(error):
    app = FastAPI()
    app.add_exception_handler(OperationalError, database_busy_handler)

    @app.post("/save")
    def save():
        raise error

    return app


class _Conn:
    def __init__(self):
        self.info = {}


class DatabaseBusyTests(unittest.TestCase):
    def test_locked_write_answers_busy_not_500(self):
        locked = OperationalError("commit", {}, sqlite3.OperationalError("database is locked"))
        res = TestClient(_app(locked)).post("/save")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["code"], "database_busy")
        self.assertEqual(res.headers["retry-after"], "2")

    def test_other_operational_errors_stay_500(self):
        broken = OperationalError("select", {}, sqlite3.OperationalError("no such table: x"))
        res = TestClient(_app(broken), raise_server_exceptions=False).post("/save")
        self.assertEqual(res.status_code, 500)

    def test_long_write_names_the_writer(self):
        conn = _Conn()
        database._note_first_write(conn, None, "INSERT INTO x VALUES (1)", None, None, False)
        self.assertIn("test_database_busy.py", conn.info["write_where"])
        conn.info["write_started"] -= database._LONG_WRITE_S + 1
        with self.assertLogs("alles.db", logging.WARNING) as logs:
            database._end_write(conn)
        self.assertIn("held the database", logs.output[0])
        self.assertNotIn("write_started", conn.info)

    def test_reads_do_not_start_the_clock(self):
        conn = _Conn()
        database._note_first_write(conn, None, "select 1", None, None, False)
        self.assertNotIn("write_started", conn.info)


if __name__ == "__main__":
    unittest.main()
