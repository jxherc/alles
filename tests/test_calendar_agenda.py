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

    def test_open_tasks_sit_on_their_day_and_overdue_ones_lead_today(self):
        today = date.today()
        add = lambda title, due, **extra: self.client.post(  # noqa: E731
            "/api/tasks", json={"title": title, "due_date": due, **extra}
        )
        add("old bill", (today - timedelta(days=5)).isoformat())
        add("older bill", (today - timedelta(days=9)).isoformat() + "T08:00")
        add("finished", (today - timedelta(days=2)).isoformat(), stage="done")
        add("due soon", (today + timedelta(days=2)).isoformat())
        add("too far", (today + timedelta(days=40)).isoformat())
        add("no date", None)
        d = self.client.get("/api/calendar/agenda?days=30").json()
        self.assertEqual(d["today"], today.isoformat())
        # oldest first, like home; a done task is never overdue
        self.assertEqual([t["title"] for t in d["overdue"]], ["older bill", "old bill"])
        self.assertEqual(d["overdue"][0]["due"], (today - timedelta(days=9)).isoformat())
        # today shows up for them even with nothing else on it
        self.assertEqual(d["days"][0]["date"], today.isoformat())
        by_day = {g["date"]: [t["title"] for t in g["tasks"]] for g in d["days"]}
        self.assertEqual(by_day[(today + timedelta(days=2)).isoformat()], ["due soon"])
        self.assertNotIn("too far", [t for titles in by_day.values() for t in titles])
        # the same overdue list home shows
        home = self.client.get("/api/today", params={"date": today.isoformat()}).json()
        self.assertEqual(
            [t["title"] for t in home["tasks"]["overdue"]], [t["title"] for t in d["overdue"]]
        )

    def test_a_repeating_multi_day_event_covers_each_of_its_days(self):
        start = date.today() - timedelta(days=8)
        self._create(
            title="trip",
            start_dt=start.isoformat(),
            end_dt=(start + timedelta(days=2)).isoformat(),
            all_day=True,
            recurrence="weekly",
            recur_count=4,
        )
        d = self.client.get("/api/calendar/agenda?days=30").json()
        seen = [
            (g["date"], bool(e.get("continued")))
            for g in d["days"]
            for e in g["events"]
            if e["title"] == "trip"
        ]
        want = []
        for week in range(4):
            first = start + timedelta(days=7 * week)
            for i in range(3):
                day = first + timedelta(days=i)
                if day >= date.today():
                    want.append((day.isoformat(), i > 0))
        self.assertEqual(sorted(seen), want)
