import os
import tempfile
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app import _cleanup_empty_sessions
from core.database import Message, Session
from core.migrations import m0068_aide_primary_session
from tests._client import ApiTest


class AidePrimaryConversationTest(ApiTest):
    def test_resolver_is_stable_and_does_not_rewrite_existing_sessions(self):
        old = self.client.post("/api/sessions", json={"name": "old task"}).json()

        first = self.client.get("/api/aide/conversation")
        second = self.client.get("/api/aide/conversation")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertTrue(first.json()["primary"])
        self.assertNotEqual(first.json()["id"], old["id"])

        db = self.db()
        self.assertEqual(db.query(Session).filter_by(aide_role="primary").count(), 1)
        self.assertIsNotNone(db.get(Session, old["id"]))
        db.close()

    def test_primary_conversation_cannot_be_archived_or_deleted(self):
        primary = self.client.get("/api/aide/conversation").json()
        archived = self.client.post(f"/api/sessions/{primary['id']}/archive")
        deleted = self.client.delete(f"/api/sessions/{primary['id']}")

        self.assertEqual(archived.status_code, 409)
        self.assertEqual(deleted.status_code, 409)
        self.assertEqual(archived.json()["code"], "primary_aide_session_protected")
        self.assertEqual(deleted.json()["code"], "primary_aide_session_protected")

    def test_empty_session_cleanup_keeps_primary_but_removes_abandoned_chat(self):
        primary = self.client.get("/api/aide/conversation").json()
        abandoned = self.client.post("/api/sessions", json={}).json()

        _cleanup_empty_sessions()

        db = self.db()
        self.assertIsNotNone(db.get(Session, primary["id"]))
        self.assertIsNone(db.get(Session, abandoned["id"]))
        self.assertEqual(db.query(Message).filter_by(session_id=primary["id"]).count(), 0)
        db.close()


class AidePrimaryMigrationTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.engine = create_engine(f"sqlite:///{self.path}")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE sessions ("
                    "id TEXT PRIMARY KEY, name TEXT, archived BOOLEAN NOT NULL DEFAULT 0)"
                )
            )
            conn.execute(text("INSERT INTO sessions(id,name) VALUES ('legacy','legacy task')"))

    def tearDown(self):
        self.engine.dispose()
        os.remove(self.path)

    def test_up_is_idempotent_and_down_preserves_identity_data(self):
        with self.engine.begin() as conn:
            m0068_aide_primary_session.up(conn)
            m0068_aide_primary_session.up(conn)
            conn.execute(
                text("INSERT INTO sessions(id,name,aide_role) VALUES ('primary','Aide','primary')")
            )

        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sessions(id,name,aide_role) VALUES ('other','Other','primary')")
            )

        with self.engine.begin() as conn:
            m0068_aide_primary_session.down(conn)

        with self.engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))}
            indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(sessions)"))}
            role = conn.execute(
                text("SELECT aide_role FROM sessions WHERE id = 'primary'")
            ).scalar_one()
            conn.execute(
                text("INSERT INTO sessions(id,name,aide_role) VALUES ('other','Other','primary')")
            )

        self.assertIn("aide_role", columns)
        self.assertNotIn("ux_sessions_aide_primary", indexes)
        self.assertEqual(role, "primary")
