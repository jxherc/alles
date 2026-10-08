from core.database import CalendarEvent
from services import calendar_events
from services.ics import parse_ics
from tests._client import ApiTest


class CalendarExportParityTests(ApiTest):
    def test_saved_event_shape_matches_calendar_response(self):
        db = self.db()
        event = CalendarEvent(
            id="shape",
            title="Saved event",
            start_dt="2026-07-03T09:00:00",
            reminders="[10, 60]",
            recur_except='{"not": "a list"}',
            recur_interval=0,
        )
        db.add(event)
        db.commit()
        expected = calendar_events.event_dict(event)
        db.close()

        response = self.client.get("/api/calendar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [expected])
        self.assertEqual(expected["reminders"], [10, 60])
        self.assertEqual(expected["recur_except"], [])
        self.assertEqual(expected["recur_interval"], 1)

    def test_calendar_and_unified_ics_exports_match(self):
        db = self.db()
        db.add_all(
            [
                CalendarEvent(
                    id="trip",
                    title="Trip, with family",
                    start_dt="2026-06-30",
                    end_dt="2026-07-02",
                    all_day=True,
                    description="first day\nlast day",
                ),
                CalendarEvent(
                    id="meeting",
                    title="Team sync",
                    start_dt="2026-07-03T09:00:00",
                    end_dt="2026-07-03T09:30:00",
                    all_day=False,
                ),
            ]
        )
        db.commit()
        db.close()

        calendar = self.client.get("/api/calendar/export.ics")
        unified = self.client.get("/api/export/calendar", params={"format": "ical"})

        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(unified.status_code, 200)
        self.assertEqual(calendar.content, unified.content)
        self.assertEqual(calendar.headers["content-type"], unified.headers["content-type"])
        self.assertEqual(
            calendar.headers["content-disposition"], unified.headers["content-disposition"]
        )
        events = parse_ics(calendar.text)
        self.assertEqual([event["title"] for event in events], ["Trip, with family", "Team sync"])
        self.assertEqual(events[0]["end_dt"], "2026-07-02")
