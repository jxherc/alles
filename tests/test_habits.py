from datetime import date

from routes.habits import build_grid, completion_pct, daily_streak, week_done_count
from tests._client import ApiTest


class HabitLogicTests(ApiTest):
    def test_daily_streak_consecutive(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-20", "2026-06-19", "2026-06-18"}
        self.assertEqual(daily_streak(dates, today), 3)

    def test_daily_streak_grace_for_today(self):
        # today not yet done, but a run ending yesterday still counts
        today = date(2026, 6, 20)
        dates = {"2026-06-19", "2026-06-18"}
        self.assertEqual(daily_streak(dates, today), 2)

    def test_daily_streak_broken_by_gap(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-20", "2026-06-18", "2026-06-17"}  # missed the 19th
        self.assertEqual(daily_streak(dates, today), 1)

    def test_daily_streak_zero_when_stale(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-10"}
        self.assertEqual(daily_streak(dates, today), 0)

    def test_week_done_count_window(self):
        today = date(2026, 6, 20)
        dates = {
            "2026-06-20",
            "2026-06-18",
            "2026-06-14",
            "2026-06-13",
        }  # 13th is outside 7-day window
        self.assertEqual(week_done_count(dates, today), 3)

    def test_completion_pct_weekly_capped(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-20", "2026-06-19", "2026-06-18", "2026-06-17"}  # 4 done
        self.assertEqual(completion_pct("weekly", 3, dates, today), 100)  # 4/3 capped

    def test_completion_pct_weekly_partial(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-20", "2026-06-19"}
        self.assertEqual(completion_pct("weekly", 4, dates, today), 50)  # 2/4

    def test_completion_pct_daily(self):
        today = date(2026, 6, 20)
        dates = {"2026-06-20", "2026-06-19", "2026-06-18"}  # 3 of last 7
        self.assertEqual(completion_pct("daily", 1, dates, today), 43)  # round(3/7*100)

    def test_build_grid_length_and_order(self):
        today = date(2026, 6, 20)
        grid = build_grid({"2026-06-20"}, today, 7)
        self.assertEqual(len(grid), 7)
        self.assertEqual(grid[-1]["date"], "2026-06-20")  # newest last
        self.assertTrue(grid[-1]["done"])
        self.assertFalse(grid[0]["done"])


class HabitApiTests(ApiTest):
    def _create(self, **kw):
        body = {"name": "Read", "cadence": "daily"}
        body.update(kw)
        return self.client.post("/api/habits", json=body)

    def test_create_returns_id(self):
        r = self._create()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["id"])
        self.assertEqual(r.json()["name"], "Read")

    def test_create_requires_name(self):
        self.assertEqual(self.client.post("/api/habits", json={"name": "  "}).status_code, 400)

    def test_create_rejects_bad_cadence(self):
        self.assertEqual(self._create(cadence="hourly").status_code, 400)

    def test_toggle_marks_done_then_undone(self):
        hid = self._create().json()["id"]
        r1 = self.client.post(f"/api/habits/{hid}/toggle", json={"date": "2026-06-20"})
        self.assertTrue(r1.json()["done"])
        r2 = self.client.post(f"/api/habits/{hid}/toggle", json={"date": "2026-06-20"})
        self.assertFalse(r2.json()["done"])

    def test_toggle_idempotent_no_duplicate_logs(self):
        hid = self._create().json()["id"]
        for _ in range(3):
            self.client.post(f"/api/habits/{hid}/toggle", json={"date": "2026-06-20"})
        # 3 toggles → on/off/on → done, exactly one log
        ov = self.client.get("/api/habits/overview").json()
        h = next(x for x in ov["habits"] if x["id"] == hid)
        self.assertTrue(h["done_today"] is True or any(g["done"] for g in h["grid"]))

    def test_overview_shape(self):
        hid = self._create(name="Water").json()["id"]
        self.client.post(f"/api/habits/{hid}/toggle", json={"date": date.today().isoformat()})
        h = next(
            x for x in self.client.get("/api/habits/overview").json()["habits"] if x["id"] == hid
        )
        for k in ("streak", "pct", "grid", "done_today", "week_done"):
            self.assertIn(k, h)
        self.assertTrue(h["done_today"])
        self.assertGreaterEqual(h["streak"], 1)

    def test_patch_updates(self):
        hid = self._create().json()["id"]
        r = self.client.patch(f"/api/habits/{hid}", json={"name": "Read 30m", "target": 5})
        self.assertEqual(r.json()["name"], "Read 30m")
        self.assertEqual(r.json()["target"], 5)

    def test_delete_removes(self):
        hid = self._create().json()["id"]
        self.assertEqual(self.client.delete(f"/api/habits/{hid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/habits/{hid}").status_code, 404)

    def test_archived_excluded_from_overview(self):
        hid = self._create(name="Old").json()["id"]
        self.client.patch(f"/api/habits/{hid}", json={"archived": True})
        ids = [x["id"] for x in self.client.get("/api/habits/overview").json()["habits"]]
        self.assertNotIn(hid, ids)
