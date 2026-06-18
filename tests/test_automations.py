import unittest
from services.automations import _render
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


if __name__ == "__main__":
    unittest.main()
