import asyncio
import unittest
from unittest import mock

from core.database import Task
from routes import search
from services import agent_tools as at
from tests._client import ApiTest


class CrossAppToolTests(unittest.TestCase):
    def _names(self, settings):
        return {t["function"]["name"] for t in at.build_tool_defs(settings)}

    def test_app_tools_registered(self):
        n = self._names({})
        for t in (
            "calendar_list",
            "calendar_create",
            "task_add",
            "task_list",
            "note_write",
            "note_search",
            "contact_add",
            "mail_list",
            "mail_send",
            "calendar_delete",
            "task_done",
            "contact_list",
            "note_read",
            "note_list",
        ):
            self.assertIn(t, n)

    def test_plan_mode_hides_app_mutations(self):
        plan = self._names({"agent_permission_mode": "plan"})
        for mut in (
            "calendar_create",
            "calendar_delete",
            "task_add",
            "task_done",
            "note_write",
            "contact_add",
            "mail_send",
        ):
            self.assertNotIn(mut, plan)
        for read in ("calendar_list", "task_list", "note_search", "mail_list", "contact_list"):
            self.assertIn(read, plan)  # reads stay available in plan mode

    def test_app_mutations_in_mutating_set(self):
        for mut in (
            "calendar_create",
            "calendar_delete",
            "task_add",
            "task_done",
            "note_write",
            "contact_add",
            "mail_send",
        ):
            self.assertIn(mut, at.MUTATING_TOOLS)

    def test_full_auto_has_more_tools_than_plan(self):
        full = self._names({"agent_permission_mode": "full_auto"})
        plan = self._names({"agent_permission_mode": "plan"})
        self.assertGreater(len(full), len(plan))

    def test_subagent_tools_are_hidden_when_profile_disables_delegation(self):
        names = self._names({"agent_subagents": False})
        self.assertNotIn("spawn_agent", names)
        self.assertNotIn("spawn_agents", names)

    def test_shell_in_mutating_set(self):
        self.assertIn("shell", at.MUTATING_TOOLS)
        self.assertIn("write_file", at.MUTATING_TOOLS)

    def test_decide_permission_full_access_allows_mutations(self):
        for name, args in (
            ("write_file", {"path": "/tmp/x.txt"}),
            ("shell", {"command": "true"}),
            ("mail_send", {"to": "owner@example.com"}),
            ("computer_click", {"x": 1, "y": 1}),
            ("spawn_agent", {"task": "check"}),
        ):
            self.assertEqual(at.decide_permission(name, args, "full_access", []), "allow")

    def test_decide_permission_auto_is_risk_aware(self):
        self.assertEqual(
            at.decide_permission("write_file", {"path": "/tmp/x.txt"}, "full_auto", []),
            "allow",
        )
        for name in ("shell", "calendar_delete", "mail_send", "computer_click", "spawn_agent"):
            self.assertEqual(at.decide_permission(name, {}, "full_auto", []), "ask")

    def test_decide_permission_plan_denies_mutations(self):
        p = at.decide_permission("write_file", {"path": "/tmp/x.txt"}, "plan", [])
        self.assertEqual(p, "deny")

    def test_decide_permission_approve_asks(self):
        p = at.decide_permission("shell", {"command": "ls"}, "approve", [])
        self.assertEqual(p, "ask")

    def test_decide_permission_rule_override_wins(self):
        # user rule that always allows shell
        rules = [{"tool": "shell", "action": "allow"}]
        p = at.decide_permission("shell", {"command": "ls"}, "approve", rules)
        self.assertEqual(p, "allow")

    def test_every_permission_level_covers_each_risk_class(self):
        cases = {
            "read": ("read_file", {"path": "notes.md"}),
            "write": ("write_file", {"path": "notes.md"}),
            "shell": ("shell", {"command": "pwd"}),
            "deletion": ("calendar_delete", {"id": "event"}),
            "external communication": ("mail_send", {"to": "owner@example.com"}),
            "computer use": ("computer_click", {"x": 1, "y": 1}),
            "delegation": ("spawn_agent", {"task": "inspect"}),
        }
        expected = {
            "full_access": {name: "allow" for name in cases},
            "full_auto": {
                "read": "allow",
                "write": "allow",
                "shell": "ask",
                "deletion": "ask",
                "external communication": "ask",
                "computer use": "ask",
                "delegation": "ask",
            },
            "approve": {name: ("allow" if name == "read" else "ask") for name in cases},
            "plan": {name: ("allow" if name == "read" else "deny") for name in cases},
        }
        for mode, decisions in expected.items():
            for risk, (tool, arguments) in cases.items():
                with self.subTest(mode=mode, risk=risk):
                    self.assertEqual(
                        at.decide_permission(tool, arguments, mode, []), decisions[risk]
                    )


class TaskToolApiTests(ApiTest):
    def test_aide_add_rejects_invalid_titles_without_saving_a_task(self):
        for title in ("", "   ", None, 7):
            with self.subTest(title=title):
                result = asyncio.run(at.execute("task_add", {"title": title}))
                self.assertTrue(result.get("error"), result)
        self.assertEqual(self.client.get("/api/tasks").json(), [])

    def test_aide_add_uses_the_same_clean_title_seen_in_plan(self):
        result = asyncio.run(at.execute("task_add", {"title": "  call mom  "}))
        self.assertNotIn("error", result)
        tasks = self.client.get("/api/tasks").json()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "call mom")
        self.assertEqual(tasks[0]["stage"], "backlog")

    def test_aide_completion_keeps_recurring_task_and_activity_rules(self):
        task = self.client.post(
            "/api/tasks",
            json={
                "title": "pay rent",
                "due_date": "2026-01-31",
                "repeat": "monthly",
                "stage": "doing",
            },
        ).json()

        result = asyncio.run(at.execute("task_done", {"id": task["id"], "done": True}))
        self.assertNotIn("error", result)
        with self.db() as db:
            original = db.get(Task, task["id"])
            self.assertTrue(original.done)
            self.assertEqual(original.stage, "done")
            self.assertIsNotNone(original.completed_at)
            next_task = db.query(Task).filter(Task.id != task["id"]).one()
            self.assertEqual(next_task.due_date, "2026-02-28")
            self.assertEqual(next_task.anchor_day, 31)
            self.assertFalse(next_task.done)
            self.assertEqual(next_task.stage, "backlog")

        timeline = self.client.get("/api/timeline", params={"types": "task", "days": 7})
        self.assertEqual(timeline.status_code, 200)
        self.assertTrue(
            any(
                item["id"] == task["id"] and item["subtitle"] == "completed"
                for item in timeline.json()["events"]
            )
        )

        asyncio.run(at.execute("task_done", {"id": task["id"], "done": True}))
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)

    def test_aide_reopen_clears_completion_without_resetting_active_work(self):
        task = self.client.post(
            "/api/tasks", json={"title": "finish report", "stage": "doing"}
        ).json()
        asyncio.run(at.execute("task_done", {"id": task["id"], "done": False}))
        with self.db() as db:
            self.assertEqual(db.get(Task, task["id"]).stage, "doing")

        self.client.patch(f"/api/tasks/{task['id']}", json={"done": True})
        asyncio.run(at.execute("task_done", {"id": task["id"], "done": False}))
        with self.db() as db:
            reopened = db.get(Task, task["id"])
            self.assertFalse(reopened.done)
            self.assertEqual(reopened.stage, "backlog")
            self.assertIsNone(reopened.completed_at)

    def test_aide_rejects_non_boolean_completion_without_changing_task(self):
        task = self.client.post("/api/tasks", json={"title": "leave open"}).json()

        result = asyncio.run(at.execute("task_done", {"id": task["id"], "done": "false"}))

        self.assertTrue(result.get("error"))
        with self.db() as db:
            self.assertFalse(db.get(Task, task["id"]).done)


class ContactToolApiTests(ApiTest):
    def test_contact_api_create_is_available_to_aide_recall(self):
        with mock.patch("services.textindex._embed", return_value=None):
            contact = self.client.post("/api/contacts", json={"name": "Quartzferret API"}).json()
            recall = asyncio.run(at.execute("recall", {"query": "Quartzferret"}))
        self.assertIn(contact["name"], recall["output"])
        self.assertIn(f"/?app=contacts#{contact['id']}", recall["output"])

    def test_aide_contact_add_is_available_to_aide_recall(self):
        with mock.patch("services.textindex._embed", return_value=None):
            added = asyncio.run(
                at.execute(
                    "contact_add",
                    {
                        "name": "Quartzferret Aide",
                        "email": "quartzferret@example.test",
                        "phone": "555-0101",
                        "notes": "met at the library",
                    },
                )
            )
            recall = asyncio.run(at.execute("recall", {"query": "Quartzferret"}))
        self.assertFalse(added.get("error"), added)
        contact = self.client.get("/api/contacts").json()[0]
        self.assertEqual(contact["name"], "Quartzferret Aide")
        self.assertEqual(contact["email"], "quartzferret@example.test")
        self.assertEqual(contact["phone"], "555-0101")
        self.assertEqual(contact["notes"], "met at the library")
        self.assertEqual(contact["tags"], [])
        self.assertIn("Quartzferret Aide", recall["output"])
        self.assertIn(f"/?app=contacts#{contact['id']}", recall["output"])

    def test_contact_create_survives_an_index_outage(self):
        with mock.patch(
            "services.personal_index.index_record", side_effect=RuntimeError("offline")
        ):
            api = self.client.post("/api/contacts", json={"name": "API Contact"})
            aide = asyncio.run(at.execute("contact_add", {"name": "Aide Contact"}))
        self.assertEqual(api.status_code, 200)
        self.assertFalse(aide.get("error"), aide)
        self.assertEqual(
            sorted(contact["name"] for contact in self.client.get("/api/contacts").json()),
            ["API Contact", "Aide Contact"],
        )


class SearchHelperTests(unittest.TestCase):
    def test_snip_centers_match(self):
        t = ("word " * 30) + "NEEDLE here " + ("word " * 30)
        s = search._snip(t, "needle")
        self.assertIn("NEEDLE", s)
        self.assertLessEqual(len(s), 121)
        self.assertNotIn("\n", s)

    def test_snip_no_match_takes_head(self):
        self.assertTrue(search._snip("abc def ghi", "zzz").startswith("abc"))

    def test_snip_strips_newlines(self):
        # multiline text — snip should collapse newlines
        t = "hello\nNEEDLE\nworld"
        s = search._snip(t, "needle")
        self.assertNotIn("\n", s)

    def test_snip_at_start(self):
        # match at very beginning — no room to go left
        s = search._snip("NEEDLE rest of text", "needle")
        self.assertTrue(s.startswith("NEEDLE"))


if __name__ == "__main__":
    unittest.main()
