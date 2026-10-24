from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import event

from services import calendar_events
from tests._client import ApiTest, db

CalendarEvent = db.CalendarEvent
_TORONTO = {"timezone": "America/Toronto"}


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

    def legacy(self, **values):
        """an old row that kept its offset; new writes are stored naive."""
        body = {
            "title": "series",
            "start_dt": "2026-09-25T13:00:00Z",
            "end_dt": "2026-09-25T14:00:00Z",
            "recurrence": "daily",
            "recur_count": 5,
            **values,
        }
        d = self.db()
        row = CalendarEvent(**calendar_events.event_columns(body))
        d.add(row)
        d.commit()
        eid = row.id
        d.close()
        return next(r for r in self.rows() if r["id"] == eid)

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

    def test_all_day_inclusive_and_zoned_instants_land_on_wall_time(self):
        response = self.client.post(
            "/api/calendar?time_zone=America%2FToronto",
            json={
                "title": "zoned",
                "start_dt": "2026-09-26T02:30:00Z",
                "end_dt": "2026-09-26T03:30:15Z",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()
        self.assertEqual(original["start_dt"], "2026-09-25T22:30:00")
        self.assertEqual(original["end_dt"], "2026-09-25T23:30:15")
        changed = self.client.patch(
            f"/api/calendar/{original['id']}", json={"description": "only prose"}
        ).json()
        self.assertEqual(changed["start_dt"], original["start_dt"])
        self.assertEqual(changed["end_dt"], original["end_dt"])
        # an edit that leaves the times alone leaves a kept offset alone, whatever the zone
        old = self.legacy(start_dt="2026-09-26T02:30:00Z", end_dt="2026-09-26T03:30:00Z")
        kept = self.client.patch(
            f"/api/calendar/{old['id']}?time_zone=America%2FToronto",
            json={"description": "only prose"},
        ).json()
        self.assertEqual(kept["start_dt"], "2026-09-26T02:30:00Z")
        self.assertEqual(kept["end_dt"], "2026-09-26T03:30:00Z")
        self.create(
            title="all day", all_day=True, start_dt="2026-09-25", end_dt="2026-09-25", recurrence=""
        )

    def test_zoned_writes_store_wall_time_and_free_time_reads_old_rows(self):
        with patch("services.calendar_events.load_settings", return_value=_TORONTO):
            made = self.client.post(
                "/api/calendar",
                json={
                    "title": "call",
                    "start_dt": "2026-11-10T15:00:00Z",
                    "end_dt": "2026-11-10T16:00:00Z",
                },
            )
            self.assertEqual(made.status_code, 200, made.text)
            self.assertEqual(made.json()["start_dt"], "2026-11-10T10:00:00")
            self.legacy(
                title="old import",
                start_dt="2026-11-11T15:00:00+00:00",
                end_dt="2026-11-11T16:00:00+00:00",
                recurrence="",
                recur_count=None,
            )
            self.legacy(
                title="old standup",
                start_dt="2026-11-02T18:00:00Z",
                end_dt="2026-11-02T18:30:00Z",
                recur_count=None,
            )
            first = self.client.get("/api/calendar/free", params={"date": "2026-11-10"})
            second = self.client.get("/api/calendar/free", params={"date": "2026-11-11"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(
            first.json()["slots"],
            [
                {"start": "2026-11-10T09:00", "end": "2026-11-10T10:00"},
                {"start": "2026-11-10T11:00", "end": "2026-11-10T13:00"},
                {"start": "2026-11-10T13:30", "end": "2026-11-10T18:00"},
            ],
        )
        self.assertEqual(
            second.json()["slots"],
            [
                {"start": "2026-11-11T09:00", "end": "2026-11-11T10:00"},
                {"start": "2026-11-11T11:00", "end": "2026-11-11T13:00"},
                {"start": "2026-11-11T13:30", "end": "2026-11-11T18:00"},
            ],
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
        original = self.legacy(start_dt="2026-09-25T13:00:00Z", end_dt="2026-09-25T14:00:00Z")
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
        original = self.legacy(
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
        # fridays 13:00 utc in the offset's own frame are 08:00 in toronto after the change;
        # 14:00z is a new time picked in toronto, so it becomes toronto's wall time
        self.assertEqual(response.json()["start_dt"], "2026-11-06T09:00:00")

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

        original = self.legacy(
            # sunday in utc, its own frame: saturday 23:30 in toronto
            start_dt="2026-11-01T03:30:05.123Z",
            end_dt="2026-11-01T07:30:05.123Z",
            recurrence="weekly",
            recur_byday="SU",
            recur_count=2,
        )
        response = self.client.patch(
            f"/api/calendar/{original['id']}?scope=this&occ=2026-11-07&time_zone=America%2FToronto",
            json={"description": "only prose"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        child = response.json()
        # times untouched: the occurrence keeps its own moment (sundays 03:30 utc, saturday
        # 22:30 in toronto after the change) and four real hours
        self.assertEqual(child["start_dt"], "2026-11-08T03:30:05.123000+00:00")
        self.assertEqual(child["end_dt"], "2026-11-08T07:30:05.123000+00:00")
        self.assertEqual(
            (
                datetime.fromisoformat(child["end_dt"]) - datetime.fromisoformat(child["start_dt"])
            ).total_seconds(),
            4 * 3600,
        )

    def test_scoped_aware_end_crosses_spring_gap_by_elapsed_duration(self):
        original = self.legacy(
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
        # 06:30 utc is 01:30 est; an hour later is 03:30 edt
        self.assertEqual(response.json()["start_dt"], "2026-03-08T06:30:00+00:00")
        self.assertEqual(response.json()["end_dt"], "2026-03-08T07:30:00+00:00")


class CalendarServiceWallTimeTest(ApiTest):
    """every writer goes through the service, so all of them store wall time"""

    def test_create_event_stores_wall_time_for_any_writer(self):
        import asyncio

        from services import agent_tools, calendar_events

        d = self.db()
        try:
            made = calendar_events.create_event(
                d,
                {
                    "title": "browser",
                    "start_dt": "2026-11-10T15:00:00Z",
                    "end_dt": "2026-11-10T16:00:00Z",
                },
                time_zone="America/Toronto",
            )
            self.assertEqual(
                (made.start_dt, made.end_dt), ("2026-11-10T10:00:00", "2026-11-10T11:00:00")
            )
            with patch("services.calendar_events.load_settings", return_value=_TORONTO):
                made = calendar_events.create_event(
                    d, {"title": "capture", "start_dt": "2026-07-10T15:00:00+00:00"}
                )
            # summer, so -4, and the default hour is added after the conversion
            self.assertEqual(made.start_dt, "2026-07-10T11:00:00")
            self.assertTrue(made.end_dt.startswith("2026-07-10T"))
            # a naive or all-day value is already wall time and stays as sent
            made = calendar_events.create_event(
                d, {"title": "naive", "start_dt": "2026-07-10T09:30", "end_dt": "2026-07-10T10:00"}
            )
            self.assertEqual((made.start_dt, made.end_dt), ("2026-07-10T09:30", "2026-07-10T10:00"))
        finally:
            d.close()
        with patch("services.calendar_events.load_settings", return_value=_TORONTO):
            out = asyncio.run(
                agent_tools._calendar_create(
                    {
                        "title": "aide",
                        "start_dt": "2026-11-10T20:00:00Z",
                        "end_dt": "2026-11-10T21:00:00Z",
                    }
                )
            )
        self.assertNotIn("error", out, out)
        aide = next(row for row in self.rows() if row["title"] == "aide")
        self.assertEqual(
            (aide["start_dt"], aide["end_dt"]), ("2026-11-10T15:00:00", "2026-11-10T16:00:00")
        )

    def rows(self):
        return self.client.get("/api/calendar").json()

    def test_validation_reads_plainly(self):
        from fastapi import HTTPException

        from services import calendar_events

        for data, detail in (
            ({"title": " ", "start_dt": "2026-07-10"}, "an event needs a title"),
            ({"title": "x", "start_dt": "soon"}, "use a real start and end date"),
        ):
            with self.subTest(detail=detail), self.assertRaises(HTTPException) as caught:
                calendar_events.validate_event(data)
            self.assertEqual(caught.exception.detail, detail)


class CalendarWallTimeMigrationTest(ApiTest):
    """zoned rows are kept as stored and read at the owner's wall time; only an explicit
    timezone setting lets m0074 rewrite them at upgrade"""

    toronto = {"x-alles-time-zone": "America/Toronto"}
    tokyo = {"x-alles-time-zone": "Asia/Tokyo"}

    def tearDown(self):
        from core.settings import save_settings

        save_settings({"detected_timezone": ""})  # a remembered zone mustn't leak into other tests
        super().tearDown()

    def seed(self, rows):
        d = self.db()
        ids = []
        for row in rows:
            event = CalendarEvent(**calendar_events.event_columns({"title": "x", **row}))
            d.add(event)
            d.commit()
            ids.append(event.id)
        d.close()
        return ids

    def stored(self, eid):
        d = self.db()
        try:
            row = d.get(CalendarEvent, eid)
            return row.start_dt, row.end_dt
        finally:
            d.close()

    def migrate(self, settings):
        from core.migrations import m0074_calendar_wall_times as m0074

        with patch("core.settings.load_settings", return_value=settings):
            with self.eng.begin() as conn:
                m0074.up(conn)

    def test_migration_moves_zoned_rows_to_the_set_timezone_once(self):
        zoned, plain_offset, naive, all_day, fold, one_sided = self.seed(
            [
                {"start_dt": "2026-11-10T15:00:00Z", "end_dt": "2026-11-10T16:00:00+00:00"},
                {"start_dt": "2026-07-10T09:00:00-0700", "end_dt": None},
                {"start_dt": "2026-07-10T09:30", "end_dt": "2026-07-10T10:00"},
                {"start_dt": "2026-07-10", "end_dt": "2026-07-11", "all_day": True},
                # 1:30 edt to 1:30 est: the same wall clock, an hour apart
                {"start_dt": "2026-11-01T05:30:00Z", "end_dt": "2026-11-01T06:30:00Z"},
                {"start_dt": "2026-07-10T15:00:00Z", "end_dt": "2026-07-10T10:30"},
            ]
        )
        for _ in range(2):  # idempotent: the second run finds nothing to change
            self.migrate(_TORONTO)
            self.assertEqual(self.stored(zoned), ("2026-11-10T10:00:00", "2026-11-10T11:00:00"))
            self.assertEqual(self.stored(plain_offset), ("2026-07-10T12:00:00", None))
            self.assertEqual(self.stored(naive), ("2026-07-10T09:30", "2026-07-10T10:00"))
            self.assertEqual(self.stored(all_day), ("2026-07-10", "2026-07-11"))
            self.assertEqual(self.stored(fold), ("2026-11-01T01:30:00", "2026-11-01T02:30:00"))
            self.assertEqual(self.stored(one_sided), ("2026-07-10T11:00:00", "2026-07-10T12:00:00"))

    def test_migration_leaves_repeating_rows_in_their_own_frame(self):
        rows = [
            # sunday 01:00 utc is saturday 21:00 in toronto: moving only the start would make
            # every occurrence a day late
            {"start_dt": "2026-11-01T01:00:00Z", "end_dt": "2026-11-01T02:00:00Z",
             "recurrence": "weekly", "recur_byday": "SU", "recur_count": 4},
            {"start_dt": "2026-10-30T02:00:00Z", "end_dt": "2026-10-30T03:00:00Z",
             "recurrence": "daily", "recur_until": "2026-11-05", "recur_except": ["2026-11-02"]},
            {"start_dt": "2026-12-01T03:00:00Z", "end_dt": "2026-12-01T04:00:00Z",
             "recurrence": "monthly", "recur_count": 3},
        ]  # fmt: skip
        ids = self.seed(rows)
        before = [self.stored(eid) for eid in ids]
        tor = ZoneInfo("America/Toronto")
        weekly = calendar_events.event_dict(self.db().get(CalendarEvent, ids[0]))
        seen = calendar_events.occurrence_starts(
            weekly, datetime(2026, 10, 1), datetime(2026, 12, 1), tor
        )
        for _ in range(2):  # idempotent
            self.migrate(_TORONTO)
            self.assertEqual([self.stored(eid) for eid in ids], before)
        # and they still read on toronto's days: saturdays at 21:00, then 20:00 after the change
        self.assertEqual(
            [s.isoformat() for s in seen],
            [
                "2026-10-31T21:00:00",
                "2026-11-07T20:00:00",
                "2026-11-14T20:00:00",
                "2026-11-21T20:00:00",
            ],
        )

    def test_a_blank_setting_rewrites_nothing_at_upgrade(self):
        (eid,) = self.seed([{"start_dt": "2026-03-08T07:30:00Z", "end_dt": None}])
        for blank in ({"timezone": ""}, {}, {"timezone": "Not/AZone"}):
            self.migrate(blank)
            self.assertEqual(self.stored(eid), ("2026-03-08T07:30:00Z", None))

    def test_requests_never_rewrite_a_kept_offset_whatever_zone_they_bring(self):
        (eid,) = self.seed([{"start_dt": "2026-03-08T07:30:00Z", "end_dt": "2026-03-08T08:30:00Z"}])
        with patch("services.calendar_events.load_settings", return_value={"timezone": ""}):
            for headers in ({}, self.toronto, self.tokyo, self.toronto):
                self.client.get("/api/calendar", headers=headers)
                self.client.get("/api/calendar/agenda", headers=headers)
                self.client.get("/api/calendar/conflicts", headers=headers)
                self.client.get(
                    "/api/calendar/free", params={"date": "2026-03-08"}, headers=headers
                )
        self.assertEqual(self.stored(eid), ("2026-03-08T07:30:00Z", "2026-03-08T08:30:00Z"))

    def test_blank_setting_utc_server_toronto_browser_reads_3_30(self):
        import os
        import time

        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        try:
            with patch("services.calendar_events.load_settings", return_value={"timezone": ""}):
                # an api client sends Z with no zone: the offset is kept, nothing is guessed
                made = self.client.post(
                    "/api/calendar",
                    json={"title": "api", "start_dt": "2026-03-08T07:30:00Z", "end_dt": None},
                ).json()
                self.assertEqual(made["start_dt"], "2026-03-08T07:30:00Z")
                free = self.client.get(
                    "/api/calendar/free", params={"date": "2026-03-08"}, headers=self.toronto
                ).json()["slots"]
                slots = self.client.get(
                    "/api/calendar/free-slots",
                    params={"day": "2026-03-08", "day_start": "00:00", "day_end": "12:00"},
                    headers=self.toronto,
                ).json()["slots"]
            # 07:30Z is 03:30 in toronto that morning (edt began at 2:00): busy 3:30 to 4:30
            self.assertEqual(slots[0], {"start": "00:00", "end": "03:30"})
            self.assertEqual(slots[1]["start"], "04:30")
            self.assertTrue(all(slot["start"] >= "2026-03-08T09:00" for slot in free))
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_every_endpoint_reads_an_old_zoned_row_at_the_same_wall_time(self):
        from datetime import date, datetime, timedelta
        from zoneinfo import ZoneInfo

        day = date.today() + timedelta(days=1)
        d = day.isoformat()
        # a weekly 14:00Z meeting from an old import, on a day in the coming week
        self.seed(
            [
                {
                    "title": "old weekly",
                    "start_dt": f"{d}T14:00:00Z",
                    "end_dt": f"{d}T15:00:00Z",
                    "recurrence": "weekly",
                }
            ]
        )
        self.client.post(
            "/api/calendar",
            json={"title": "new local", "start_dt": f"{d}T09:30", "end_dt": f"{d}T10:30"},
        )
        local = datetime.fromisoformat(f"{d}T14:00:00+00:00").astimezone(
            ZoneInfo("America/Toronto")
        )
        local = local.replace(tzinfo=None)
        busy_from, busy_to = local.strftime("%H:%M"), (local + timedelta(hours=1)).strftime("%H:%M")
        with patch("services.calendar_events.load_settings", return_value={"timezone": ""}):
            agenda = self.client.get(
                "/api/calendar/agenda", params={"days": 3}, headers=self.toronto
            ).json()["days"]
            free = self.client.get(
                "/api/calendar/free", params={"date": d}, headers=self.toronto
            ).json()["slots"]
            slots = self.client.get(
                "/api/calendar/free-slots", params={"day": d}, headers=self.toronto
            ).json()["slots"]
            clash = self.client.get("/api/calendar/conflicts", headers=self.toronto).json()
        old = [
            e for g in agenda if g["date"] == d for e in g["events"] if e["title"] == "old weekly"
        ]
        self.assertEqual(old[0]["start_dt"], local.isoformat())
        self.assertIn({"start": f"{d}T{busy_to}", "end": f"{d}T18:00"}, free)
        for slot in slots:
            self.assertFalse(slot["start"] < busy_to and slot["end"] > busy_from, (slot, busy_from))
        # 14:00Z is 09:00 or 10:00 in toronto, so it overlaps the 09:30 local event
        self.assertEqual(clash["conflicts"], [{"a": "old weekly", "b": "new local"}])


class OwnerZoneTest(ApiTest):
    """one owner zone for background work: the setting, else the last browser zone seen"""

    def tearDown(self):
        from core.settings import save_settings

        save_settings({"detected_timezone": ""})
        super().tearDown()

    def test_zone_order_and_remembering(self):
        from core.settings import load_settings

        with patch("services.calendar_events.load_settings", return_value={"timezone": ""}):
            self.assertIsNone(calendar_events.owner_zone())
            self.assertIsNone(calendar_events.write_zone())
            self.assertEqual(calendar_events.owner_zone("Asia/Tokyo").key, "Asia/Tokyo")
        # a request with a real zone is remembered, once, and only that
        self.client.get("/api/calendar", headers={"x-alles-time-zone": "America/Toronto"})
        self.assertEqual(load_settings().get("detected_timezone"), "America/Toronto")
        self.client.get("/api/calendar", headers={"x-alles-time-zone": "Not/AZone"})
        self.client.get("/api/calendar")
        self.assertEqual(load_settings().get("detected_timezone"), "America/Toronto")
        self.assertEqual(calendar_events.owner_zone().key, "America/Toronto")
        # but it never decides a write: with no setting an offset is still kept
        self.assertIsNone(calendar_events.write_zone())
        # the setting always wins
        with patch(
            "services.calendar_events.load_settings",
            return_value={"timezone": "Europe/London", "detected_timezone": "America/Toronto"},
        ):
            self.assertEqual(calendar_events.owner_zone().key, "Europe/London")
            self.assertEqual(calendar_events.write_zone().key, "Europe/London")

    def test_booking_slots_read_a_zoned_row_and_never_crash(self):
        from datetime import date, timedelta

        d = (date.today() + timedelta(days=2)).isoformat()
        s = self.db()
        page = db.BookingPage(token="tok123", work_start=9, work_end=17, duration_min=60)
        s.add(page)
        s.add(
            CalendarEvent(
                title="caldav", start_dt=f"{d}T14:00:00+00:00", end_dt=f"{d}T15:00:00+00:00"
            )
        )
        s.add(CalendarEvent(title="local", start_dt=f"{d}T09:00", end_dt=f"{d}T10:00"))
        s.commit()
        page = s.query(db.BookingPage).first()
        with patch(
            "services.calendar_events.load_settings",
            return_value={"timezone": "", "detected_timezone": "America/Toronto"},
        ):
            slots = calendar_events.compute_booking_slots(s, page, d)
        s.close()
        starts = [slot["start"][11:16] for slot in slots]
        self.assertNotIn("09:00", starts)
        # 14:00Z is 9 or 10 in toronto: that hour is busy, 14:00 itself is free
        self.assertIn("14:00", starts)

    def test_today_and_the_aide_listing_read_a_zoned_row_at_wall_time(self):
        import asyncio
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from services import agent_tools

        tor = ZoneInfo("America/Toronto")
        noon = datetime.now(tor).replace(hour=12, minute=0, second=0, microsecond=0)
        stamp = noon.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        s = self.db()
        s.add(CalendarEvent(title="zoned lunch", start_dt=stamp, end_dt=None))
        s.commit()
        s.close()
        today = self.client.get(
            "/api/today", params={"date": noon.date().isoformat(), "timezone": "America/Toronto"}
        ).json()
        events = today["sections"]["today"]["events"]
        self.assertEqual([(e["title"], e["time"]) for e in events], [("zoned lunch", "12:00")])
        with patch(
            "services.calendar_events.load_settings",
            return_value={"timezone": "America/Toronto"},
        ):
            listing = asyncio.run(agent_tools._calendar_list("", ""))
        self.assertIn(f"{noon.date().isoformat()}T12:00:00", listing["output"])
