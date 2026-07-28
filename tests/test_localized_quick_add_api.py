from unittest.mock import patch

from tests._client import ApiTest


class LocalizedQuickAddApiTests(ApiTest):
    def test_task_quick_add_uses_the_active_interface_language(self):
        with patch("routes.tasks.load_settings", return_value={"language": "fr"}):
            response = self.client.post("/api/tasks/quick", json={"text": "appeler maman demain"})
        self.assertEqual(response.status_code, 200)
        task = response.json()
        self.assertEqual(task["title"], "appeler maman")
        self.assertTrue(task["due_date"])

    def test_calendar_quick_add_uses_the_active_interface_language(self):
        with patch("routes.calendar.load_settings", return_value={"language": "zh-Hans"}):
            response = self.client.post(
                "/api/calendar/quick",
                json={"text": "会议 明天 下午3点30分 持续2小时"},
            )
        self.assertEqual(response.status_code, 200)
        event = response.json()
        self.assertEqual(event["title"], "会议")
        self.assertIn("T15:30", event["start_dt"])
        self.assertIn("T17:30", event["end_dt"])
