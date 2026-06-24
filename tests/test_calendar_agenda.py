"""audit fix: the agenda must expand recurring events (a weekly event whose master start is in
the past still has upcoming occurrences) instead of querying start_dt directly."""

from datetime import date, timedelta

from tests._client import ApiTest


class CalendarAgendaTests(ApiTest):
    def _create(self, **body):
        return self.client.post("/api/calendar", json=body).json()

    def test_agenda_expands_recurring_master_in_past(self):
        start = (date.today() - timedelta(days=14)).isoformat() + "T09:00:00"
        self._create(title="Standup", start_dt=start, recurrence="weekly")
        d = self.client.get("/api/calendar/agenda?days=30").json()
        titles = [e["title"] for g in d["days"] for e in g["events"]]
        self.assertIn("Standup", titles)  # recurring occurrences project into the window
        for g in d["days"]:
            self.assertGreaterEqual(g["date"], date.today().isoformat())

    def test_agenda_still_lists_one_off(self):
        when = (date.today() + timedelta(days=3)).isoformat() + "T14:00:00"
        self._create(title="Dentist", start_dt=when)
        d = self.client.get("/api/calendar/agenda?days=30").json()
        titles = [e["title"] for g in d["days"] for e in g["events"]]
        self.assertIn("Dentist", titles)
