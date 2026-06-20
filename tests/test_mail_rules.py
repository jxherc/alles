from core.database import CachedMessage, MailAccount
from services import mail_rules
from tests._client import ApiTest


class ApplyRulesTests(ApiTest):
    def test_apply_rules_from_match(self):
        rules = [
            {"match_field": "from", "match_value": "boss", "action": "markread", "enabled": True}
        ]
        acts = mail_rules.apply_rules({"from": "The Boss <boss@x.com>", "subject": "hi"}, rules)
        self.assertEqual(acts, [{"action": "markread", "action_arg": ""}])

    def test_apply_rules_subject_match(self):
        rules = [
            {"match_field": "subject", "match_value": "invoice", "action": "mute", "enabled": True}
        ]
        acts = mail_rules.apply_rules({"from": "a@x.com", "subject": "June Invoice"}, rules)
        self.assertEqual(acts[0]["action"], "mute")

    def test_apply_rules_no_match(self):
        rules = [
            {"match_field": "from", "match_value": "boss", "action": "markread", "enabled": True}
        ]
        self.assertEqual(mail_rules.apply_rules({"from": "a@x.com", "subject": "hi"}, rules), [])

    def test_apply_rules_disabled_skipped(self):
        rules = [
            {"match_field": "from", "match_value": "a", "action": "markread", "enabled": False}
        ]
        self.assertEqual(mail_rules.apply_rules({"from": "a@x.com", "subject": "x"}, rules), [])

    def test_vacation_first_reply(self):
        reply, st = mail_rules.vacation_reply_for(
            "bob@x.com", {"enabled": True, "subject": "OOO", "body": "away"}, {}, "2026-06-19"
        )
        self.assertEqual(reply["to"], "bob@x.com")
        self.assertEqual(st["bob@x.com"], "2026-06-19")

    def test_vacation_skips_same_sender_day(self):
        vac = {"enabled": True, "subject": "OOO", "body": "away"}
        _, st = mail_rules.vacation_reply_for("bob@x.com", vac, {}, "2026-06-19")
        reply2, _ = mail_rules.vacation_reply_for("bob@x.com", vac, st, "2026-06-19")
        self.assertIsNone(reply2)

    def test_vacation_disabled_none(self):
        reply, _ = mail_rules.vacation_reply_for("bob@x.com", {"enabled": False}, {}, "2026-06-19")
        self.assertIsNone(reply)


class RuleApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = MailAccount(
            name="Me", email="me@x.com", imap_host="i", smtp_host="s", username="me", password="p"
        )
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _cached(self, uid, sender, subject):
        db = self.db()
        db.add(
            CachedMessage(
                account_id=self.aid,
                folder="INBOX",
                uid=str(uid),
                sender=sender,
                subject=subject,
                date="2026-06-10",
                date_ts=1,
                seen=False,
            )
        )
        db.commit()
        db.close()

    def test_rule_crud(self):
        r = self.client.post(
            "/api/mail/rules",
            json={"match_field": "from", "match_value": "boss", "action": "markread"},
        ).json()
        self.assertTrue(
            any(x["id"] == r["id"] for x in self.client.get("/api/mail/rules").json()["rules"])
        )
        self.client.delete(f"/api/mail/rules/{r['id']}")
        self.assertFalse(self.client.get("/api/mail/rules").json()["rules"])

    def test_run_marks_read(self):
        self._cached(1, "Boss <boss@x.com>", "hi")
        self.client.post(
            "/api/mail/rules",
            json={"match_field": "from", "match_value": "boss", "action": "markread"},
        )
        self.client.post(f"/api/mail/rules/run/{self.aid}")
        db = self.db()
        self.assertTrue(db.query(CachedMessage).filter_by(uid="1").first().seen)
        db.close()

    def test_run_mutes(self):
        self._cached(1, "a@x.com", "Spam Promo")
        self.client.post(
            "/api/mail/rules",
            json={"match_field": "subject", "match_value": "promo", "action": "mute"},
        )
        self.client.post(f"/api/mail/rules/run/{self.aid}")
        db = self.db()
        self.assertTrue(db.query(CachedMessage).filter_by(uid="1").first().muted)
        db.close()

    def test_smart_reply_disabled_no_endpoint(self):
        d = self.client.post("/api/mail/smart-reply", json={"text": "Can we meet tomorrow?"}).json()
        self.assertFalse(d["enabled"])
        self.assertEqual(d["suggestions"], [])
