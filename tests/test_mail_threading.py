"""stage 2i - RFC-5322 reference-graph threading. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import mail as mailsvc
from services import mail_cache


def _m(uid, mid, subject, in_reply_to="", references=""):
    return {
        "uid": uid,
        "message_id": mid,
        "subject": subject,
        "in_reply_to": in_reply_to,
        "references": references,
        "from": "x@y.com",
        "date_ts": float(uid),
    }


class ThreadFnTests(unittest.TestCase):
    def _tids(self, msgs):
        return {m["uid"]: m["thread_id"] for m in mailsvc.thread_messages(msgs)}

    def test_reply_chain_threads(self):
        msgs = [
            _m("1", "<a@x>", "Lunch?"),
            _m("2", "<b@x>", "Re: Lunch?", in_reply_to="<a@x>", references="<a@x>"),
        ]
        t = self._tids(msgs)
        self.assertEqual(t["1"], t["2"])

    def test_threads_despite_subject_change(self):
        msgs = [
            _m("1", "<a@x>", "Lunch?"),
            _m("2", "<b@x>", "Re: Lunch?", references="<a@x>"),
            _m("3", "<c@x>", "Fwd: totally different", references="<a@x> <b@x>"),
        ]
        t = self._tids(msgs)
        self.assertEqual(len({t["1"], t["2"], t["3"]}), 1)  # all one thread

    def test_unrelated_split(self):
        msgs = [_m("1", "<a@x>", "hi"), _m("2", "<b@x>", "hi")]  # same subject, no refs
        t = self._tids(msgs)
        self.assertNotEqual(t["1"], t["2"])

    def test_headerless_fallback_singleton(self):
        msgs = [_m("1", "", "no headers"), _m("2", "", "also none")]
        t = self._tids(msgs)
        self.assertNotEqual(t["1"], t["2"])  # each its own thread via uid

    def test_references_only_threads(self):
        msgs = [
            _m("1", "<a@x>", "start"),
            _m("2", "<b@x>", "reply", references="<a@x>"),  # no in_reply_to
        ]
        t = self._tids(msgs)
        self.assertEqual(t["1"], t["2"])

    def test_order_independent(self):
        a = [_m("1", "<a@x>", "s"), _m("2", "<b@x>", "r", references="<a@x>")]
        b = [_m("2", "<b@x>", "r", references="<a@x>"), _m("1", "<a@x>", "s")]
        ta = {m["uid"]: m["thread_id"] for m in mailsvc.thread_messages(a)}
        tb = {m["uid"]: m["thread_id"] for m in mailsvc.thread_messages(b)}
        self.assertEqual(ta["1"], tb["1"])
        self.assertEqual(ta["1"], ta["2"])

    def test_reply_to_missing_ancestor_still_groups_siblings(self):
        # neither replies to a msg we have, but both cite the same missing root
        msgs = [
            _m("1", "<b@x>", "re", references="<missing@x>"),
            _m("2", "<c@x>", "re", references="<missing@x>"),
        ]
        t = self._tids(msgs)
        self.assertEqual(t["1"], t["2"])

    def test_empty(self):
        self.assertEqual(mailsvc.thread_messages([]), [])


class CachePersistTests(unittest.TestCase):
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

    def test_save_persists_headers_and_thread(self):
        msgs = [
            _m("1", "<a@x>", "Lunch?"),
            _m("2", "<b@x>", "Re: changed", references="<a@x>"),
        ]
        mail_cache.save(self.s, "A1", "INBOX", msgs)
        rows = {r.uid: r for r in self.s.query(db.CachedMessage).all()}
        self.assertEqual(rows["1"].message_id, "<a@x>")
        self.assertEqual(rows["2"].references, "<a@x>")
        self.assertTrue(rows["1"].thread_id)
        self.assertEqual(rows["1"].thread_id, rows["2"].thread_id)


if __name__ == "__main__":
    unittest.main()
