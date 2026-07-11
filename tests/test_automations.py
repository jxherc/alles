import asyncio
import json
import unittest
from unittest import mock

from core.database import AutomationAttempt, AutomationRule, MailAccount, Task
from services import automations
from services.automations import _render, _trim
from tests._client import ApiTest, VaultApiTest


class RuleEditTests(ApiTest):
    def test_patch_can_change_trigger_action(self):
        r = self.client.post(
            "/api/automations",
            json={
                "trigger": "daily_at",
                "trigger_arg": "08:00",
                "action": "push",
                "action_arg": "morning",
            },
        )
        self.assertEqual(r.status_code, 200)
        rid = r.json()["id"]
        # full edit: change the trigger + action types, not just args
        p = self.client.patch(
            f"/api/automations/{rid}",
            json={
                "trigger": "mail_from",
                "trigger_arg": "boss@",
                "action": "create_task",
                "action_arg": "{subject}",
            },
        )
        self.assertEqual(p.status_code, 200)
        d = p.json()
        self.assertEqual(
            (d["trigger"], d["trigger_arg"], d["action"]), ("mail_from", "boss@", "create_task")
        )
        # bad trigger rejected
        self.assertEqual(
            self.client.patch(f"/api/automations/{rid}", json={"trigger": "nope"}).status_code, 400
        )

    def test_create_list_delete(self):
        self.client.post(
            "/api/automations",
            json={"trigger": "doc_tag", "trigger_arg": "invoice", "action": "create_note"},
        )
        lst = self.client.get("/api/automations").json()
        self.assertEqual(len(lst), 1)
        rid = lst[0]["id"]
        self.assertEqual(self.client.delete(f"/api/automations/{rid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/automations").json(), [])

    def test_create_rejects_bad_trigger(self):
        r = self.client.post("/api/automations", json={"trigger": "bogus", "action": "push"})
        self.assertEqual(r.status_code, 400)

    def test_create_rejects_bad_action(self):
        r = self.client.post(
            "/api/automations",
            json={"trigger": "doc_tag", "trigger_arg": "x", "action": "fly_to_moon"},
        )
        self.assertEqual(r.status_code, 400)

    def test_daily_at_validates_time_format(self):
        bad = self.client.post(
            "/api/automations",
            json={"trigger": "daily_at", "trigger_arg": "8am", "action": "push"},
        )
        self.assertEqual(bad.status_code, 400)
        good = self.client.post(
            "/api/automations",
            json={"trigger": "daily_at", "trigger_arg": "08:30", "action": "push"},
        )
        self.assertEqual(good.status_code, 200)

    def test_daily_at_rejects_out_of_range(self):
        # "25:99" matches \d{2}:\d{2} but no clock reaches it, so the rule would silently never fire
        for t in ("25:99", "24:00", "08:60", "99:99"):
            r = self.client.post(
                "/api/automations",
                json={"trigger": "daily_at", "trigger_arg": t, "action": "push"},
            )
            self.assertEqual(r.status_code, 400, t)

    def test_patch_validates_daily_at_time(self):
        rid = self.client.post(
            "/api/automations",
            json={"trigger": "daily_at", "trigger_arg": "08:00", "action": "push"},
        ).json()["id"]
        # patching to a bogus time must be rejected, not silently stored
        bad = self.client.patch(f"/api/automations/{rid}", json={"trigger_arg": "25:00"})
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch(f"/api/automations/{rid}", json={"trigger_arg": "09:15"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["trigger_arg"], "09:15")

    def test_patch_enabled_toggle(self):
        rid = self.client.post(
            "/api/automations",
            json={"trigger": "doc_tag", "trigger_arg": "t", "action": "push"},
        ).json()["id"]
        d = self.client.patch(f"/api/automations/{rid}", json={"enabled": False}).json()
        self.assertFalse(d["enabled"])
        d = self.client.patch(f"/api/automations/{rid}", json={"enabled": True}).json()
        self.assertTrue(d["enabled"])

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/automations/nope").status_code, 404)

    def test_options_returns_triggers_and_actions(self):
        d = self.client.get("/api/automations/options").json()
        triggers = {t["value"] for t in d["triggers"]}
        actions = {a["value"] for a in d["actions"]}
        self.assertIn("daily_at", triggers)
        self.assertIn("mail_from", triggers)
        self.assertIn("push", actions)
        self.assertIn("create_task", actions)

    def test_every_wired_trigger_is_in_the_dropdown(self):
        # a trigger that's wired but missing from options is unreachable from the UI
        from services.automations import TRIGGERS

        exposed = {
            t["value"] for t in self.client.get("/api/automations/options").json()["triggers"]
        }
        self.assertEqual(set(TRIGGERS), exposed)

    def test_patch_action_arg_only(self):
        # patching just the arg leaves everything else alone
        rid = self.client.post(
            "/api/automations",
            json={
                "trigger": "sub_renewing",
                "trigger_arg": "3",
                "action": "push",
                "action_arg": "orig",
            },
        ).json()["id"]
        d = self.client.patch(f"/api/automations/{rid}", json={"action_arg": "updated"}).json()
        self.assertEqual(d["action_arg"], "updated")
        self.assertEqual(d["trigger"], "sub_renewing")


class RenderTests(unittest.TestCase):
    def test_substitutes_known(self):
        self.assertEqual(
            _render("{name} renews in {days}", {"name": "Netflix", "days": 3}),
            "Netflix renews in 3",
        )

    def test_unknown_placeholder_left_as_is(self):
        self.assertEqual(_render("hi {who}", {"name": "x"}), "hi {who}")

    def test_empty_template(self):
        self.assertEqual(_render("", {"name": "x"}), "")

    def test_no_placeholders(self):
        self.assertEqual(_render("just text", {}), "just text")


class TrimTests(unittest.TestCase):
    def test_trim_keeps_recent(self):
        d = {str(i): i for i in range(300)}
        out = _trim(d, keep=200)
        self.assertEqual(len(out), 200)
        self.assertIn("299", out)
        self.assertNotIn("0", out)

    def test_trim_noop_when_small(self):
        d = {"a": 1, "b": 2}
        self.assertIs(_trim(d, keep=200), d)


class AutomationSafetyTests(ApiTest):
    def _rule(self, *, action="create_task", action_arg="task"):
        db = self.db()
        rule = AutomationRule(
            name="safe rule",
            trigger="daily_at",
            trigger_arg="00:00",
            action=action,
            action_arg=action_arg,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return db, rule

    def test_one_occurrence_runs_only_once(self):
        db, rule = self._rule(action_arg="only once")
        first = asyncio.run(automations._fire(db, rule, {"dedupe": "same occurrence"}))
        second = asyncio.run(automations._fire(db, rule, {"dedupe": "same occurrence"}))

        self.assertEqual(first["status"], "succeeded")
        self.assertTrue(first["executed"])
        self.assertEqual(second["status"], "succeeded")
        self.assertFalse(second["executed"])
        self.assertEqual(db.query(Task).filter_by(title="only once").count(), 1)
        self.assertEqual(db.query(AutomationAttempt).count(), 1)
        db.close()

    def test_uncertain_push_is_never_retried_automatically(self):
        db, rule = self._rule(action="push", action_arg="ping")
        delivery = mock.AsyncMock(
            return_value={
                "sent": 0,
                "failed": 0,
                "uncertain": 1,
                "pruned": 0,
                "total": 1,
            }
        )
        with mock.patch("routes.push.broadcast_result", delivery):
            first = asyncio.run(automations._fire(db, rule, {"dedupe": "push-1"}))
            second = asyncio.run(automations._fire(db, rule, {"dedupe": "push-1"}))

        self.assertEqual(first["status"], "uncertain")
        self.assertEqual(second["status"], "uncertain")
        self.assertFalse(second["executed"])
        self.assertEqual(delivery.await_count, 1)
        db.close()

    def test_no_push_recipient_is_a_confirmed_failure(self):
        db, rule = self._rule(action="push", action_arg="ping")
        result = asyncio.run(automations._fire(db, rule, {"dedupe": "push-empty"}))
        self.assertEqual(result["status"], "failed")
        self.assertIn("no live push", result["error"])
        db.close()

    def test_uncertain_notification_is_never_retried_automatically(self):
        db, rule = self._rule(action="notify", action_arg="ping")
        delivery = mock.AsyncMock(return_value={"discord": False, "telegram": None})
        with mock.patch("services.notify.send", delivery):
            first = asyncio.run(automations._fire(db, rule, {"dedupe": "notify-1"}))
            second = asyncio.run(automations._fire(db, rule, {"dedupe": "notify-1"}))
        self.assertEqual(first["status"], "uncertain")
        self.assertEqual(second["status"], "uncertain")
        self.assertEqual(delivery.await_count, 1)
        db.close()

    def test_occurrence_identity_does_not_store_private_source_text(self):
        db, rule = self._rule()
        private_value = "/private/vault/work/secret-file.md"
        asyncio.run(automations._fire(db, rule, {"dedupe": private_value}))
        attempt = db.query(AutomationAttempt).one()
        self.assertNotIn("private", attempt.occurrence_key)
        self.assertNotIn("secret-file", attempt.occurrence_key)
        self.assertEqual(len(attempt.occurrence_key), 64)
        db.close()

    def test_interrupted_claim_becomes_uncertain_before_jobs_resume(self):
        db, rule = self._rule()
        attempt = AutomationAttempt(
            rule_id=rule.id,
            occurrence_key="a" * 64,
            action=rule.action,
            status="running",
        )
        db.add(attempt)
        db.commit()
        attempt_id = attempt.id
        db.close()

        self.assertEqual(automations.reconcile_interrupted_attempts(), 1)
        db = self.db()
        attempt = db.get(AutomationAttempt, attempt_id)
        self.assertEqual(attempt.status, "uncertain")
        self.assertIsNotNone(attempt.finished_at)
        db.close()

    def test_canceled_action_is_saved_as_uncertain(self):
        db, rule = self._rule(action="push")
        with mock.patch.object(
            automations,
            "_perform_action",
            mock.AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(automations._fire(db, rule, {"dedupe": "shutdown"}))
        attempt = db.query(AutomationAttempt).one()
        self.assertEqual(attempt.status, "uncertain")
        db.close()

    def test_daily_success_marker_is_written_only_after_success(self):
        db, rule = self._rule(action="push")
        rule_id = rule.id
        db.close()

        with mock.patch.object(
            automations,
            "_fire",
            mock.AsyncMock(return_value={"status": "uncertain"}),
        ):
            asyncio.run(automations.run_automations())
        db = self.db()
        self.assertNotIn("last_daily", json.loads(db.get(AutomationRule, rule_id).state))
        db.close()

        with mock.patch.object(
            automations,
            "_fire",
            mock.AsyncMock(return_value={"status": "succeeded"}),
        ):
            asyncio.run(automations.run_automations())
        db = self.db()
        self.assertIn("last_daily", json.loads(db.get(AutomationRule, rule_id).state))
        db.close()

    def test_attempt_history_and_honest_manual_test_response(self):
        rule_id = self.client.post(
            "/api/automations",
            json={"trigger": "daily_at", "trigger_arg": "00:00", "action": "push"},
        ).json()["id"]
        response = self.client.post(f"/api/automations/{rule_id}/test")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["attempt"]["status"], "failed")

        attempts = self.client.get(f"/api/automations/{rule_id}/attempts").json()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertNotIn("occurrence_key", attempts[0])
        listed = self.client.get("/api/automations").json()
        self.assertEqual(listed[0]["last_attempt"]["status"], "failed")

    def test_deleting_rule_removes_attempt_history(self):
        db, rule = self._rule()
        rule_id = rule.id
        asyncio.run(automations._fire(db, rule, {"dedupe": "delete-me"}))
        db.close()
        self.assertEqual(self.client.delete(f"/api/automations/{rule_id}").status_code, 200)
        db = self.db()
        self.assertEqual(db.query(AutomationAttempt).filter_by(rule_id=rule_id).count(), 0)
        db.close()


class DocAutomationSafetyTests(VaultApiTest):
    def test_uncertain_note_write_is_not_repeated(self):
        db = self.db()
        rule = AutomationRule(
            name="doc rule",
            trigger="doc_tag",
            trigger_arg="urgent",
            action="create_note",
            action_arg="{path}",
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id
        db.close()

        with mock.patch(
            "services.notes_vault.create",
            side_effect=OSError("simulated uncertain filesystem result"),
        ) as create:
            asyncio.run(automations.on_doc_saved("private.md", "#urgent"))
            asyncio.run(automations.on_doc_saved("private.md", "#urgent"))

        self.assertEqual(create.call_count, 1)
        db = self.db()
        self.assertNotIn(
            "private.md", json.loads(db.get(AutomationRule, rule_id).state).get("done", {})
        )
        self.assertEqual(db.query(AutomationAttempt).one().status, "uncertain")
        db.close()


class MailAutomationTests(ApiTest):
    def test_new_mail_account_is_baselined_not_fired(self):
        db = self.db()
        old = MailAccount(id="old", email="old@example.com")
        new = MailAccount(id="new", email="new@example.com")
        rule = AutomationRule(
            trigger="mail_from",
            trigger_arg="boss@",
            action="create_task",
            action_arg="{subject}",
            state=json.dumps({"uids": {"old": 9}}),
        )
        db.add_all([old, new, rule])
        db.commit()

        def fake_fetch(acct, folder, limit):
            if acct["email"] == "old@example.com":
                return [{"uid": "10", "from": "boss@example.com", "subject": "new boss mail"}]
            return [{"uid": "100", "from": "boss@example.com", "subject": "historic boss mail"}]

        fired = []

        async def fake_fire(_db, _rule, ctx):
            fired.append(ctx)

        with (
            mock.patch("services.mail.fetch_inbox", fake_fetch),
            mock.patch.object(automations, "_fire", fake_fire),
        ):
            asyncio.run(automations._check_mail_rule(db, rule, json.loads(rule.state)))

        self.assertEqual([f["subject"] for f in fired], ["new boss mail"])
        db.refresh(rule)
        self.assertEqual(json.loads(rule.state)["uids"], {"old": 10, "new": 100})
        db.close()


if __name__ == "__main__":
    unittest.main()
