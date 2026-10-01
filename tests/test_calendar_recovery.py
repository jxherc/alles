from sqlalchemy import event

from tests._client import ApiTest, db

CalendarEvent = db.CalendarEvent


class CalendarRecoveryTest(ApiTest):
    def create(self, **values):
        body = {
            "title": "series",
            "start_dt": "2026-09-25T09:00",
            "end_dt": "2026-09-25T10:00",
            "recurrence": "daily",
            "recur_count": 5,
            **values,
        }
        response = self.client.post("/api/calendar", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rows(self):
        return self.client.get("/api/calendar").json()

    def test_invalid_end_does_not_mutate(self):
        original = self.create()
        response = self.client.patch(
            f"/api/calendar/{original['id']}", json={"title": "lost", "end_dt": "2026-09-24T10:00"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows(), [original])
        self.assertEqual(
            self.client.post("/api/calendar", json={"title": "bad", "start_dt": "bad"}).status_code,
            400,
        )

    def test_all_day_inclusive_and_aware_instants_remain_exact(self):
        original = self.create(
            start_dt="2026-09-26T02:30:00Z", end_dt="2026-09-26T03:30:00Z", recurrence=""
        )
        changed = self.client.patch(
            f"/api/calendar/{original['id']}", json={"description": "only prose"}
        ).json()
        self.assertEqual(changed["start_dt"], original["start_dt"])
        self.assertEqual(changed["end_dt"], original["end_dt"])
        self.create(
            title="all day", all_day=True, start_dt="2026-09-25", end_dt="2026-09-25", recurrence=""
        )

    def test_this_scope_commits_master_and_replacement(self):
        original = self.create()
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-09-27",
            json={"title": "single", "start_dt": "2026-09-27T11:00", "end_dt": "2026-09-27T12:00"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertNotEqual(saved["id"], original["id"])
        self.assertEqual(saved["recurrence"], "")
        self.assertIsNone(saved["recur_count"])
        master = next(row for row in self.rows() if row["id"] == original["id"])
        self.assertEqual(master["recur_except"], ["2026-09-27"])
        self.assertEqual(master["start_dt"], original["start_dt"])
        retry = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-09-27", json={"title": "again"}
        )
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(len(self.rows()), 2)

    def test_following_scope_preserves_remaining_count_and_exceptions(self):
        original = self.create(recur_except=["2026-09-26", "2026-09-29"])
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=following&occ=2026-09-28",
            json={
                "title": "following",
                "start_dt": "2026-09-28T09:00",
                "end_dt": "2026-09-28T10:00",
                "recur_count": 5,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertEqual(child["recur_count"], 2)
        self.assertEqual(child["recur_except"], ["2026-09-29"])
        master = next(row for row in self.rows() if row["id"] == original["id"])
        self.assertEqual(master["recur_until"], "2026-09-27")
        self.assertEqual(master["recur_count"], 5)

    def test_failed_this_and_following_inserts_roll_back_master(self):
        original = self.create()

        def fail_insert(*_args):
            raise RuntimeError("synthetic insert failure")

        for scope in ["this", "following"]:
            with self.subTest(scope=scope):
                event.listen(CalendarEvent, "before_insert", fail_insert)
                try:
                    with self.assertRaisesRegex(RuntimeError, "synthetic insert failure"):
                        self.client.patch(
                            f"/api/calendar/{original['id']}?scope={scope}&occ=2026-09-27",
                            json={
                                "title": "replacement",
                                "start_dt": "2026-09-27T09:00",
                                "end_dt": "2026-09-27T10:00",
                            },
                        )
                finally:
                    event.remove(CalendarEvent, "before_insert", fail_insert)
                self.assertEqual(self.rows(), [original])

    def test_invalid_scope_day_and_timezone_do_not_change_series(self):
        original = self.create(start_dt="2026-09-25T13:00:00Z", end_dt="2026-09-25T14:00:00Z")
        for query in [
            "scope=bad",
            "scope=this&occ=bad",
            "scope=this&occ=2026-10-10",
            "scope=this&occ=2026-09-26&time_zone=Invalid/Zone",
        ]:
            self.assertIn(
                self.client.patch(
                    f"/api/calendar/{original['id']}?{query}", json={"title": "changed"}
                ).status_code,
                [400, 409],
            )
            self.assertEqual(self.rows(), [original])

    def test_aware_recurrence_index_uses_selected_zone_across_dst(self):
        original = self.create(
            start_dt="2026-10-30T13:00:00Z",
            end_dt="2026-10-30T14:00:00Z",
            recurrence="weekly",
            recur_byday="FR",
            recur_count=3,
        )
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=following&occ=2026-11-06&time_zone=America%2FToronto",
            json={
                "title": "DST following",
                "start_dt": "2026-11-06T14:00:00.000Z",
                "end_dt": "2026-11-06T15:00:00.000Z",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["recur_count"], 2)
        self.assertEqual(response.json()["start_dt"], "2026-11-06T14:00:00.000Z")

    def test_description_only_scoped_patch_uses_the_occurrence_dates(self):
        original = self.create()
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-09-27",
            json={"description": "only prose"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["start_dt"], "2026-09-27T09:00:00")
        self.assertEqual(response.json()["end_dt"], "2026-09-27T10:00:00")
        self.assertEqual(
            next(row for row in self.rows() if row["id"] == original["id"])["start_dt"],
            original["start_dt"],
        )

    def test_scoped_aware_duration_and_precision_across_fall_clock_change(self):
        from datetime import datetime

        original = self.create(
            start_dt="2026-11-01T03:30:05.123Z",
            end_dt="2026-11-01T07:30:05.123Z",
            recurrence="weekly",
            recur_byday="SA",
            recur_count=2,
        )
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-11-07&time_zone=America%2FToronto",
            json={"description": "only prose"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        self.assertEqual(child["start_dt"], "2026-11-07T23:30:05.123000-05:00")
        self.assertEqual(child["end_dt"], "2026-11-08T03:30:05.123000-05:00")
        self.assertEqual(
            (
                datetime.fromisoformat(child["end_dt"]) - datetime.fromisoformat(child["start_dt"])
            ).total_seconds(),
            4 * 3600,
        )

    def test_scoped_aware_end_crosses_spring_gap_by_elapsed_duration(self):
        original = self.create(
            start_dt="2026-03-01T06:30:00Z",
            end_dt="2026-03-01T07:30:00Z",
            recurrence="weekly",
            recur_byday="SU",
            recur_count=2,
        )
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-03-08&time_zone=America%2FToronto",
            json={"description": "only prose"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["start_dt"], "2026-03-08T01:30:00-05:00")
        self.assertEqual(response.json()["end_dt"], "2026-03-08T03:30:00-04:00")
