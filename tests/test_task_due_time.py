"""a task can be due at a time: the api, sorting, overdue, the calendar and the agent tools."""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch

from core.database import Task
from services import calendar_events
from services.task_due import clean_clock, is_overdue, sort_key, split_due
from tests._client import ApiTest

NOW = datetime(2026, 10, 22, 10, 30)


class DueMomentHelpersTests(unittest.TestCase):
    def test_a_clock_is_padded_and_checked(self):
        self.assertEqual(clean_clock("9:05"), "09:05")
        self.assertEqual(clean_clock("09:30:00"), "09:30")
        self.assertIsNone(clean_clock(""))
        self.assertIsNone(clean_clock(None))
        for bad in ("25:00", "9", "9am", "12:60", "noon"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_clock(bad)

    def test_a_day_that_carries_a_time_splits(self):
        self.assertEqual(split_due("2026-10-20T09:30"), ("2026-10-20", "09:30"))
        self.assertEqual(split_due("2026-10-20"), ("2026-10-20", None))
        self.assertEqual(split_due("nope"), (None, None))

    def test_a_day_with_no_time_follows_the_ones_with_a_time(self):
        rows = [("2026-10-22", None), ("2026-10-22", "08:00"), ("2026-10-21", None), (None, None)]
        rows.sort(key=lambda r: sort_key(*r))
        self.assertEqual(
            rows,
            [("2026-10-21", None), ("2026-10-22", "08:00"), ("2026-10-22", None), (None, None)],
        )

    def test_overdue_at_the_time_not_at_midnight(self):
        self.assertTrue(is_overdue("2026-10-21", None, NOW))
        self.assertTrue(is_overdue("2026-10-22", "09:00", NOW))
        self.assertFalse(is_overdue("2026-10-22", "10:30", NOW))
        self.assertFalse(is_overdue("2026-10-22", "11:00", NOW))
        self.assertFalse(is_overdue("2026-10-22", None, NOW))  # due today, any time
        self.assertFalse(is_overdue("2026-10-23", "01:00", NOW))
        self.assertFalse(is_overdue(None, "09:00", NOW))


class TaskDueTimeApiTests(ApiTest):
    def make(self, **body):
        r = self.client.post("/api/tasks", json={"title": "chem test", **body})
        return r

    def test_a_task_keeps_its_time(self):
        r = self.make(due_date="2026-10-23", due_time="9:00")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["due_date"], r.json()["due_time"]), ("2026-10-23", "09:00"))
        again = self.client.get("/api/tasks").json()[0]
        self.assertEqual(again["due_time"], "09:00")

    def test_a_task_with_no_time_says_so(self):
        r = self.make(due_date="2026-10-23")
        self.assertIsNone(r.json()["due_time"])

    def test_a_time_needs_a_day_and_must_be_a_time(self):
        self.assertEqual(self.make(due_time="09:00").status_code, 400)
        self.assertEqual(self.make(due_date="2026-10-23", due_time="9am").status_code, 400)
        self.assertEqual(self.make(due_date="2026-10-23", due_time="25:00").status_code, 400)

    def test_a_day_that_carries_a_time_is_split(self):
        r = self.make(due_date="2026-10-23T14:15")
        self.assertEqual((r.json()["due_date"], r.json()["due_time"]), ("2026-10-23", "14:15"))

    def test_the_natural_language_create_reads_the_time(self):
        r = self.client.post(
            "/api/tasks", json={"title": "chem unit test tomorrow 9 am", "nl": True}
        )
        body = r.json()
        self.assertEqual(body["title"], "chem unit test")
        self.assertEqual(body["due_time"], "09:00")
        self.assertTrue(body["due_date"])

    def test_quick_add_reads_the_time(self):
        r = self.client.post("/api/tasks/quick", json={"text": "dentist friday 3:30pm"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["title"], r.json()["due_time"]), ("dentist", "15:30"))
        pre = self.client.post(
            "/api/tasks/quick", json={"text": "dentist friday 3:30pm", "preview": True}
        ).json()
        self.assertEqual(pre["candidate"]["due_time"], "15:30")

    def test_the_add_rows_due_field_wins_over_the_text(self):
        r = self.client.post(
            "/api/tasks/quick",
            json={"text": "dentist friday 3:30pm", "due": "2026-11-05T16:00"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        got = r.json()
        self.assertEqual((got["due_date"], got["due_time"]), ("2026-11-05", "16:00"))
        day_only = self.client.post(
            "/api/tasks/quick", json={"text": "water the plants", "due": "2026-11-06"}
        ).json()
        self.assertEqual((day_only["due_date"], day_only["due_time"]), ("2026-11-06", None))
        bad = self.client.post("/api/tasks/quick", json={"text": "x", "due": "2026-11-06T25:00"})
        self.assertEqual(bad.status_code, 400)

    def test_moving_the_day_keeps_the_time_and_clearing_the_day_clears_it(self):
        tid = self.make(due_date="2026-10-23", due_time="09:00").json()["id"]
        moved = self.client.patch(f"/api/tasks/{tid}", json={"due_date": "2026-10-25"}).json()
        self.assertEqual((moved["due_date"], moved["due_time"]), ("2026-10-25", "09:00"))
        retimed = self.client.patch(f"/api/tasks/{tid}", json={"due_time": "17:45"}).json()
        self.assertEqual(retimed["due_time"], "17:45")
        any_time = self.client.patch(f"/api/tasks/{tid}", json={"due_time": None}).json()
        self.assertEqual((any_time["due_date"], any_time["due_time"]), ("2026-10-25", None))
        self.client.patch(f"/api/tasks/{tid}", json={"due_time": "08:00"})
        cleared = self.client.patch(f"/api/tasks/{tid}", json={"due_date": None}).json()
        self.assertEqual((cleared["due_date"], cleared["due_time"]), (None, None))

    def test_a_time_with_no_day_on_the_task_is_refused(self):
        tid = self.make().json()["id"]
        r = self.client.patch(f"/api/tasks/{tid}", json={"due_time": "09:00"})
        self.assertEqual(r.status_code, 400)

    def test_a_guarded_edit_can_change_the_time(self):
        tid = self.make(due_date="2026-10-23", due_time="09:00").json()["id"]
        r = self.client.patch(
            f"/api/tasks/{tid}",
            json={"due_time": "10:00", "expected": {"due_time": "09:00"}},
        )
        self.assertEqual(r.status_code, 200, r.text)
        stale = self.client.patch(
            f"/api/tasks/{tid}",
            json={"due_time": "11:00", "expected": {"due_time": "09:00"}},
        )
        self.assertEqual(stale.status_code, 409)

    def test_a_task_goes_overdue_at_its_time(self):
        with patch.object(calendar_events, "owner_now", return_value=NOW):
            soon = self.make(title="later", due_date="2026-10-22", due_time="18:00").json()
            gone = self.make(title="earlier", due_date="2026-10-22", due_time="08:00").json()
            anyt = self.make(title="anytime", due_date="2026-10-22").json()
            old = self.make(title="old", due_date="2026-10-21").json()
            rows = {t["title"]: t for t in self.client.get("/api/tasks").json()}
        self.assertFalse(soon["overdue"] or anyt["overdue"])
        self.assertTrue(gone["overdue"] and old["overdue"])
        self.assertEqual(rows["earlier"]["overdue"], True)
        self.assertEqual(rows["later"]["overdue"], False)

    def test_the_list_sorts_by_day_then_time_with_no_time_last(self):
        for title, day, clock in (
            ("c", "2026-10-23", None),
            ("b", "2026-10-23", "13:00"),
            ("a", "2026-10-23", "08:00"),
            ("z", "2026-10-22", None),
        ):
            self.make(title=title, due_date=day, due_time=clock)
        order = [t["title"] for t in self.client.get("/api/tasks").json()]
        self.assertEqual(order, ["z", "a", "b", "c"])

    def test_a_repeat_keeps_its_time(self):
        tid = self.make(due_date="2026-10-23", due_time="07:30", repeat="daily").json()["id"]
        out = self.client.patch(f"/api/tasks/{tid}", json={"done": True}).json()
        self.assertEqual(out["spawned"]["due_time"], "07:30")

    def test_the_calendar_overlay_and_agenda_carry_the_time(self):
        self.make(title="exam", due_date="2026-10-22", due_time="09:00")
        self.make(title="essay", due_date="2026-10-22", due_time="20:00")
        overlay = self.client.get(
            "/api/calendar/tasks", params={"start": "2026-10-22", "end": "2026-10-22"}
        ).json()
        self.assertEqual(
            [(t["title"], t["time"]) for t in overlay], [("exam", "09:00"), ("essay", "20:00")]
        )
        with patch.object(calendar_events, "owner_now", return_value=NOW):
            agenda = self.client.get("/api/calendar/agenda", params={"days": 3}).json()
        self.assertEqual([t["title"] for t in agenda["overdue"]], ["exam"])
        today = next(d for d in agenda["days"] if d["date"] == "2026-10-22")
        self.assertEqual(
            [(t["title"], t["due_time"]) for t in today["tasks"]], [("essay", "20:00")]
        )


class TaskDueTimeAgentToolTests(ApiTest):
    def run_tool(self, args):
        from services import agent_tools

        return asyncio.run(agent_tools.execute("task_add", args))

    def test_the_tool_takes_a_day_and_a_time(self):
        out = self.run_tool(
            {"title": "hand in essay", "due_date": "2026-10-23", "due_time": "08:15"}
        )
        self.assertNotIn("error", out, out)
        row = self.client.get("/api/tasks").json()[0]
        self.assertEqual(
            (row["title"], row["due_date"], row["due_time"]),
            ("hand in essay", "2026-10-23", "08:15"),
        )
        self.assertIn("08:15", out["output"])

    def test_words_left_in_the_title_count_when_no_day_was_given(self):
        out = self.run_tool({"title": "chem unit test tomorrow 9 am"})
        self.assertNotIn("error", out, out)
        row = self.client.get("/api/tasks").json()[0]
        self.assertEqual((row["title"], row["due_time"]), ("chem unit test", "09:00"))

    def test_a_plain_title_stays_plain(self):
        self.run_tool({"title": "homework"})
        row = self.client.get("/api/tasks").json()[0]
        self.assertEqual((row["title"], row["due_date"], row["due_time"]), ("homework", None, None))

    def test_a_bad_day_or_a_time_with_no_day_is_an_error(self):
        for args in (
            {"title": "x", "due_date": "friday"},
            {"title": "x", "due_date": "2026-10-23", "due_time": "9am"},
            {"title": "x", "due_time": "09:00"},
            {"title": "  "},
        ):
            with self.subTest(args=args):
                self.assertTrue(self.run_tool(args).get("error"))
        self.assertEqual(self.client.get("/api/tasks").json(), [])

    def test_the_list_shows_the_time(self):
        self.run_tool({"title": "exam", "due_date": "2026-10-23", "due_time": "09:00"})
        from services import agent_tools

        out = asyncio.run(agent_tools.execute("task_list", {}))
        self.assertIn("(due 2026-10-23 09:00)", out["output"])


class TaskDueTimeMigrationTests(ApiTest):
    def test_a_time_inside_the_day_is_split_and_a_second_run_changes_nothing(self):
        from sqlalchemy import text

        from core.database import engine
        from core.migrations import m0077_task_due_time

        d = self.db()
        d.add_all(
            [
                Task(title="old timed", due_date="2026-10-20T09:30"),
                Task(title="old day", due_date="2026-10-21"),
            ]
        )
        d.commit()
        d.close()
        with engine.begin() as conn:
            m0077_task_due_time.up(conn)
            m0077_task_due_time.up(conn)
            rows = {
                title: shown
                for title, shown in conn.execute(
                    text("SELECT title, due_date || ' ' || COALESCE(due_time, '-') FROM tasks")
                ).fetchall()
            }
        self.assertEqual(rows["old timed"], "2026-10-20 09:30")
        self.assertEqual(rows["old day"], "2026-10-21 -")


if __name__ == "__main__":
    unittest.main()
