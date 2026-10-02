"""Concurrent rule runs preserve metadata and queue one automatic reply per message."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, CachedMessage, MailAccount, ScheduledMail
from services import mail_rules


class RuleConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alles-rule-race-")
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "owned.db"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        with self.Session() as db:
            db.add(
                MailAccount(
                    id="owned", email="self@example.invalid", username="self@example.invalid"
                )
            )
            db.add(
                CachedMessage(
                    id="message",
                    account_id="owned",
                    folder="INBOX",
                    uid="1",
                    sender="sender@example.invalid",
                    subject="hello",
                    autoreplied=False,
                    labels="base",
                )
            )
            db.commit()

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def rule(self, action, arg=""):
        return {
            "match_field": "from",
            "match_value": "sender",
            "action": action,
            "action_arg": arg,
            "enabled": True,
        }

    def overlap(self, first_rules, second_rules):
        ready = threading.Event()
        release = threading.Event()
        second_done = threading.Event()
        owner = {"id": None}
        original = mail_rules.apply_rules

        def apply(msg, rules):
            if threading.get_ident() == owner["id"] and not ready.is_set():
                ready.set()
                assert release.wait(5)
            return original(msg, rules)

        def first():
            owner["id"] = threading.get_ident()
            with self.Session() as db:
                return mail_rules.run_on_cache(db, "owned", first_rules)

        def second():
            try:
                with self.Session() as db:
                    return mail_rules.run_on_cache(db, "owned", second_rules)
            finally:
                second_done.set()

        with mock.patch.object(mail_rules, "apply_rules", side_effect=apply):
            with ThreadPoolExecutor(max_workers=2) as pool:
                one = pool.submit(first)
                try:
                    self.assertTrue(ready.wait(5))
                    two = pool.submit(second)
                    second_done.wait(0.25)
                finally:
                    release.set()
                return one.result(5), two.result(5)

    def test_overlapping_runs_enqueue_one_reply(self):
        rules = [self.rule("autoreply", "owned test reply")]
        counts = self.overlap(rules, rules)
        with self.Session() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 1)
            self.assertTrue(db.get(CachedMessage, "message").autoreplied)
        self.assertEqual(sum(counts), 1)

    def test_overlapping_labels_preserve_both_additions(self):
        counts = self.overlap([self.rule("label", "first")], [self.rule("label", "second")])
        with self.Session() as db:
            self.assertEqual(
                set(db.get(CachedMessage, "message").labels.split(",")), {"base", "first", "second"}
            )
        self.assertEqual(counts, (1, 1))

    def test_preloaded_session_reads_new_guards_and_labels(self):
        with self.Session() as stale:
            message = stale.get(CachedMessage, "message")
            self.assertFalse(message.autoreplied)
            with self.Session() as other:
                self.assertEqual(
                    mail_rules.run_on_cache(
                        other,
                        "owned",
                        [self.rule("autoreply", "owned reply"), self.rule("label", "second")],
                    ),
                    2,
                )
            count = mail_rules.run_on_cache(
                stale, "owned", [self.rule("autoreply", "owned reply"), self.rule("label", "first")]
            )
            self.assertEqual(count, 1)
        with self.Session() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 1)
            self.assertEqual(
                set(db.get(CachedMessage, "message").labels.split(",")), {"base", "first", "second"}
            )

    def test_failed_commit_does_not_leave_queue_or_guard(self):
        rules = [self.rule("autoreply", "owned reply")]
        with self.assertRaisesRegex(RuntimeError, "owned commit failure"):
            with self.Session() as db:
                with mock.patch.object(
                    db, "commit", side_effect=RuntimeError("owned commit failure")
                ):
                    mail_rules.run_on_cache(db, "owned", rules)
        with self.Session() as db:
            self.assertEqual(db.query(ScheduledMail).count(), 0)
            self.assertFalse(db.get(CachedMessage, "message").autoreplied)
            self.assertEqual(mail_rules.run_on_cache(db, "owned", rules), 1)
            self.assertEqual(db.query(ScheduledMail).count(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
