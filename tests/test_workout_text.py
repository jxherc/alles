"""set text in the owner's words. the cases come from the vault skill workout-logging and the
notation rules at the top of workout.md (pounds, a bare weight is a done set, reps default 10)."""

import asyncio
import unittest
from datetime import date, timedelta

import services.agent_tools as at
from core.database import HabitLog
from services.workout_text import Unclear, describe, parse
from tests._client import ApiTest


def sets(text):
    return parse(text)["sets"]


class SkillExampleTests(unittest.TestCase):
    def test_bare_numbers_are_completed_sets(self):
        # skill: 'a bare number ("55*12", "8 reps of 70") is a completed set'
        self.assertEqual(
            sets("55*12"), [{"weight": 55, "unit": "lb", "reps": 12, "status": "done"}]
        )
        self.assertEqual(
            sets("8 reps of 70"), [{"weight": 70, "unit": "lb", "reps": 8, "status": "done"}]
        )
        self.assertEqual(
            sets("70x10"), [{"weight": 70, "unit": "lb", "reps": 10, "status": "done"}]
        )
        self.assertEqual(sets("70 × 10"), sets("70x10"))

    def test_default_reps_is_ten(self):
        # skill: "default reps = 10 unless Eric says otherwise"; workout.md: a bare weight is done
        self.assertEqual(sets("70"), [{"weight": 70, "unit": "lb", "reps": 10, "status": "done"}])
        self.assertEqual(sets("82.5")[0]["weight"], 82.5)

    def test_next_and_ill_try_are_planned(self):
        # skill: 'Words like "next", "i'll try", "i'll start" mean planned, not done'
        for text in ("next 85", "i'll try 85", "i'll start 85", "Next: 85x8"):
            with self.subTest(text=text):
                one = sets(text)[0]
                self.assertEqual((one["weight"], one["status"]), (85, "planned"))
        self.assertEqual(sets("Next: 85x8")[0]["reps"], 8)

    def test_pounds_unless_stated(self):
        self.assertEqual(sets("70")[0]["unit"], "lb")
        self.assertEqual(sets("30kg x 8")[0]["unit"], "kg")
        self.assertEqual(sets("70 lbs x 10")[0]["unit"], "lb")

    def test_a_side_reported_twice_asks_one_question(self):
        # skill: "right did 10... right did 12" is a mislabeled side: ask "is that left?"
        with self.assertRaises(Unclear) as caught:
            parse("right did 10... right did 12")
        self.assertEqual(str(caught.exception), "is that left?")
        with self.assertRaises(Unclear) as caught:
            parse("left 10 left 12")
        self.assertEqual(str(caught.exception), "is that right?")


class WorkoutNotationTests(unittest.TestCase):
    def test_left_and_right_with_their_own_weights(self):
        expected = [
            {"side": "L", "weight": 60, "unit": "lb", "reps": 12, "status": "done"},
            {"side": "R", "weight": 70, "unit": "lb", "reps": 10, "status": "done"},
        ]
        self.assertEqual(sets("left 60x12 right 70x10"), expected)
        self.assertEqual(sets("left 60 × 12, right 70 × 10"), expected)

    def test_a_shared_weight_with_reps_per_side(self):
        out = parse("15 per hand × left 12, right 10")
        self.assertEqual(out["basis"], "per_hand")
        self.assertEqual(
            [(s["side"], s["weight"], s["reps"]) for s in out["sets"]],
            [("L", 15, 12), ("R", 15, 10)],
        )
        self.assertEqual(
            [(s["side"], s["reps"]) for s in sets("40 × right 10, left 7")], [("R", 10), ("L", 7)]
        )

    def test_approx_reps_and_notes_in_brackets_stay_in_raw(self):
        text = "65; left ~10 (last 3 reps bad), right 12"
        out = parse(text)
        left, right = out["sets"]
        self.assertEqual((left["side"], left["reps"], left["approx"]), ("L", 10, True))
        self.assertEqual((right["side"], right["reps"]), ("R", 12))
        self.assertEqual(out["raw"], text)

    def test_partials_unknowns_and_set_counts(self):
        self.assertEqual(
            sets("100 x 10+5")[0] | {},
            {"weight": 100, "unit": "lb", "reps": 10, "partial": 5, "status": "done"},
        )
        self.assertEqual(sets("85 × ?")[0]["reps"], "?")
        self.assertEqual((sets("? × ?")[0]["weight"], sets("? × ?")[0]["reps"]), ("?", "?"))
        self.assertEqual(sets("85 × 2 sets")[0]["count"], 2)
        self.assertEqual(sets("70x10x3")[0]["count"], 3)
        self.assertEqual([s["reps"] for s in sets("70 × 10/10/10/12")], [10, 10, 10, 12])

    def test_both_sides(self):
        out = parse("15 per hand × 12 both sides")
        self.assertEqual([(s["side"], s["reps"]) for s in out["sets"]], [("L", 12), ("R", 12)])

    def test_assistance_is_help_not_load(self):
        out = parse("30 assistance × 8")
        self.assertEqual(out["sets"], [{"assist": 30, "unit": "lb", "reps": 8, "status": "done"}])
        self.assertEqual(out["basis"], "assist")

    def test_per_side_machines(self):
        self.assertEqual(parse("20 per side × 10")["basis"], "per_side")

    def test_unreadable_text_asks(self):
        for text in ("", "heavy", "did some rows"):
            with self.subTest(text=text), self.assertRaises(Unclear):
                parse(text)

    def test_describe_is_short(self):
        self.assertEqual(describe(sets("55*12")), "55 lb x 12")
        self.assertEqual(
            describe(sets("left 60x12 right 70x10")), "left 60 lb x 12, right 70 lb x 10"
        )
        self.assertEqual(describe(sets("next 85")), "planned 85 lb x 10")


class AideSetLoggingTests(ApiTest):
    """aide logs each reported set at once, as a one-step action (no pi)."""

    def setUp(self):
        super().setUp()
        at.set_agent_ctx({"agent_environment": "general"})
        self.habit = self.client.post("/api/habits", json={"name": "gym", "kind": "workout"}).json()

    def tearDown(self):
        at.set_agent_ctx({})
        super().tearDown()

    def ex(self, args):
        return asyncio.run(at.execute("habit_log", {"id": self.habit["id"]} | args))

    def today(self):
        day = date.today().isoformat()
        card = next(
            c
            for c in self.client.get(f"/api/habits/overview?date_q={day}").json()["habits"]
            if c["id"] == self.habit["id"]
        )
        return card["days"][day]["entries"][0]["values"]["exercises"]

    def test_sets_append_live_with_short_confirmations(self):
        first = self.ex({"exercise": "low row", "sets": "55x10"})
        self.assertEqual(first["output"], "low row set 1: 55 lb x 10. (new, first time)")
        second = self.ex({"exercise": "Low Row", "sets": "70*8"})
        self.assertEqual(second["output"], "low row set 2: 70 lb x 8.")
        split = self.ex({"exercise": "pulldown", "sets": "left 60 × 12, right 70 × 10"})
        self.assertEqual(
            split["output"], "pulldown set 1: left 60 lb x 12, right 70 lb x 10. (new, first time)"
        )
        planned = self.ex({"exercise": "low row", "sets": "next 85"})
        self.assertEqual(planned["output"], "low row set 3: planned 85 lb x 10.")
        row, pulldown = self.today()
        self.assertEqual([s["status"] for s in row["sets"]], ["done", "done", "planned"])
        self.assertEqual(row["sets"][0]["raw"], "55x10")
        self.assertEqual([s["side"] for s in pulldown["sets"]], ["L", "R"])
        self.assertTrue(row["first_time"])

    def test_a_side_reported_twice_asks_and_writes_nothing(self):
        out = self.ex({"exercise": "glute lift", "sets": "right did 10... right did 12"})
        self.assertEqual(out, {"output": "is that left?", "question": True})
        with self.db() as db:
            self.assertEqual(db.query(HabitLog).count(), 0)

    def test_needs_an_exercise_and_a_set_habit(self):
        self.assertTrue(self.ex({"sets": "70x10"})["question"])
        water = self.client.post("/api/habits", json={"name": "water", "kind": "count"}).json()
        out = asyncio.run(at.execute("habit_log", {"id": water["id"], "sets": "70x10"}))
        self.assertTrue(out["error"])

    def test_known_exercise_is_not_first_time(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.client.post(
            f"/api/habits/{self.habit['id']}/toggle",
            json={
                "date": yesterday,
                "data": {"rows": [{"exercise": "lat pulldown", "weight": 70}]},
            },
        )
        out = self.ex({"exercise": "lat pulldown", "sets": "85x9"})
        self.assertEqual(out["output"], "lat pulldown set 1: 85 lb x 9.")


if __name__ == "__main__":
    unittest.main()
