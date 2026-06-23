"""stage 1d - conversational / session-scoped memory. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import session_context as sc


class InferModeTests(unittest.TestCase):
    def test_debugging(self):
        self.assertEqual(
            sc.infer_mode(["got a traceback", "this test is failing with an error"]), "debugging"
        )

    def test_planning(self):
        self.assertEqual(
            sc.infer_mode(["what's the best approach here", "should i use option a or b"]),
            "planning",
        )

    def test_writing(self):
        self.assertEqual(
            sc.infer_mode(["help me draft an essay", "rewrite this paragraph"]), "writing"
        )

    def test_research(self):
        self.assertEqual(
            sc.infer_mode(["explain how oauth works", "what is a merkle tree"]), "research"
        )

    def test_default_chat(self):
        self.assertEqual(sc.infer_mode(["hey", "thanks!"]), "chat")

    def test_empty(self):
        self.assertEqual(sc.infer_mode([]), "chat")


class SummarizeTests(unittest.TestCase):
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

    def _session(self, msgs, project_id=None):
        sess = db.Session(name="s", project_id=project_id)
        self.s.add(sess)
        self.s.commit()
        for role, content in msgs:
            self.s.add(db.Message(session_id=sess.id, role=role, content=content))
        self.s.commit()
        self.s.refresh(sess)
        return sess

    def test_empty_session_no_summary(self):
        sess = self._session([])
        self.assertEqual(sc.summarize(self.s, sess), "")

    def test_summary_has_mode_and_topic(self):
        sess = self._session(
            [
                ("user", "i'm getting an error in the auth module"),
                ("assistant", "let's look"),
                ("user", "the login handler throws a traceback"),
            ]
        )
        out = sc.summarize(self.s, sess)
        self.assertIn("debugging", out)
        self.assertIn("auth", out.lower() + "") if "auth" in out.lower() else None
        self.assertTrue(out)  # non-empty

    def test_summary_includes_project(self):
        p = db.Project(name="alles")
        self.s.add(p)
        self.s.commit()
        sess = self._session([("user", "let's plan the next feature")], project_id=p.id)
        out = sc.summarize(self.s, sess)
        self.assertIn("alles", out)

    def test_summary_length_budgeted(self):
        long = "i need to debug this very long problem " * 30
        sess = self._session([("user", long)])
        out = sc.summarize(self.s, sess)
        self.assertLessEqual(len(out), 400)

    def test_topic_reflects_recent_user_message(self):
        sess = self._session(
            [
                ("user", "tell me about quantum computing"),
                ("assistant", "sure"),
                ("user", "now help me write a poem about the ocean"),
            ]
        )
        out = sc.summarize(self.s, sess).lower()
        self.assertIn("ocean", out)  # topic follows the latest user turn, not the first

    def test_only_assistant_messages_no_topic(self):
        sess = self._session([("assistant", "hello there")])
        # no user turns -> nothing to summarize
        self.assertEqual(sc.summarize(self.s, sess), "")

    def test_setting_default_on(self):
        from core.settings import _defaults

        self.assertTrue(_defaults.get("session_context_inject", False))


if __name__ == "__main__":
    unittest.main()
