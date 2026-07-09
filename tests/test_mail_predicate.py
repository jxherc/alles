"""stage 2j - boolean smart-mailbox predicate language. tests first (RED)."""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import mail_predicate as mp


def _msg(
    sender="bob@acme.com",
    subject="lunch?",
    labels=None,
    seen=False,
    flagged=False,
    muted=False,
    to="",
):
    return {
        "from": sender,
        "to": to,
        "subject": subject,
        "labels": labels or [],
        "seen": seen,
        "flagged": flagged,
        "muted": muted,
    }


def _matches(q, msg):
    return msg in mp.match(q, [msg])


class TermTests(unittest.TestCase):
    def test_from_term(self):
        self.assertTrue(_matches("from:bob", _msg(sender="bob@acme.com")))
        self.assertFalse(_matches("from:bob", _msg(sender="alice@x.com")))

    def test_subject_term(self):
        self.assertTrue(_matches("subject:lunch", _msg(subject="Re: lunch?")))

    def test_bare_word_is_text(self):
        self.assertTrue(_matches("acme", _msg(sender="bob@acme.com")))
        self.assertTrue(_matches("lunch", _msg(subject="lunch?")))

    def test_to_does_not_match_sender(self):
        # 'to:' is a recipient filter; it must NOT match a message FROM that address
        m = _msg(sender="alice@x.com", subject="hi")
        m["to"] = ""
        self.assertFalse(_matches("to:alice", m))

    def test_to_matches_recipient(self):
        m = _msg(sender="news@x.com", to="Me <me@x.com>, billing@example.com")
        self.assertTrue(_matches("to:billing", m))
        self.assertFalse(_matches("to:news", m))

    def test_label_term(self):
        self.assertTrue(_matches("label:work", _msg(labels=["work", "x"])))
        self.assertFalse(_matches("label:work", _msg(labels=["home"])))

    def test_is_unread_read_flagged(self):
        self.assertTrue(_matches("is:unread", _msg(seen=False)))
        self.assertFalse(_matches("is:unread", _msg(seen=True)))
        self.assertTrue(_matches("is:read", _msg(seen=True)))
        self.assertTrue(_matches("is:flagged", _msg(flagged=True)))

    def test_quoted_value(self):
        self.assertTrue(_matches('subject:"team lunch"', _msg(subject="our TEAM LUNCH today")))
        self.assertFalse(_matches('subject:"team lunch"', _msg(subject="team meeting")))

    def test_quoted_phrase_not_split_into_terms(self):
        # field:"a b" must match the PHRASE in that field, not (field:a AND text:b).
        # used to tokenize as subject:"team + lunch" -> wrong, broader results.
        self.assertTrue(_matches('subject:"team lunch"', _msg(subject="our weekly team lunch")))
        # reversed words: phrase absent -> must NOT match (the split bug matched this)
        self.assertFalse(_matches('subject:"team lunch"', _msg(subject="lunch with the team")))


class BooleanTests(unittest.TestCase):
    def test_implicit_and(self):
        q = "from:bob subject:lunch"
        self.assertTrue(_matches(q, _msg(sender="bob@x", subject="lunch")))
        self.assertFalse(_matches(q, _msg(sender="bob@x", subject="dinner")))

    def test_explicit_and(self):
        self.assertTrue(_matches("from:bob AND is:unread", _msg(sender="bob@x", seen=False)))
        self.assertFalse(_matches("from:bob AND is:unread", _msg(sender="bob@x", seen=True)))

    def test_or(self):
        q = "from:bob OR from:alice"
        self.assertTrue(_matches(q, _msg(sender="alice@x")))
        self.assertTrue(_matches(q, _msg(sender="bob@x")))
        self.assertFalse(_matches(q, _msg(sender="carol@x")))

    def test_not(self):
        self.assertTrue(_matches("NOT label:spam", _msg(labels=["work"])))
        self.assertFalse(_matches("NOT label:spam", _msg(labels=["spam"])))

    def test_grouping_precedence(self):
        q = "(from:bob OR from:alice) AND NOT label:spam"
        self.assertTrue(_matches(q, _msg(sender="alice@x", labels=["work"])))
        self.assertFalse(_matches(q, _msg(sender="alice@x", labels=["spam"])))
        self.assertFalse(_matches(q, _msg(sender="carol@x", labels=["work"])))

    def test_or_binds_looser_than_and(self):
        # from:bob AND subject:x OR from:alice  ==  (from:bob AND subject:x) OR from:alice
        q = "from:bob subject:x OR from:alice"
        self.assertTrue(_matches(q, _msg(sender="alice@x", subject="zzz")))
        self.assertTrue(_matches(q, _msg(sender="bob@x", subject="xylophone")))
        self.assertFalse(_matches(q, _msg(sender="bob@x", subject="zzz")))

    def test_case_insensitive_operators(self):
        self.assertTrue(_matches("from:bob or from:alice", _msg(sender="alice@x")))
        self.assertTrue(_matches("not label:spam", _msg(labels=["work"])))


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
        self.assertTrue(_matches("label:urgent", m))


class PathologicalInputTests(unittest.TestCase):
    """deep nesting / huge queries must not RecursionError into a 500 (DoS)."""

    def test_deep_parens_no_crash(self):
        q = "(" * 5000 + "a" + ")" * 5000
        # must return a bool (treating the pathological query as no-match), never raise
        self.assertIsInstance(_matches(q, _msg(sender="a@x")), bool)

    def test_long_not_chain_no_crash(self):
        q = "NOT " * 2000 + "a"
        self.assertIsInstance(_matches(q, _msg()), bool)

    def test_long_and_chain_no_crash(self):
        q = " AND ".join(["from:x"] * 3000)
        self.assertIsInstance(_matches(q, _msg(sender="x@y")), bool)

    def test_unbalanced_parens_no_crash(self):
        self.assertIsInstance(_matches("(" * 10000, _msg()), bool)

    def test_match_list_pathological(self):
        # match() over a list must also stay safe
        self.assertIsInstance(mp.match("(" * 5000, [_msg(), _msg()]), list)


if __name__ == "__main__":
    unittest.main()
