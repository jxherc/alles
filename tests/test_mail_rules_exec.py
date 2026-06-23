"""stage 2g - mail rule label + autoreply execution + vacation send. tests first (RED)."""

import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import mail_rules


class _Base(unittest.TestCase):
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

    def _msg(self, sender="boss@acme.com", subject="hi", uid="1", **kw):
        m = db.CachedMessage(
            account_id="A1", folder="INBOX", uid=uid, sender=sender, subject=subject, **kw
        )
        self.s.add(m)
        self.s.commit()
        return m

    def _scheduled(self):
        return self.s.query(db.ScheduledMail).all()


class LabelTests(_Base):
    def test_label_applied(self):
        m = self._msg()
        rules = [
            {"match_field": "from", "match_value": "acme", "action": "label", "action_arg": "work"}
        ]
        n = mail_rules.run_on_cache(self.s, "A1", rules)
        self.s.refresh(m)
        self.assertEqual(n, 1)
        self.assertIn("work", m.labels.split(","))

    def test_label_idempotent(self):
        m = self._msg(labels="work")
        rules = [
            {"match_field": "from", "match_value": "acme", "action": "label", "action_arg": "work"}
        ]
        n = mail_rules.run_on_cache(self.s, "A1", rules)
        self.s.refresh(m)
        self.assertEqual(n, 0)  # already labeled
        self.assertEqual(m.labels, "work")

    def test_label_dedups_and_appends(self):
        m = self._msg(labels="personal")
        rules = [
            {"match_field": "from", "match_value": "acme", "action": "label", "action_arg": "work"}
        ]
        mail_rules.run_on_cache(self.s, "A1", rules)
        self.s.refresh(m)
        self.assertEqual(set(m.labels.split(",")), {"personal", "work"})


class AutoreplyTests(_Base):
    def test_autoreply_enqueues(self):
        m = self._msg(subject="need help")
        rules = [
            {
                "match_field": "from",
                "match_value": "acme",
                "action": "autoreply",
                "action_arg": "got it, will reply soon",
            }
        ]
        n = mail_rules.run_on_cache(self.s, "A1", rules)
        self.s.refresh(m)
        sched = self._scheduled()
        self.assertEqual(n, 1)
        self.assertEqual(len(sched), 1)
        self.assertEqual(sched[0].to, "boss@acme.com")
        self.assertEqual(sched[0].body, "got it, will reply soon")
        self.assertTrue(m.autoreplied)

    def test_autoreply_not_duplicated_on_rerun(self):
        self._msg()
        rules = [
            {
                "match_field": "from",
                "match_value": "acme",
                "action": "autoreply",
                "action_arg": "ok",
            }
        ]
        mail_rules.run_on_cache(self.s, "A1", rules)
        n2 = mail_rules.run_on_cache(self.s, "A1", rules)  # re-run
        self.assertEqual(n2, 0)
        self.assertEqual(len(self._scheduled()), 1)

    def test_autoreply_subject_is_reply(self):
        self._msg(subject="invoice")
        rules = [
            {
                "match_field": "from",
                "match_value": "acme",
                "action": "autoreply",
                "action_arg": "thanks",
            }
        ]
        mail_rules.run_on_cache(self.s, "A1", rules)
        self.assertTrue(self._scheduled()[0].subject.lower().startswith("re:"))


class VacationTests(_Base):
    VAC = {"enabled": True, "subject": "Away", "body": "I am out until Monday"}

    def test_vacation_enqueues_one_per_sender(self):
        self._msg(sender="a@x.com", uid="1")
        self._msg(sender="a@x.com", uid="2")  # same sender, same day
        n, state = mail_rules.run_vacation(self.s, "A1", self.VAC, {}, "2026-06-23")
        self.assertEqual(n, 1)
        self.assertEqual(len(self._scheduled()), 1)
        self.assertEqual(state.get("a@x.com"), "2026-06-23")

    def test_vacation_different_senders(self):
        self._msg(sender="a@x.com", uid="1")
        self._msg(sender="b@y.com", uid="2")
        n, _ = mail_rules.run_vacation(self.s, "A1", self.VAC, {}, "2026-06-23")
        self.assertEqual(n, 2)

    def test_vacation_disabled_noop(self):
        self._msg(sender="a@x.com")
        n, _ = mail_rules.run_vacation(self.s, "A1", {"enabled": False}, {}, "2026-06-23")
        self.assertEqual(n, 0)
        self.assertEqual(len(self._scheduled()), 0)

    def test_vacation_respects_prior_state(self):
        self._msg(sender="a@x.com")
        n, _ = mail_rules.run_vacation(
            self.s, "A1", self.VAC, {"a@x.com": "2026-06-23"}, "2026-06-23"
        )
        self.assertEqual(n, 0)  # already replied today

    def test_vacation_reply_content(self):
        self._msg(sender="a@x.com")
        mail_rules.run_vacation(self.s, "A1", self.VAC, {}, "2026-06-23")
        sched = self._scheduled()[0]
        self.assertEqual(sched.to, "a@x.com")
        self.assertEqual(sched.subject, "Away")
        self.assertEqual(sched.body, "I am out until Monday")


if __name__ == "__main__":
    unittest.main()
