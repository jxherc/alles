from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from core.database import CalendarEvent, Reminder, Task
from tests._client import ApiTest


class TodayApiTest(ApiTest):
    def test_reminders_use_requested_timezone_day_and_clock_across_midnight_and_dst(self):
        cases = [
            # UTC has crossed midnight, but Toronto has not.
            ("America/Toronto", "2026-09-25", "2026-09-26T00:30:00", "20:30", True),
            ("America/Toronto", "2026-09-25", "2026-09-26T04:00:00", "00:00", False),
            # UTC is still yesterday, but Tokyo has crossed midnight.
            ("Asia/Tokyo", "2026-09-25", "2026-09-25T15:00:00", "00:00", False),
            ("Asia/Tokyo", "2026-09-26", "2026-09-25T15:00:00", "00:00", True),
            ("America/Toronto", "2026-03-08", "2026-03-08T07:30:00", "03:30", True),
            ("America/Toronto", "2026-11-01", "2026-11-01T05:30:00", "01:30", True),
            ("America/Toronto", "2026-11-01", "2026-11-01T06:30:00", "01:30", True),
        ]
        for zone, day, trigger, clock, visible in cases:
            with self.subTest(zone=zone, day=day, trigger=trigger):
                with self.db() as db:
                    db.query(Reminder).delete()
                    db.add(
                        Reminder(
                            text="boundary", trigger_at=datetime.fromisoformat(trigger), fired=False
                        )
                    )
                    db.add(
                        Reminder(
                            text="already fired",
                            trigger_at=datetime.fromisoformat(trigger),
                            fired=True,
                        )
                    )
                    db.commit()
                # An explicit viewer zone takes precedence over a different configured zone.
                with patch("core.settings.load_settings", return_value={"timezone": "UTC"}):
                    response = self.client.get("/api/today", params={"date": day, "timezone": zone})
                self.assertEqual(response.status_code, 200, response.text)
                reminders = response.json()["reminders"]
                self.assertEqual(
                    [row["text"] for row in reminders], ["boundary"] if visible else []
                )
                if visible:
                    self.assertEqual(reminders[0]["at"], clock)

    def test_invalid_reminder_timezone_is_rejected(self):
        response = self.client.get(
            "/api/today", params={"date": "2026-09-25", "timezone": "unknown/zone"}
        )
        self.assertEqual(response.status_code, 400)

    def test_date_only_reminders_fall_back_to_configured_timezone(self):
        with self.db() as db:
            db.add(Reminder(text="owner day", trigger_at=datetime(2026, 9, 26, 0, 30)))
            db.commit()
        with patch("core.settings.load_settings", return_value={"timezone": "America/Toronto"}):
            response = self.client.get("/api/today", params={"date": "2026-09-25"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [(r["text"], r["at"]) for r in response.json()["reminders"]], [("owner day", "20:30")]
        )

    def test_missing_or_invalid_date_uses_resolved_timezone_today(self):
        with self.db() as db:
            db.add(Reminder(text="owner day", trigger_at=datetime(2026, 9, 26, 0, 30)))
            db.commit()
        for supplied_date in (None, "invalid"):
            for viewer_zone, expected_date, expected_clock in (
                (None, "2026-09-25", "20:30"),
                ("Asia/Tokyo", "2026-09-26", "09:30"),
            ):
                with self.subTest(date=supplied_date, zone=viewer_zone):
                    params = {}
                    if supplied_date:
                        params["date"] = supplied_date
                    if viewer_zone:
                        params["timezone"] = viewer_zone
                    with (
                        patch(
                            "core.settings.load_settings",
                            return_value={"timezone": "America/Toronto"},
                        ),
                        patch("services.signals.datetime", wraps=datetime) as clock,
                    ):
                        clock.now.return_value = datetime(2026, 9, 26, 1, tzinfo=UTC)
                        response = self.client.get("/api/today", params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["date"], expected_date)
                    self.assertEqual(response.json()["reminders"][0]["at"], expected_clock)

    def test_date_only_without_configured_timezone_uses_server_local_zone(self):
        instant = datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
        local = instant.astimezone()
        with self.db() as db:
            db.add(Reminder(text="server day", trigger_at=instant.replace(tzinfo=None)))
            db.commit()
        for settings in ({}, {"timezone": ""}, {"timezone": "old/invalid"}):
            with self.subTest(settings=settings):
                with patch("core.settings.load_settings", return_value=settings):
                    response = self.client.get(
                        "/api/today", params={"date": local.date().isoformat()}
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["reminders"][0]["at"], local.strftime("%H:%M"))

    def test_aggregates_events_tasks_reminders(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(CalendarEvent(title="today event", start_dt=f"{today}T10:00:00", all_day=False))
        d.add(Task(title="due today", due_date=today, done=False))
        d.add(Task(title="way overdue", due_date="2000-01-01", done=False))
        d.add(Task(title="done already", due_date=today, done=True))
        d.add(
            Reminder(
                text="ping me",
                trigger_at=datetime.now(UTC).replace(tzinfo=None),
                fired=False,
                type="reminder",
            )
        )
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertIn("today event", [e["title"] for e in r["events"]])
        self.assertIn("due today", [t["title"] for t in r["tasks"]["due_today"]])
        self.assertIn("way overdue", [t["title"] for t in r["tasks"]["overdue"]])
        self.assertIn("ping me", [x["text"] for x in r["reminders"]])
        # the completed task isn't counted as open
        self.assertNotIn("done already", [t["title"] for t in r["tasks"]["due_today"]])

    def test_empty_day(self):
        r = self.client.get("/api/today").json()
        self.assertEqual(r["events"], [])
        self.assertEqual(r["tasks"]["overdue"], [])
        self.assertEqual(r["tasks"]["open_count"], 0)

    def test_date_query_param(self):
        # pass a specific date; only that date's event should show up
        target = "2030-03-15"
        d = self.db()
        d.add(CalendarEvent(title="march event", start_dt=f"{target}T09:00:00", all_day=False))
        d.add(CalendarEvent(title="other day", start_dt="2030-03-16T09:00:00", all_day=False))
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={target}").json()
        titles = [e["title"] for e in r["events"]]
        self.assertIn("march event", titles)
        self.assertNotIn("other day", titles)
        self.assertEqual(r["date"], target)

    def test_open_count_includes_tasks_without_due_date(self):
        d = self.db()
        d.add(Task(title="no due date", done=False))
        d.add(Task(title="also no due", done=False))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertGreaterEqual(r["tasks"]["open_count"], 2)

    def test_fired_reminder_not_returned(self):
        d = self.db()
        d.add(
            Reminder(
                text="old fired",
                trigger_at=datetime.now(UTC).replace(tzinfo=None),
                fired=True,
                type="reminder",
            )
        )
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertNotIn("old fired", [x["text"] for x in r["reminders"]])

    def test_future_reminder_not_returned(self):
        tomorrow = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2)
        d = self.db()
        d.add(Reminder(text="future ping", trigger_at=tomorrow, fired=False, type="reminder"))
        d.commit()
        d.close()

        # use today's date so "tomorrow" is definitely in the future
        today = date.today().isoformat()
        r = self.client.get(f"/api/today?date={today}").json()
        self.assertNotIn("future ping", [x["text"] for x in r["reminders"]])

    def test_all_day_event_has_empty_time(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(CalendarEvent(title="all day thing", start_dt=today, all_day=True))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        match = next((e for e in r["events"] if e["title"] == "all day thing"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["time"], "")
        self.assertTrue(match["all_day"])

    def test_weekly_recurring_event_appears_on_matching_weekday(self):
        # find next monday from today
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7  # skip today if today is monday
        next_monday = today + timedelta(days=days_until_monday)

        # create a weekly event that started on a past monday
        past_monday = next_monday - timedelta(weeks=2)
        d = self.db()
        d.add(
            CalendarEvent(
                title="weekly monday",
                start_dt=past_monday.isoformat() + "T08:00:00",
                recurrence="weekly",
                all_day=False,
            )
        )
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={next_monday.isoformat()}").json()
        titles = [e["title"] for e in r["events"]]
        self.assertIn("weekly monday", titles)

    def test_monthly_31st_recurring_event_appears_on_short_month_clamp(self):
        d = self.db()
        d.add(
            CalendarEvent(
                title="monthly close",
                start_dt="2026-01-31T08:00:00",
                recurrence="monthly",
                all_day=False,
            )
        )
        d.commit()
        d.close()

        r = self.client.get("/api/today?date=2026-02-28").json()
        self.assertIn("monthly close", [e["title"] for e in r["events"]])

    def test_task_without_due_date_not_in_overdue_or_due_today(self):
        d = self.db()
        d.add(Task(title="floaty task", done=False))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        all_due = r["tasks"]["due_today"] + r["tasks"]["overdue"]
        self.assertNotIn("floaty task", [t["title"] for t in all_due])
        # but it does count toward open_count
        self.assertGreaterEqual(r["tasks"]["open_count"], 1)

    def test_response_structure_always_present(self):
        r = self.client.get("/api/today").json()
        self.assertIn("date", r)
        self.assertIn("events", r)
        self.assertIn("tasks", r)
        self.assertIn("reminders", r)
        self.assertIn("renewing", r)
        self.assertIn("day_events", r)
        self.assertIn("recent_docs", r)
        self.assertIn("overdue", r["tasks"])
        self.assertIn("due_today", r["tasks"])
        self.assertIn("open_count", r["tasks"])

    def test_weekly_recurring_not_on_wrong_weekday(self):
        # a weekly event on monday shouldn't appear on tuesday
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        next_monday = today + timedelta(days=days_until_monday)
        next_tuesday = next_monday + timedelta(days=1)

        past_monday = next_monday - timedelta(weeks=2)
        d = self.db()
        d.add(
            CalendarEvent(
                title="monday only",
                start_dt=past_monday.isoformat() + "T08:00:00",
                recurrence="weekly",
                all_day=False,
            )
        )
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={next_tuesday.isoformat()}").json()
        self.assertNotIn("monday only", [e["title"] for e in r["events"]])
