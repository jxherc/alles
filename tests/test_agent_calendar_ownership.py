import asyncio
from unittest import mock

from core.database import CalendarEvent
from services import agent_tools
from tests._client import ApiTest


class AgentCalendarOwnershipTests(ApiTest):
    def test_create_uses_calendar_rules_and_keeps_tool_result(self):
        with mock.patch(
            "services.calendar_events.load_settings",
            return_value={"cal_default_duration_min": 30},
        ):
            result = asyncio.run(
                agent_tools.execute(
                    "calendar_create",
                    {
                        "title": "Team review",
                        "start_dt": "2026-06-20T11:00",
                        "color": "green",
                        "recurrence": "weekly",
                    },
                )
            )
        self.assertFalse(result.get("error"), result)
        self.assertIn("created event", result["output"])
        db = self.db()
        try:
            event = db.query(CalendarEvent).one()
            self.assertEqual(event.title, "Team review")
            self.assertEqual(event.end_dt, "2026-06-20T11:30:00")
            self.assertTrue(event.calendar_id)
            self.assertEqual(event.color, "green")
            self.assertEqual(event.recurrence, "weekly")
        finally:
            db.close()

    def test_invalid_date_returns_tool_error_without_writing(self):
        result = asyncio.run(
            agent_tools.execute("calendar_create", {"title": "Broken", "start_dt": "not a date"})
        )
        self.assertTrue(result.get("error"), result)
        db = self.db()
        try:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        finally:
            db.close()

    def test_wrong_boolean_type_does_not_make_an_all_day_event(self):
        result = asyncio.run(
            agent_tools.execute(
                "calendar_create",
                {"title": "Timed", "start_dt": "2026-06-20T11:00", "all_day": "false"},
            )
        )
        self.assertTrue(result.get("error"), result)
        db = self.db()
        try:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        finally:
            db.close()
