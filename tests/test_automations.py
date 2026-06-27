import unittest

from services.automations import _render, _trim
from tests._client import ApiTest


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

        exposed = {t["value"] for t in self.client.get("/api/automations/options").json()["triggers"]}
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


if __name__ == "__main__":
    unittest.main()
