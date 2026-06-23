"""stage 2j - boolean smart-mailbox predicate language. tests first (RED)."""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import mail_predicate as mp


def _msg(
    sender="bob@acme.com", subject="lunch?", labels=None, seen=False, flagged=False, muted=False
):
    return {
        "from": sender,
        "subject": subject,
        "labels": labels or [],
        "seen": seen,
        "flagged": flagged,
        "muted": muted,
    }


class TermTests(unittest.TestCase):
    def test_from_term(self):
        self.assertTrue(mp.match_one("from:bob", _msg(sender="bob@acme.com")))
        self.assertFalse(mp.match_one("from:bob", _msg(sender="alice@x.com")))

    def test_subject_term(self):
        self.assertTrue(mp.match_one("subject:lunch", _msg(subject="Re: lunch?")))

    def test_bare_word_is_text(self):
        self.assertTrue(mp.match_one("acme", _msg(sender="bob@acme.com")))
        self.assertTrue(mp.match_one("lunch", _msg(subject="lunch?")))

    def test_label_term(self):
        self.assertTrue(mp.match_one("label:work", _msg(labels=["work", "x"])))
        self.assertFalse(mp.match_one("label:work", _msg(labels=["home"])))

    def test_is_unread_read_flagged(self):
        self.assertTrue(mp.match_one("is:unread", _msg(seen=False)))
        self.assertFalse(mp.match_one("is:unread", _msg(seen=True)))
        self.assertTrue(mp.match_one("is:read", _msg(seen=True)))
        self.assertTrue(mp.match_one("is:flagged", _msg(flagged=True)))

    def test_quoted_value(self):
        self.assertTrue(mp.match_one('subject:"team lunch"', _msg(subject="our TEAM LUNCH today")))
        self.assertFalse(mp.match_one('subject:"team lunch"', _msg(subject="team meeting")))


class BooleanTests(unittest.TestCase):
    def test_implicit_and(self):
        q = "from:bob subject:lunch"
        self.assertTrue(mp.match_one(q, _msg(sender="bob@x", subject="lunch")))
        self.assertFalse(mp.match_one(q, _msg(sender="bob@x", subject="dinner")))

    def test_explicit_and(self):
        self.assertTrue(mp.match_one("from:bob AND is:unread", _msg(sender="bob@x", seen=False)))
        self.assertFalse(mp.match_one("from:bob AND is:unread", _msg(sender="bob@x", seen=True)))

    def test_or(self):
        q = "from:bob OR from:alice"
        self.assertTrue(mp.match_one(q, _msg(sender="alice@x")))
        self.assertTrue(mp.match_one(q, _msg(sender="bob@x")))
        self.assertFalse(mp.match_one(q, _msg(sender="carol@x")))

    def test_not(self):
        self.assertTrue(mp.match_one("NOT label:spam", _msg(labels=["work"])))
        self.assertFalse(mp.match_one("NOT label:spam", _msg(labels=["spam"])))

    def test_grouping_precedence(self):
        q = "(from:bob OR from:alice) AND NOT label:spam"
        self.assertTrue(mp.match_one(q, _msg(sender="alice@x", labels=["work"])))
        self.assertFalse(mp.match_one(q, _msg(sender="alice@x", labels=["spam"])))
        self.assertFalse(mp.match_one(q, _msg(sender="carol@x", labels=["work"])))

    def test_or_binds_looser_than_and(self):
        # from:bob AND subject:x OR from:alice  ==  (from:bob AND subject:x) OR from:alice
        q = "from:bob subject:x OR from:alice"
        self.assertTrue(mp.match_one(q, _msg(sender="alice@x", subject="zzz")))
        self.assertTrue(mp.match_one(q, _msg(sender="bob@x", subject="xylophone")))
        self.assertFalse(mp.match_one(q, _msg(sender="bob@x", subject="zzz")))

    def test_case_insensitive_operators(self):
        self.assertTrue(mp.match_one("from:bob or from:alice", _msg(sender="alice@x")))
        self.assertTrue(mp.match_one("not label:spam", _msg(labels=["work"])))


class MatchTests(unittest.TestCase):
    def test_empty_matches_all(self):
        msgs = [_msg(), _msg(sender="z@z")]
        self.assertEqual(len(mp.match("", msgs)), 2)

    def test_match_filters_list(self):
        msgs = [_msg(sender="bob@x"), _msg(sender="alice@x"), _msg(sender="carol@x")]
        out = mp.match("from:bob OR from:alice", msgs)
        self.assertEqual({m["from"] for m in out}, {"bob@x", "alice@x"})

    def test_labels_as_csv_string(self):
        m = {"from": "x", "subject": "", "labels": "work,urgent", "seen": False}
        self.assertTrue(mp.match_one("label:urgent", m))


if __name__ == "__main__":
    unittest.main()
