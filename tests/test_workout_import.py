"""the workout.md importer on a synthetic log in the same three table formats (never the
owner's real rows): preview, a year the owner confirms, apply, skip on re-import, undo."""

import unittest
from pathlib import Path

from core.database import HabitLog
from services import habit_kinds, workout_import
from tests._client import ApiTest

FIXTURE = (Path(__file__).parent / "fixtures" / "workout_log.md").read_text("utf-8")


def table_rows(text):
    return [
        line.strip()
        for line in text.splitlines()
        if line.startswith("|")
        and not line.startswith("| exercise")
        and not line.startswith("| ---")
    ]


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.parsed = workout_import.parse(FIXTURE)
        self.sessions = self.parsed["sessions"]

    def exercise(self, session, name):
        return next(e for e in self.sessions[session]["exercises"] if e["name"] == name)

    def test_sessions_groups_and_dates(self):
        self.assertEqual(
            [(s["group"], s["heading"], s["date"], s["needs_year"]) for s in self.sessions],
            [
                ("back", "mar 3", None, True),
                ("back", "apr 9 2025", "2025-04-09", False),
                ("legs", "apr 12 2025", "2025-04-12", False),
            ],
        )
        self.assertEqual(self.sessions[2]["note"], "session: finished")
        self.assertEqual(self.parsed["problems"], [])

    def test_every_row_is_kept_word_for_word(self):
        raws = [
            s["raw"]
            for session in self.sessions
            for e in session["exercises"]
            for s in e["sets"]
            if "raw" in s
        ]
        self.assertEqual(raws, table_rows(FIXTURE))

    def test_recorded_rows(self):
        cable = self.exercise(0, "cable row")["sets"]
        self.assertEqual(
            [(s["weight"], s["reps"], s.get("count", 1)) for s in cable], [(30, 12, 1), (40, 12, 2)]
        )
        pulldown = self.exercise(0, "wide pulldown")["sets"]
        self.assertEqual([s["reps"] for s in pulldown], [12, 10, 10])
        self.assertEqual(pulldown[2]["partial"], 4)
        self.assertEqual([s.get("note") for s in pulldown[1:]], ["(1.5 after)", "(0.5)"])
        rope = self.exercise(0, "rope pullover")["sets"]
        self.assertEqual(rope[1]["status"], "unfinished")
        self.assertEqual(rope[0]["note"], "grip slipped")

    def test_reps_rows(self):
        row = self.exercise(1, "chest supported row")["sets"]
        self.assertEqual(
            [(s["weight"], s["reps"], s.get("count", 1)) for s in row], [(40, 10, 1), (45, 8, 2)]
        )
        self.assertEqual(self.exercise(1, "straight arm pulldown")["sets"][0]["weight"], "?")

    def test_set_rows_sides_unknowns_and_states(self):
        step = self.exercise(2, "step up (台阶上步)")
        self.assertEqual(step["setup"], {"basis": "per_hand"})
        self.assertEqual(
            [(s["side"], s["reps"]) for s in step["sets"]],
            [("L", 12), ("R", 10), ("L", 11), ("R", 11)],
        )
        press = self.exercise(2, "single leg press")["sets"]
        self.assertEqual([(s["side"], s["weight"]) for s in press[:2]], [("L", 90), ("R", 100)])
        self.assertTrue(press[2]["approx"])
        dip = self.exercise(2, "assisted dip")["sets"][0]
        self.assertEqual((dip["assist"], "weight" in dip), (50, False))
        hack = self.exercise(2, "hack squat")
        self.assertTrue(hack["first_time"])
        self.assertEqual(
            [(s["status"], s["reps"]) for s in hack["sets"]], [("failed", "?"), ("done", 10)]
        )
        self.assertEqual(hack["sets"][1]["count"], 2)
        curl = self.exercise(2, "leg curl")["sets"][0]
        self.assertEqual((curl["status"], curl["count"], curl["partial"]), ("planned", 2, 5))
        unknown = self.exercise(2, "unlabeled entry")["sets"][0]
        self.assertEqual((unknown["weight"], unknown["reps"]), ("?", "?"))
        self.assertEqual([s["reps"] for s in self.exercise(2, "calf raise")["sets"]], [15, 15, 12])
        machine = self.exercise(2, "machine dip")["sets"][0]
        self.assertEqual((machine["assist"], machine["reps"], "weight" in machine), (30, 8, False))
        warmup = self.exercise(2, "easy row")["sets"][0]
        self.assertEqual(
            (warmup["type"], "weight" in warmup, "reps" in warmup), ("warmup", False, False)
        )

    def test_every_session_fits_a_workout_log(self):
        for session in self.sessions:
            doc = {"v": 2, "entries": [workout_import.entry(session, "imp-x")]}
            self.assertTrue(habit_kinds.clean_log("workout", doc))

    def test_a_year_is_never_guessed(self):
        with self.assertRaises(workout_import.WorkoutImportError):
            workout_import.session_date(self.sessions[0])
        self.assertEqual(workout_import.session_date(self.sessions[0], 2025), "2025-03-03")

    def test_empty_or_huge_text_is_refused(self):
        for text in ("", "   ", "x" * (workout_import.MAX_TEXT + 1)):
            with self.subTest(size=len(text)), self.assertRaises(workout_import.WorkoutImportError):
                workout_import.parse(text)


class ImportApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.habit = self.client.post("/api/habits", json={"name": "gym", "kind": "workout"}).json()
        self.url = f"/api/habits/{self.habit['id']}/import"

    def rows(self):
        with self.db() as db:
            return {
                log.date: log.data
                for log in db.query(HabitLog).filter_by(habit_id=self.habit["id"]).all()
            }

    def test_preview_writes_nothing(self):
        preview = self.client.post(f"{self.url}/preview", json={"text": FIXTURE})
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertTrue(body["needs_year"])
        self.assertEqual(len(body["sessions"]), 3)
        self.assertEqual(body["sets"], 28)
        self.assertEqual(self.rows(), {})

    def test_apply_needs_the_year_then_undo_restores_everything(self):
        # a day that was already logged by hand keeps its own entry through import and undo
        before = {
            "v": 2,
            "entries": [
                {
                    "id": "mine",
                    "values": {
                        "exercises": [{"name": "bench", "sets": [{"weight": 95, "reps": 5}]}]
                    },
                }
            ],
        }
        self.client.post(
            f"/api/habits/{self.habit['id']}/toggle", json={"date": "2025-04-12", "data": before}
        )
        kept = self.rows()["2025-04-12"]

        refused = self.client.post(self.url, json={"text": FIXTURE})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["detail"], "pick the year for the sessions without one")
        self.assertEqual(set(self.rows()), {"2025-04-12"})

        applied = self.client.post(self.url, json={"text": FIXTURE, "year": 2025})
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual((applied.json()["sessions"], applied.json()["skipped"]), (3, 0))
        self.assertEqual(set(self.rows()), {"2025-03-03", "2025-04-09", "2025-04-12"})
        cards = self.client.get("/api/habits/overview?date_q=2025-04-12").json()["habits"]
        day = next(c for c in cards if c["id"] == self.habit["id"])["days"]["2025-04-12"]
        self.assertEqual([e["id"] for e in day["entries"]][0], "mine")
        self.assertEqual(day["entries"][1]["values"]["muscles"], ["legs"])

        again = self.client.post(self.url, json={"text": FIXTURE, "year": 2025})
        self.assertEqual((again.json()["sessions"], again.json()["skipped"]), (0, 3))
        preview = self.client.post(
            f"{self.url}/preview", json={"text": FIXTURE, "year": 2025}
        ).json()
        self.assertTrue(all(s["already"] for s in preview["sessions"]))

        undone = self.client.post(f"{self.url}/{applied.json()['batch']}/undo")
        self.assertEqual(undone.json()["removed"], 3)
        self.assertEqual(self.rows(), {"2025-04-12": kept})

    def test_only_workout_habits_import(self):
        water = self.client.post("/api/habits", json={"name": "water", "kind": "count"}).json()
        refused = self.client.post(
            f"/api/habits/{water['id']}/import/preview", json={"text": FIXTURE}
        )
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(
            self.client.post("/api/habits/nope/import", json={"text": FIXTURE}).status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
