"""a chat message that asks for a task can be kept as one when there is no model to answer it
(aide's "add as a task" button): the quick add parser reads the message, not a quick add line."""

import unittest
from datetime import date

from services.task_nl import parse_message_task, strip_task_request
from tests._client import ApiTest


class StripTaskRequestTests(unittest.TestCase):
    def test_the_ask_around_the_task_comes_off(self):
        for text, expected in (
            ("add study for chem to my todo", "study for chem"),
            ("Add homework to my to-do list.", "homework"),
            ("please add call mom tomorrow to my tasks", "call mom tomorrow"),
            ("add a task: pay rent", "pay rent"),
            ("remind me to water the plants", "water the plants"),
            ("todo: email the teacher", "email the teacher"),
            ("buy milk as a task", "buy milk"),
            ("put dentist on my todo list", "dentist"),
        ):
            with self.subTest(text=text):
                self.assertEqual(strip_task_request(text), expected)

    def test_a_plain_message_is_not_an_ask(self):
        for text in ("what's the weather", "add", "make a plan for tomorrow", "hi", ""):
            with self.subTest(text=text):
                self.assertIsNone(strip_task_request(text))

    def test_understood_means_an_ask_or_something_the_parser_takes(self):
        today = date(2026, 10, 28)
        parsed, understood = parse_message_task("add study for chem to my todo", today=today)
        self.assertEqual((parsed["title"], understood), ("study for chem", True))
        parsed, understood = parse_message_task("chem test tomorrow 9am", today=today)
        self.assertEqual(
            (parsed["due_date"], parsed["due_time"], understood), ("2026-10-29", "09:00", True)
        )
        _, understood = parse_message_task("how do enzymes work", today=today)
        self.assertFalse(understood)


class MessageTaskApiTests(ApiTest):
    def quick(self, text, **extra):
        return self.client.post(
            "/api/tasks/quick", json={"text": text, "from_message": True, **extra}
        )

    def test_the_preview_says_whether_it_reads_as_a_task(self):
        yes = self.quick("add study for chem to my todo", preview=True).json()
        self.assertTrue(yes["understood"])
        self.assertEqual(yes["candidate"]["title"], "study for chem")
        no = self.quick("how do enzymes work", preview=True).json()
        self.assertFalse(no["understood"])
        self.assertEqual(self.client.get("/api/tasks").json(), [])

    def test_adding_keeps_the_task_and_refuses_what_is_not_one(self):
        added = self.quick("add study for chem to my todo tomorrow 9 am")
        self.assertEqual(added.status_code, 200, added.text)
        body = added.json()
        self.assertEqual((body["title"], body["due_time"]), ("study for chem", "09:00"))
        self.assertTrue(body["due_date"])
        refused = self.quick("how do enzymes work")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(len(self.client.get("/api/tasks").json()), 1)

    def test_an_ordinary_quick_add_is_unchanged(self):
        r = self.client.post("/api/tasks/quick", json={"text": "add milk", "preview": True}).json()
        self.assertNotIn("understood", r)
        self.assertEqual(r["candidate"]["title"], "add milk")


if __name__ == "__main__":
    unittest.main()
