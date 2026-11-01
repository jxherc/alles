"""one exercise's last time, records and the one tier progression hint (track E3)."""

import json
import unittest

from services.habit_logs import exercise_history
from tests._client import ApiTest

PULLDOWN = "hammer strength front mts pulldown"


def day(*exercises):
    return {"v": 2, "entries": [{"id": "e1", "values": {"exercises": list(exercises)}}]}


def ex(sets, name=PULLDOWN, **extra):
    return {"name": name, "sets": sets, **extra}


def s(weight, reps, **extra):
    return {"weight": weight, "unit": "lb", "reps": reps, "status": "done", "count": 1} | extra


class ExerciseHistoryTests(unittest.TestCase):
    def test_last_time_is_the_newest_day_before_today_with_the_same_setup(self):
        logs = [
            ("2026-10-12", day(ex([s(55, 10)]))),
            ("2026-10-19", day(ex([s(60, 12, side="L"), s(70, 10, side="R")]))),
            ("2026-10-20", day(ex([s(90, 8)], setup={"grip": "reverse"}))),
            ("2026-10-26", day(ex([s(65, 10)]))),
        ]
        out = exercise_history(logs, PULLDOWN.upper(), {}, "2026-10-26")
        self.assertEqual(out["last"]["date"], "2026-10-19")
        self.assertEqual([one["side"] for one in out["last"]["sets"]], ["L", "R"])
        # a reverse grip press is another movement: its history stays apart
        grip = exercise_history(logs, PULLDOWN, {"grip": "reverse"}, "2026-10-26")
        self.assertEqual(grip["last"]["date"], "2026-10-20")
        self.assertEqual(grip["records"][""]["heaviest"]["weight"], 90)
        self.assertIsNone(exercise_history(logs, "lat pulldown", {}, "2026-10-26")["last"])

    def test_records_per_side_skip_warmups_and_unfinished_sets(self):
        logs = [
            ("2026-10-19", day(ex([s(60, 12, side="L"), s(70, 10, side="R")]))),
            (
                "2026-10-22",
                day(ex([s(100, 10, type="warmup"), s(80, 3, side="R", status="failed"),
                        s(65, 12, side="L"), s(65, 6, side="R")])),
            ),
        ]  # fmt: skip
        records = exercise_history(logs, PULLDOWN, {}, "2026-10-30")["records"]
        self.assertNotIn("", records)  # the warm up is the only both sides set
        self.assertEqual(records["L"]["heaviest"]["weight"], 65)
        self.assertEqual(records["R"]["heaviest"]["weight"], 70)  # the failed 80 doesn't count
        self.assertEqual(records["R"]["e1rm"]["value"], round(70 * (1 + 10 / 30), 1))
        self.assertEqual(
            [(r["weight"], r["reps"]) for r in records["R"]["reps_at"]], [(70, 10), (65, 6)]
        )
        self.assertEqual(records["L"]["volume"]["lb"], 65 * 12)
        # warm ups count once the habit says so
        counted = exercise_history(logs, PULLDOWN, {}, "2026-10-30", {"warmups_count": True})
        self.assertEqual(counted["records"][""]["heaviest"]["weight"], 100)

    def test_count_and_units_reach_volume_and_unknowns_never_count(self):
        logs = [("2026-10-01", day(ex([s(20, 10, unit="kg", count=3), s("?", "?")])))]
        records = exercise_history(logs, PULLDOWN, {}, "2026-10-02")["records"][""]
        self.assertEqual(
            records["heaviest"], {"weight": 20, "unit": "kg", "reps": 10, "date": "2026-10-01"}
        )
        self.assertAlmostEqual(
            records["volume"]["lb"], round(20 * 2.20462262 * 10 * 3, 1), places=0
        )

    def test_hint_only_within_about_a_week_with_every_rep_done(self):
        good = [
            (
                "2026-10-19",
                day(ex([s(50, 10, type="warmup"), s(60, 12, side="L"), s(70, 10, side="R")])),
            )
        ]
        hint = exercise_history(good, PULLDOWN, {}, "2026-10-26")["hint"]
        self.assertEqual(
            [(h["side"], h["from"], h["to"]) for h in hint], [("L", 60, 65), ("R", 70, 75)]
        )
        self.assertIsNone(exercise_history(good, PULLDOWN, {}, "2026-10-28")["hint"])  # 9 days
        stepped = exercise_history(good, PULLDOWN, {}, "2026-10-20", {"weight_step": 2.5})["hint"]
        self.assertEqual(stepped[0]["to"], 62.5)
        for spoiled in (
            s(70, 10, side="R", bad=3),
            s(70, 10, side="R", status="attempted"),
            s("?", 10, side="R"),
        ):
            logs = [("2026-10-19", day(ex([s(60, 12, side="L"), spoiled])))]
            self.assertIsNone(exercise_history(logs, PULLDOWN, {}, "2026-10-26")["hint"], spoiled)


class ExerciseHistoryApiTests(ApiTest):
    def test_the_route_reads_the_habit_logs(self):
        habit = self.client.post("/api/habits", json={"name": "gym", "kind": "workout"}).json()
        doc = day(ex([s(60, 12, side="L"), s(70, 10, side="R")], setup={"basis": "per_side"}))
        saved = self.client.post(
            f"/api/habits/{habit['id']}/toggle", json={"date": "2026-10-19", "data": doc}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        url = f"/api/habits/{habit['id']}/exercise"
        params = {
            "name": PULLDOWN,
            "setup": json.dumps({"basis": "per_side"}),
            "date_q": "2026-10-26",
        }
        out = self.client.get(url, params=params).json()
        self.assertEqual(out["last"]["date"], "2026-10-19")
        self.assertEqual(len(out["hint"]), 2)
        self.assertIsNone(self.client.get(url, params={"name": PULLDOWN}).json()["last"])
        self.assertEqual(self.client.get(url, params={**params, "setup": "[1]"}).status_code, 400)
        self.assertEqual(
            self.client.get("/api/habits/nope/exercise", params=params).status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
