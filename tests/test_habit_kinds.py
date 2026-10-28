import json
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from core.database import HabitLog
from core.migrations import m0076_habit_kinds
from services import habit_kinds
from services.habit_kinds import HabitLogError, clean_log, exercise_names
from tests._client import ApiTest


class CleanLogTests(unittest.TestCase):
    def test_workout_rows_fill_owner_defaults(self):
        data = clean_log(
            "workout",
            {
                "rows": [
                    {"exercise": " lat  pulldown ", "weight": "70", "reps": 10, "sets": 3},
                    {"exercise": "dumbbell press", "weight": 27.5},
                    {"exercise": "push-ups", "weight": None, "reps": "", "note": "slow"},
                ]
            },
        )
        self.assertEqual(
            data["rows"],
            [
                {"exercise": "lat pulldown", "weight": 70, "reps": 10, "sets": 3, "note": ""},
                # a bare weight is one set of 10
                {"exercise": "dumbbell press", "weight": 27.5, "reps": 10, "sets": 1, "note": ""},
                {"exercise": "push-ups", "weight": None, "reps": 10, "sets": 1, "note": "slow"},
            ],
        )

    def test_empty_workout_is_just_done(self):
        self.assertIsNone(clean_log("workout", {"rows": []}))

    def test_workout_refuses_bad_rows(self):
        for rows in (
            [{"exercise": "", "weight": 10}],
            [{"exercise": "squat", "reps": 2.5}],
            [{"exercise": "squat", "sets": 0}],
            [{"exercise": "squat", "weight": -5}],
            [{"exercise": "squat", "weight": True}],
            [{"exercise": "squat", "weight": "heavy"}],
            [{"exercise": "x" * 81}],
            [{"exercise": "squat", "note": "n" * 201}],
            ["squat"],
        ):
            with self.subTest(rows=rows), self.assertRaises(HabitLogError):
                clean_log("workout", {"rows": rows})
        with self.assertRaisesRegex(HabitLogError, "at most 50 rows"):
            clean_log("workout", {"rows": [{"exercise": "squat"}] * 51})

    def test_each_kind_keeps_only_its_fields(self):
        self.assertEqual(
            clean_log("reading", {"amount": 24, "book": "dune", "extra": 1}),
            {"amount": 24, "unit": "pages", "book": "dune"},
        )
        self.assertEqual(
            clean_log("reading", {"amount": "2", "unit": "chapters"}),
            {"amount": 2, "unit": "chapters", "book": ""},
        )
        self.assertEqual(clean_log("count", {"amount": 6}), {"amount": 6})
        self.assertEqual(clean_log("duration", {"minutes": 45}), {"minutes": 45})
        self.assertEqual(
            clean_log("distance", {"distance": 5.25, "unit": "mi", "minutes": ""}),
            {"distance": 5.25, "unit": "mi", "minutes": None},
        )

    def test_kind_fields_refuse_bad_values(self):
        for kind, data in (
            ("reading", {"amount": 10, "unit": "words"}),
            ("reading", {"unit": "pages"}),
            ("count", {"amount": float("inf")}),
            ("count", {}),
            ("duration", {"minutes": 2000}),
            ("distance", {"distance": 5, "unit": "furlongs"}),
            ("distance", {"distance": 5000}),
            ("workout", {"rows": "squat"}),
            ("count", [1]),
        ):
            with self.subTest(kind=kind, data=data), self.assertRaises(HabitLogError):
                clean_log(kind, data)

    def test_check_habits_take_no_details(self):
        self.assertIsNone(clean_log("check", None))
        with self.assertRaisesRegex(HabitLogError, "simple check"):
            clean_log("check", {})

    def test_kinds_and_units(self):
        self.assertEqual(habit_kinds.check_kind(""), "check")
        self.assertEqual(habit_kinds.check_kind("Workout"), "workout")
        with self.assertRaisesRegex(HabitLogError, "doesn't exist"):
            habit_kinds.check_kind("hydration")
        with self.assertRaises(HabitLogError):
            habit_kinds.check_unit("u" * 25)

    def test_exercise_names_newest_first_once(self):
        logs = [
            ("2026-10-20", {"rows": [{"exercise": "squat"}, {"exercise": "Lat Pulldown"}]}),
            ("2026-10-27", {"rows": [{"exercise": "lat pulldown"}, {"exercise": "bench"}]}),
            ("2026-10-25", None),
            ("2026-10-26", {"rows": "broken"}),
        ]
        self.assertEqual(exercise_names(logs), ["lat pulldown", "bench", "squat"])

    def test_unreadable_stored_data_reads_as_none(self):
        self.assertIsNone(habit_kinds.load("{not json"))
        self.assertIsNone(habit_kinds.load("[1, 2]"))
        self.assertEqual(habit_kinds.load('{"amount": 3}'), {"amount": 3})


class HabitKindApiTests(ApiTest):
    def create(self, **body):
        response = self.client.post("/api/habits", json={"name": "habit"} | body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def log(self, hid, day, data=None, **extra):
        body = {"date": day} | extra
        if data is not None:
            body["data"] = data
        return self.client.post(f"/api/habits/{hid}/toggle", json=body)

    def overview_card(self, hid, day):
        cards = self.client.get(f"/api/habits/overview?date_q={day}").json()["habits"]
        return next(card for card in cards if card["id"] == hid)

    def test_create_keeps_kind_and_unit_and_old_habits_are_checks(self):
        water = self.create(name="drink water", kind="count", unit="glasses")
        self.assertEqual((water["kind"], water["unit"]), ("count", "glasses"))
        plain = self.create(name="floss")
        self.assertEqual((plain["kind"], plain["unit"]), ("check", ""))
        refused = self.client.post("/api/habits", json={"name": "x", "kind": "hydration"})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["detail"], "that habit type doesn't exist")

    def test_workout_log_marks_the_day_and_shows_details(self):
        today = date.today()
        day = today.isoformat()
        habit = self.create(name="workout", kind="workout")
        saved = self.log(
            habit["id"], day, {"rows": [{"exercise": "lat pulldown", "weight": 70, "sets": 3}]}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["done"], True)
        self.assertEqual(saved.json()["data"]["rows"][0]["reps"], 10)
        card = self.overview_card(habit["id"], day)
        self.assertTrue(card["done_today"])
        self.assertEqual(card["logs"][day]["rows"][0]["exercise"], "lat pulldown")
        self.assertEqual(card["exercises"], ["lat pulldown"])

        # saving again edits the same day: one row, new details
        self.log(habit["id"], day, {"rows": [{"exercise": "squat", "weight": 135}]})
        with self.db() as db:
            rows = db.query(HabitLog).filter_by(habit_id=habit["id"]).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0].data)["rows"][0]["exercise"], "squat")

        # un-marking the day drops its details
        off = self.log(habit["id"], day, done=False)
        self.assertEqual(off.json(), {"done": False, "date": day})
        card = self.overview_card(habit["id"], day)
        self.assertFalse(card["done_today"])
        self.assertEqual(card["logs"], {})

    def test_logs_cover_two_weeks_and_names_cover_all_history(self):
        today = date.today()
        habit = self.create(name="workout", kind="workout")
        old = (today - timedelta(days=30)).isoformat()
        recent = (today - timedelta(days=3)).isoformat()
        self.log(habit["id"], old, {"rows": [{"exercise": "deadlift", "weight": 225}]})
        self.log(habit["id"], recent, {"rows": [{"exercise": "row", "weight": 60}]})
        card = self.overview_card(habit["id"], today.isoformat())
        self.assertEqual(list(card["logs"]), [recent])
        self.assertEqual(card["exercises"], ["row", "deadlift"])

    def test_bad_details_are_refused_and_nothing_is_marked(self):
        day = date.today().isoformat()
        check = self.create(name="floss")
        refused = self.log(check["id"], day, {"amount": 1})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(
            refused.json()["detail"], "this habit is a simple check and has no log details"
        )
        reading = self.create(name="read", kind="reading")
        refused = self.log(reading["id"], day, {"amount": -3})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["detail"], "these log details don't fit this habit")
        for hid in (check["id"], reading["id"]):
            self.assertFalse(self.overview_card(hid, day)["done_today"])

    def test_plain_toggle_still_works_for_logged_kinds(self):
        day = date.today().isoformat()
        habit = self.create(name="read", kind="reading")
        self.assertEqual(self.log(habit["id"], day).json()["done"], True)
        card = self.overview_card(habit["id"], day)
        self.assertTrue(card["done_today"])
        self.assertEqual(card["logs"], {})

    def test_create_retry_compares_kind(self):
        body = {
            "name": "water",
            "kind": "count",
            "unit": "glasses",
            "request_id": "6f1c1f3e-58a5-4a39-9d1b-9a4f3f2f0a11",
        }
        first = self.client.post("/api/habits", json=body)
        again = self.client.post("/api/habits", json=body)
        self.assertEqual(first.json()["id"], again.json()["id"])
        changed = self.client.post("/api/habits", json=body | {"kind": "duration"})
        self.assertEqual(changed.status_code, 409)


class HabitKindsMigrationTests(unittest.TestCase):
    def test_old_tables_gain_columns_and_rows_read_as_before(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE habits (id VARCHAR PRIMARY KEY, name VARCHAR)"))
            conn.execute(
                text(
                    "CREATE TABLE habit_logs (id INTEGER PRIMARY KEY, habit_id VARCHAR, date VARCHAR)"
                )
            )
            conn.execute(text("INSERT INTO habits VALUES ('h1', 'floss')"))
            conn.execute(text("INSERT INTO habit_logs VALUES (1, 'h1', '2026-10-27')"))
            m0076_habit_kinds.up(conn)
            m0076_habit_kinds.up(conn)  # twice changes nothing
            self.assertEqual(
                conn.execute(text("SELECT kind, unit FROM habits")).fetchall(), [("check", "")]
            )
            self.assertEqual(
                conn.execute(text("SELECT data FROM habit_logs")).fetchall(), [(None,)]
            )

    def test_missing_tables_are_left_alone(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            m0076_habit_kinds.up(conn)
            self.assertEqual(
                conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall(),
                [],
            )


if __name__ == "__main__":
    unittest.main()
