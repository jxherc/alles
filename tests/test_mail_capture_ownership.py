import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import core.settings
from core.database import CalendarEvent, ModelEndpoint, Task
from tests._client import ApiTest


class MailCaptureOwnershipTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._settings_dir = tempfile.TemporaryDirectory()
        self._settings_path = mock.patch.object(
            core.settings, "_SETTINGS_FILE", Path(self._settings_dir.name) / "settings.json"
        )
        self._settings_path.start()
        core.settings._clear_settings_cache()

    def tearDown(self):
        self._settings_path.stop()
        core.settings._clear_settings_cache()
        self._settings_dir.cleanup()
        super().tearDown()

    def _model(self, result):
        db = self.db()
        db.add(
            ModelEndpoint(
                name="local",
                base_url="http://127.0.0.1:11434/v1",
                cached_models=json.dumps(["test-model"]),
                enabled=True,
            )
        )
        db.commit()
        db.close()
        return mock.patch("services.llm.simple_complete", new=mock.AsyncMock(return_value=result))

    def test_make_task_keeps_task_defaults(self):
        response = self.client.post("/api/mail/make-task", json={"title": "  Reply to Sam  "})
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        try:
            task = db.get(Task, response.json()["id"])
            self.assertEqual(task.title, "Reply to Sam")
            self.assertEqual(task.stage, "backlog")
            self.assertFalse(task.done)
        finally:
            db.close()

    def test_extracted_timed_event_uses_calendar_creation_rules(self):
        ordinary = self.client.post(
            "/api/calendar", json={"title": "Ordinary", "start_dt": "2026-06-20T09:00"}
        )
        self.assertEqual(ordinary.status_code, 200, ordinary.text)
        result = {
            "found": True,
            "title": "Planning call",
            "start": "2026-06-20T11:00",
            "end": None,
            "location": "Office",
            "all_day": False,
        }
        with self._model(json.dumps(result)):
            response = self.client.post(
                "/api/mail/extract-event",
                json={"subject": "Planning call", "body": "June 20 at 11"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["found"])
        ordinary_event = ordinary.json()
        duration = datetime.fromisoformat(ordinary_event["end_dt"]) - datetime.fromisoformat(
            ordinary_event["start_dt"]
        )
        expected_end = (datetime.fromisoformat(result["start"]) + duration).isoformat()
        self.assertEqual(response.json()["end"], expected_end)
        events = self.client.get("/api/calendar").json()
        extracted = next(event for event in events if event["id"] == response.json()["id"])
        self.assertEqual(extracted["calendar_id"], ordinary.json()["calendar_id"])
        self.assertEqual(extracted["end_dt"], response.json()["end"])
        self.assertEqual(extracted["description"], "from mail — Office")

    def test_invalid_model_date_does_not_save_an_event(self):
        result = {
            "found": True,
            "title": "Broken date",
            "start": "next sometime",
            "end": None,
            "location": "",
            "all_day": False,
        }
        with self._model(json.dumps(result)):
            response = self.client.post(
                "/api/mail/extract-event", json={"subject": "Broken date", "body": "Tomorrow"}
            )
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("model returned invalid event dates", response.json()["detail"])
        db = self.db()
        try:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        finally:
            db.close()

    def test_non_object_model_result_does_not_crash_or_save(self):
        with self._model('[{"found": true}]'):
            response = self.client.post(
                "/api/mail/extract-event", json={"subject": "Broken output", "body": "June 20"}
            )
        self.assertEqual(response.status_code, 502, response.text)
        db = self.db()
        try:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        finally:
            db.close()

    def test_wrong_boolean_type_does_not_make_an_all_day_event(self):
        result = {
            "found": True,
            "title": "Timed meeting",
            "start": "2026-06-20T11:00",
            "end": None,
            "location": "",
            "all_day": "false",
        }
        with self._model(json.dumps(result)):
            response = self.client.post(
                "/api/mail/extract-event", json={"subject": "Timed meeting", "body": "June 20"}
            )
        self.assertEqual(response.status_code, 502, response.text)
        db = self.db()
        try:
            self.assertEqual(db.query(CalendarEvent).count(), 0)
        finally:
            db.close()

    def test_extracted_event_seeds_calendar_on_first_use(self):
        result = {
            "found": True,
            "title": "First event",
            "start": "2026-06-20T11:00",
            "end": "2026-06-20T11:30",
            "location": "",
            "all_day": False,
        }
        with self._model(json.dumps(result)):
            response = self.client.post(
                "/api/mail/extract-event", json={"subject": "First event", "body": "June 20"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        event = next(
            event
            for event in self.client.get("/api/calendar").json()
            if event["id"] == response.json()["id"]
        )
        self.assertEqual(event["calendar_id"], self.client.get("/api/calendars").json()[0]["id"])
        self.assertEqual(event["end_dt"], "2026-06-20T11:30")

    def test_extracted_event_uses_configured_duration(self):
        result = {
            "found": True,
            "title": "Short meeting",
            "start": "2026-06-20T11:00",
            "end": None,
            "location": "",
            "all_day": False,
        }
        with self._model(json.dumps(result)):
            with mock.patch(
                "services.calendar_events.load_settings",
                return_value={"cal_default_duration_min": 30},
            ):
                response = self.client.post(
                    "/api/mail/extract-event", json={"subject": "Short meeting", "body": "June 20"}
                )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["end"], "2026-06-20T11:30:00")
