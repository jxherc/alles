from tests._client import ApiTest


class CalendarImportValidationTests(ApiTest):
    def test_malformed_calendar_never_imports_a_partial_file(self):
        good = "BEGIN:VEVENT\nSUMMARY:keep whole file\nDTSTART:20261016T090000\nEND:VEVENT\n"
        for content in [
            "not a calendar",
            "BEGIN:VCALENDAR\n" + good,
            "BEGIN:VCALENDAR\n"
            + good
            + "BEGIN:VEVENT\nDTSTART:20261340T090000\nEND:VEVENT\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:bad date\nDTSTART:nonsense\nEND:VEVENT\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:bad end\nDTSTART:20261016T090000\nDTEND:20261015T090000\nEND:VEVENT\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:invalid end\nDTSTART:20261016T090000\nDTEND:20261316T100000\nEND:VEVENT\nEND:VCALENDAR",
        ]:
            with self.subTest(content=content):
                response = self.client.post("/api/calendar/import", json={"ics": content})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.client.get("/api/calendar").json(), [])

    def test_empty_calendar_is_valid_and_a_repaired_file_can_be_retried(self):
        empty = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        response = self.client.post("/api/calendar/import", json={"ics": empty})
        self.assertEqual(response.json(), {"imported": 0, "first_only": 0})
        repaired = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:repaired\nDTSTART:20261016T090000\nDTEND:20261016T100000\nEND:VEVENT\nEND:VCALENDAR"
        response = self.client.post("/api/calendar/import", json={"ics": repaired})
        self.assertEqual(response.json(), {"imported": 1, "first_only": 0})
        self.assertEqual(self.client.get("/api/calendar").json()[0]["title"], "repaired")
