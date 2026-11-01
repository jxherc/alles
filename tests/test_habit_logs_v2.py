"""habit logs v2: every kind's shape, the gym logger's sets, slips and skips, field setups,
m0078 on a v1 database, and the api around them."""

import json
import unittest
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from core.database import Habit, HabitLog
from core.migrations import m0076_habit_kinds, m0078_habit_fields
from services import habit_kinds
from services.habit_kinds import HabitLogError, clean_log, legacy_view
from tests._client import ApiTest

MEASURE_UNITS = {
    "weight": "kg",
    "height": "cm",
    "distance": "mi",
    "liquid": "floz",
    "body": "in",
    "temperature": "f",
}


def sample(field):
    """a valid, filled value for one field."""
    kind = field["type"]
    if kind in ("number", "seconds"):
        return field.get("max", 1000) if field.get("whole") else min(field.get("max", 50), 50) / 2
    if kind == "count":
        return min(field.get("max", 1_000_000), 12)
    if kind == "minutes":
        return 42.5
    if kind == "rating":
        return field.get("max", 5)
    if kind == "clock":
        return "06:45"
    if kind == "date":
        return "2026-11-01"
    if kind == "measure":
        return {"value": 12.5, "unit": MEASURE_UNITS[field["measure"]]}
    if kind == "yesno":
        return True
    if kind == "choice":
        return field["options"][-1]
    if kind == "tags":
        return ["a", "b"]
    if kind == "text":
        return "as written"
    if kind == "link":
        return {"app": "contacts", "id": "c1", "text": "mom"}
    if kind == "people":
        return [{"text": "sam"}, {"app": "contacts", "id": "c2", "text": "alex"}]
    if kind == "checklist":
        return [{"item": "washed", "done": True}, {"item": "folded", "done": False}]
    if kind == "files":
        return ["files/one.jpg"]
    if kind == "rows":
        row = {column["key"]: sample(column) for column in field["columns"]}
        rows = [row]
        if field.get("sides"):
            rows = [dict(row, side="L"), dict(row, side="R")]
        return rows
    if kind == "sets":
        return [{"weight": 20, "unit": "lb", "reps": 8, "side": "L"}, {"reps": "?", "side": "R"}]
    if kind == "exercises":
        return [{"name": "lat pulldown", "sets": [{"weight": 70, "unit": "lb", "reps": 10}]}]
    raise AssertionError(kind)


class EveryKindShapeTests(unittest.TestCase):
    def test_catalog_has_sixty_kinds_and_every_kind_has_fields(self):
        self.assertEqual(len(habit_kinds.CATALOG), 60)
        self.assertEqual(len(set(habit_kinds.CATALOG)), 60)
        listed = habit_kinds.kinds()
        for kind in habit_kinds.KINDS:
            with self.subTest(kind=kind):
                self.assertIn(kind, listed)
                keys = [field["key"] for field in listed[kind]["fields"]]
                self.assertEqual(len(keys), len(set(keys)), "a field key repeats")
                self.assertIn("mood", keys)

    def test_every_field_of_every_kind_stores_and_round_trips(self):
        for kind in habit_kinds.KINDS:
            values = {field["key"]: sample(field) for field in habit_kinds.all_fields(kind)}
            doc = {
                "v": 2,
                "entries": [
                    {
                        "id": "e1",
                        "time": "07:30",
                        "values": values,
                        "note": "felt good",
                        "raw": "  70 x 10  ",
                        "tags": ["morning"],
                        "photos": ["files/p.jpg"],
                    }
                ],
            }
            with self.subTest(kind=kind):
                cleaned = clean_log(kind, doc)
                self.assertEqual(cleaned["v"], 2)
                entry = cleaned["entries"][0]
                self.assertEqual(set(entry["values"]), set(values))
                self.assertEqual(entry["raw"], "  70 x 10  ", "raw is kept word for word")
                self.assertEqual(clean_log(kind, cleaned), cleaned, "cleaning twice changes it")
                json.dumps(cleaned)

    def test_every_number_and_time_can_be_unknown(self):
        scalar = ("number", "count", "minutes", "seconds", "rating", "clock")
        for kind in habit_kinds.KINDS:
            for field in habit_kinds.all_fields(kind):
                if field["type"] not in scalar:
                    continue
                with self.subTest(kind=kind, field=field["key"]):
                    doc = {"v": 2, "entries": [{"values": {field["key"]: "?"}}]}
                    self.assertEqual(
                        clean_log(kind, doc)["entries"][0]["values"], {field["key"]: "?"}
                    )

    def test_every_field_refuses_a_value_of_the_wrong_shape(self):
        wrong = {
            "number": "lots",
            "seconds": -1,
            "count": 2.5,
            "minutes": 2000,
            "rating": 11,
            "clock": "25:00",
            "date": "2026-02-30",
            "measure": 12,
            "yesno": "yes",
            "choice": "none of these",
            "tags": "a",
            "text": 5,
            "link": 5,
            "people": "sam",
            "checklist": "laundry",
            "files": [""],
            "rows": {"a": 1},
            "sets": [{"reps": 1.5}],
            "exercises": [{"name": ""}],
        }
        for kind in habit_kinds.KINDS:
            for field in habit_kinds.all_fields(kind):
                with self.subTest(kind=kind, field=field["key"]):
                    doc = {"v": 2, "entries": [{"values": {field["key"]: wrong[field["type"]]}}]}
                    with self.assertRaises(HabitLogError):
                        clean_log(kind, doc)

    def test_unknown_field_keys_and_entry_keys_are_refused(self):
        for doc in (
            {"v": 2, "entries": [{"values": {"made_up": 1}}]},
            {"v": 2, "entries": [{"values": {}, "colour": "red"}]},
            {"v": 2, "entries": "x"},
            {"v": 2, "entries": [{"id": "a"}, {"id": "a"}]},
            {"v": 2, "entries": [{}] * 51},
        ):
            with self.subTest(doc=str(doc)[:60]), self.assertRaises(HabitLogError):
                clean_log("run", doc)

    def test_empty_entries_mean_just_done(self):
        self.assertIsNone(clean_log("run", {"v": 2, "entries": []}))

    def test_one_entry_a_day_kinds(self):
        two = {"v": 2, "entries": [{"values": {"steps": 9000}}, {"values": {"steps": 100}}]}
        with self.assertRaisesRegex(HabitLogError, "one entry a day"):
            clean_log("steps", two)
        drinks = [
            {"time": "08:00", "values": {"drink": "tea"}},
            {"time": "12:00", "values": {"drink": "water"}},
        ]
        self.assertEqual(len(clean_log("water", {"v": 2, "entries": drinks})["entries"]), 2)

    def test_measures_keep_the_unit_as_entered(self):
        doc = {
            "v": 2,
            "entries": [{"values": {"amount": {"value": 8, "unit": "oz"}, "drink": "tea"}}],
        }
        self.assertEqual(
            clean_log("water", doc)["entries"][0]["values"]["amount"], {"value": 8, "unit": "floz"}
        )
        for bad in (
            6,
            {"value": 6},
            {"value": 6, "unit": "kg"},
            {"value": 6, "unit": "ml", "x": 1},
        ):
            with self.subTest(bad=bad), self.assertRaises(HabitLogError):
                clean_log("water", {"v": 2, "entries": [{"values": {"amount": bad}}]})


class GymShapeTests(unittest.TestCase):
    def log(self, *exercises):
        doc = {"v": 2, "entries": [{"id": "s", "values": {"exercises": list(exercises)}}]}
        return clean_log("workout", doc)["entries"][0]["values"]["exercises"]

    def test_per_side_weights_and_set_counts(self):
        # "left 60 x 12, right 70 x 10", then the right side does one more set
        [exercise] = self.log(
            {
                "name": "hammer strength front mts pulldown",
                "setup": {"basis": "per_hand", "machine": "hammer strength"},
                "unilateral": True,
                "sets": [
                    {"side": "left", "weight": 60, "reps": 12},
                    {"side": "R", "weight": 70, "reps": 10, "count": 2},
                ],
            }
        )
        left = [s for s in exercise["sets"] if s["side"] == "L"]
        right = [s for s in exercise["sets"] if s["side"] == "R"]
        self.assertEqual((left[0]["weight"], left[0]["reps"], left[0]["count"]), (60, 12, 1))
        self.assertEqual((right[0]["weight"], right[0]["reps"], right[0]["count"]), (70, 10, 2))
        self.assertEqual(exercise["setup"], {"machine": "hammer strength", "basis": "per_hand"})
        self.assertTrue(exercise["unilateral"])

    def test_partials_bad_reps_unknowns_and_states(self):
        [exercise] = self.log(
            {
                "name": "seated row",
                "sets": [
                    {"weight": 100, "reps": 10, "partial": 5},
                    {"weight": 65, "reps": 10, "approx": True, "bad": 3, "side": "L"},
                    {"weight": "?", "reps": "?", "status": "attempted"},
                    {"weight": 85, "status": "planned"},
                    {"weight": 7.5, "status": "unfinished", "type": "failure", "rpe": 9.5},
                    {"assist": 45, "reps": 8, "unit": "lb"},
                    {"seconds": 30, "type": "warmup", "rest": 90, "tempo": "3-1-1"},
                ],
            }
        )
        sets = exercise["sets"]
        self.assertEqual((sets[0]["reps"], sets[0]["partial"]), (10, 5))
        self.assertEqual((sets[1]["approx"], sets[1]["bad"]), (True, 3))
        self.assertEqual(
            (sets[2]["weight"], sets[2]["reps"], sets[2]["status"]), ("?", "?", "attempted")
        )
        self.assertNotIn("reps", sets[3], "a planned set without reps stays without reps")
        self.assertEqual(sets[4]["type"], "failure")
        self.assertEqual((sets[5]["assist"], sets[5]["unit"]), (45, "lb"))
        self.assertEqual(sets[6]["tempo"], "3-1-1")

    def test_kg_is_kept_and_any_mass_unit_is_named(self):
        [exercise] = self.log(
            {"name": "row", "unit": "kgs", "sets": [{"weight": 40, "unit": "kilos"}]}
        )
        self.assertEqual((exercise["unit"], exercise["sets"][0]["unit"]), ("kg", "kg"))

    def test_bad_sets_are_refused(self):
        for one in (
            {"side": "middle"},
            {"type": "giant"},
            {"status": "maybe"},
            {"weight": 3000},
            {"weight": 10, "unit": "km"},
            {"count": 0},
            {"reps": -1},
            {"rpe": 11},
            {"colour": "red"},
        ):
            with self.subTest(one=one), self.assertRaises(HabitLogError):
                self.log({"name": "row", "sets": [one]})
        with self.assertRaises(HabitLogError):
            self.log({"name": "row", "setup": {"basis": "per_foot"}})

    def test_bodyweight_kinds_share_the_set_logger(self):
        for kind in ("pushups", "squats", "pullups"):
            doc = {
                "v": 2,
                "entries": [
                    {"values": {"sets": [{"reps": 12, "side": "L"}, {"reps": 10, "side": "R"}]}}
                ],
            }
            with self.subTest(kind=kind):
                sets = clean_log(kind, doc)["entries"][0]["values"]["sets"]
                self.assertEqual([(s["side"], s["reps"]) for s in sets], [("L", 12), ("R", 10)])


class LegacyTests(unittest.TestCase):
    def test_v1_converts_without_losing_a_value(self):
        cases = {
            "workout": {
                "rows": [{"exercise": "squat", "weight": 135, "reps": 8, "sets": 3, "note": "deep"}]
            },
            "reading": {"amount": 30, "unit": "chapters", "book": "dune"},
            "count": {"amount": 6},
            "duration": {"minutes": 25},
            "distance": {"distance": 5.5, "unit": "mi", "minutes": 50},
        }
        for kind, old in cases.items():
            with self.subTest(kind=kind):
                doc = clean_log(kind, old)
                self.assertTrue(habit_kinds.is_v2(doc))
                self.assertEqual(legacy_view(kind, doc), old)

    def test_new_kinds_take_only_v2(self):
        with self.assertRaises(HabitLogError):
            clean_log("run", {"distance": 5, "unit": "km"})

    def test_an_old_screen_save_keeps_side_detail_of_rows_it_did_not_change(self):
        stored = clean_log(
            "workout",
            {
                "v": 2,
                "entries": [
                    {
                        "id": "s",
                        "values": {
                            "exercises": [
                                {
                                    "name": "pulldown",
                                    "raw": "left 60 × 12, right 70 × 10",
                                    "sets": [
                                        {"side": "L", "weight": 60, "reps": 12},
                                        {"side": "R", "weight": 70, "reps": 10},
                                    ],
                                },
                                {"name": "row", "sets": [{"weight": 55, "reps": 10}]},
                            ]
                        },
                    }
                ],
            },
        )
        same = clean_log("workout", legacy_view("workout", stored))
        self.assertEqual(habit_kinds.merge_v1("workout", stored, same), stored)
        edited = legacy_view("workout", stored)
        edited["rows"][-1]["weight"] = 60
        merged = habit_kinds.merge_v1("workout", stored, clean_log("workout", edited))
        exercises = merged["entries"][0]["values"]["exercises"]
        self.assertEqual(exercises[0]["raw"], "left 60 × 12, right 70 × 10")
        self.assertEqual(exercises[-1]["sets"][0]["weight"], 60)


class FieldSetupTests(unittest.TestCase):
    def test_custom_fields_defaults_and_targets(self):
        config = habit_kinds.check_fields(
            "protein",
            {
                "on": ["grams", "meal", "c_brand"],
                "custom": [
                    {
                        "key": "c_brand",
                        "label": "brand",
                        "type": "choice",
                        "options": ["Optimum", "Kirkland"],
                    }
                ],
                "defaults": {"meal": "shake"},
                "targets": {"grams": {"min": 90, "max": 110, "period": "day"}},
                "scale": 10,
                "units": {"weight": "kg"},
                "sensitive": True,
                "weight_step": 2.5,
            },
        )
        self.assertEqual(config["custom"][0]["options"], ("optimum", "kirkland"))
        self.assertEqual(config["targets"]["grams"], {"period": "day", "min": 90, "max": 110})
        entry = {"values": {"grams": 30, "c_brand": "kirkland", "mood": 9}}
        stored = clean_log("protein", {"v": 2, "entries": [entry]}, config)
        self.assertEqual(stored["entries"][0]["values"]["c_brand"], "kirkland")
        with self.assertRaises(HabitLogError):
            clean_log("protein", {"v": 2, "entries": [entry]})  # no setup: c_brand is unknown

    def test_bad_setups_are_refused(self):
        for config in (
            {"on": ["nope"]},
            {"custom": [{"key": "brand", "label": "x", "type": "text"}]},
            {"custom": [{"key": "c_x", "label": "x", "type": "sets"}]},
            {"custom": [{"key": "c_x", "label": "x", "type": "text"}] * 2},
            {"targets": {"grams": {"min": 120, "max": 90}}},
            {"targets": {"grams": {}}},
            {"scale": 7},
            {"units": {"weight": "stone"}},
            {"mode": "sometimes"},
            {"anything": 1},
        ):
            with self.subTest(config=config), self.assertRaises(HabitLogError):
                habit_kinds.check_fields("protein", config)


class HabitApiV2Tests(ApiTest):
    def create(self, **body):
        response = self.client.post("/api/habits", json={"name": "habit"} | body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def log(self, hid, day, data=None, **extra):
        body = {"date": day} | extra
        if data is not None:
            body["data"] = data
        return self.client.post(f"/api/habits/{hid}/toggle", json=body)

    def card(self, hid, day):
        cards = self.client.get(f"/api/habits/overview?date_q={day}").json()["habits"]
        return next(card for card in cards if card["id"] == hid)

    def test_an_older_day_comes_along_when_asked(self):
        habit = self.create(name="workout", kind="workout")
        today = date.today()
        old = (today - timedelta(days=40)).isoformat()
        sets = [{"weight": 60, "unit": "lb", "reps": 10, "status": "done", "count": 1}]
        doc = {"v": 2, "entries": [{"values": {"exercises": [{"name": "row", "sets": sets}]}}]}
        self.assertEqual(self.log(habit["id"], old, doc).status_code, 200)
        self.assertNotIn(old, self.card(habit["id"], today.isoformat())["days"])
        url = f"/api/habits/overview?date_q={today.isoformat()}&log_day={old}"
        card = next(c for c in self.client.get(url).json()["habits"] if c["id"] == habit["id"])
        self.assertEqual(card["days"][old]["entries"][0]["values"]["exercises"][0]["name"], "row")
        bad = self.client.get("/api/habits/overview?log_day=soon")
        self.assertEqual(bad.status_code, 400)

    def test_kinds_route_lists_every_kind(self):
        kinds = self.client.get("/api/habits/kinds").json()["kinds"]
        self.assertEqual(set(kinds), set(habit_kinds.KINDS))
        self.assertTrue(kinds["no_alcohol"]["quit"])
        self.assertTrue(kinds["sleep"]["single"])

    def test_a_catalog_kind_with_a_field_setup(self):
        habit = self.create(
            name="protein",
            kind="protein",
            fields={"targets": {"grams": {"min": 90, "max": 110}}},
        )
        self.assertEqual(habit["fields"]["targets"]["grams"]["max"], 110)
        day = date.today().isoformat()
        saved = self.log(
            habit["id"], day, {"v": 2, "entries": [{"time": "08:00", "values": {"grams": 35}}]}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        card = self.card(habit["id"], day)
        self.assertEqual(card["days"][day]["entries"][0]["values"]["grams"], 35)
        self.assertEqual(card["logs"], {}, "no v1 view for a new kind")
        refused = self.client.post(
            "/api/habits", json={"name": "x", "kind": "protein", "fields": {"scale": 3}}
        )
        self.assertEqual(refused.status_code, 400)

    def test_a_slip_keeps_total_and_best_streak(self):
        today = date.today()
        habit = self.create(name="no alcohol", kind="no_alcohol")
        for back in range(5, 0, -1):
            self.log(
                habit["id"],
                (today - timedelta(days=back)).isoformat(),
                {"v": 2, "entries": [{"values": {"dry": True}}]},
            )
        slip = {
            "v": 2,
            "entries": [
                {"slip": True, "values": {"dry": False, "drinks": 2, "triggers": ["party"]}}
            ],
        }
        self.assertEqual(self.log(habit["id"], today.isoformat(), slip).status_code, 200)
        card = self.card(habit["id"], today.isoformat())
        self.assertEqual(card["streak"], 0)
        self.assertEqual(card["best_streak"], 5)
        self.assertEqual(card["total_days"], 5)
        self.assertEqual(card["slips"], [today.isoformat()])
        self.assertFalse(card["done_today"])
        run = self.create(name="run", kind="run")
        refused = self.log(run["id"], today.isoformat(), {"v": 2, "entries": [{"slip": True}]})
        self.assertEqual(refused.status_code, 400, "only quit habits slip")

    def test_a_planned_skip_carries_the_streak(self):
        today = date.today()
        habit = self.create(name="run", kind="run")
        for back in (3, 1, 0):
            self.log(
                habit["id"],
                (today - timedelta(days=back)).isoformat(),
                {"v": 2, "entries": [{"values": {"minutes": 30}}]},
            )
        self.log(
            habit["id"],
            (today - timedelta(days=2)).isoformat(),
            {"v": 2, "entries": [{"skip": True}]},
        )
        card = self.card(habit["id"], today.isoformat())
        self.assertEqual((card["streak"], card["best_streak"], card["total_days"]), (3, 3, 3))
        self.assertEqual(card["last_30"], 3)

    def test_kind_change_rechecks_every_log(self):
        day = date.today().isoformat()
        walk = self.create(name="walk", kind="duration")
        self.log(walk["id"], day, {"minutes": 40})
        moved = self.client.patch(f"/api/habits/{walk['id']}", json={"kind": "meditate"})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["kind"], "meditate")
        self.assertEqual(moved.json()["days"][day]["entries"][0]["values"], {"minutes": 40})
        water = self.create(name="water", kind="count", unit="glasses")
        self.log(water["id"], day, {"amount": 6})
        refused = self.client.patch(f"/api/habits/{water['id']}", json={"kind": "water"})
        self.assertEqual(refused.status_code, 409, "6 glasses can't become 6 of an unknown unit")
        self.assertEqual(self.card(water["id"], day)["kind"], "count")

    def test_patch_field_setup(self):
        habit = self.create(name="sleep", kind="sleep")
        saved = self.client.patch(
            f"/api/habits/{habit['id']}", json={"fields": {"on": ["bedtime", "wake", "naps"]}}
        )
        self.assertEqual(saved.json()["fields"], {"on": ["bedtime", "wake", "naps"]})
        bad = self.client.patch(f"/api/habits/{habit['id']}", json={"fields": {"on": ["laps"]}})
        self.assertEqual(bad.status_code, 400)

    def test_an_old_screen_edit_keeps_imported_side_detail(self):
        day = date.today().isoformat()
        habit = self.create(name="gym", kind="workout")
        detail = {
            "v": 2,
            "entries": [
                {
                    "id": "s",
                    "values": {
                        "exercises": [
                            {
                                "name": "pulldown",
                                "sets": [
                                    {"side": "L", "weight": 60, "reps": 12},
                                    {"side": "R", "weight": 70, "reps": 10},
                                ],
                            },
                        ]
                    },
                }
            ],
        }
        self.log(habit["id"], day, detail)
        old_view = self.card(habit["id"], day)["logs"][day]
        self.log(habit["id"], day, old_view)  # the old logger saves what it showed
        sets = self.card(habit["id"], day)["days"][day]["entries"][0]["values"]["exercises"][0][
            "sets"
        ]
        self.assertEqual([s["side"] for s in sets], ["L", "R"])


class M0078Tests(unittest.TestCase):
    def v1_database(self):
        engine = create_engine("sqlite://")
        conn = engine.connect()
        conn.execute(text("CREATE TABLE habits (id VARCHAR PRIMARY KEY, name VARCHAR)"))
        conn.execute(
            text("CREATE TABLE habit_logs (id INTEGER PRIMARY KEY, habit_id VARCHAR, date VARCHAR)")
        )
        conn.execute(
            text(
                "CREATE TABLE health_entries (id INTEGER PRIMARY KEY, kind VARCHAR, unit VARCHAR, value FLOAT)"
            )
        )
        m0076_habit_kinds.up(conn)
        habits = [
            ("gym", "workout"),
            ("read", "reading"),
            ("water", "count"),
            ("walk", "duration"),
            ("run", "distance"),
            ("floss", "check"),
        ]
        for hid, kind in habits:
            conn.execute(
                text("INSERT INTO habits (id, name, kind) VALUES (:id, :id, :kind)"),
                {"id": hid, "kind": kind},
            )
        logs = [
            (
                "gym",
                {
                    "rows": [
                        {
                            "exercise": "lat pulldown",
                            "weight": 70,
                            "reps": 10,
                            "sets": 3,
                            "note": "",
                        }
                    ]
                },
            ),
            ("read", {"amount": 24, "unit": "pages", "book": "dune"}),
            ("water", {"amount": 6}),
            ("walk", {"minutes": 45}),
            ("run", {"distance": 5.25, "unit": "mi", "minutes": None}),
            ("floss", None),
            ("water", "{not json"),
            ("water", {"amount": -4}),  # stored before the checks; must survive untouched
        ]
        for at, (hid, data) in enumerate(logs, 1):
            raw = data if isinstance(data, str) or data is None else json.dumps(data)
            conn.execute(
                text(
                    "INSERT INTO habit_logs (id, habit_id, date, data) VALUES (:id, :h, '2026-10-27', :d)"
                ),
                {"id": at, "h": hid, "d": raw},
            )
        for at, unit in enumerate(("lbs", "", "kg", "Pounds", "stone-ish", "kgs"), 1):
            conn.execute(
                text("INSERT INTO health_entries VALUES (:id, 'weight', :u, 150)"),
                {"id": at, "u": unit},
            )
        conn.execute(text("INSERT INTO health_entries VALUES (99, 'sleep', 'h', 8)"))
        return conn

    def dump(self, conn):
        return (
            conn.execute(text("SELECT id, data FROM habit_logs ORDER BY id")).fetchall(),
            conn.execute(text("SELECT id, unit FROM health_entries ORDER BY id")).fetchall(),
            conn.execute(text("SELECT id, fields FROM habits ORDER BY id")).fetchall(),
        )

    def test_twice_on_a_v1_database(self):
        conn = self.v1_database()
        m0078_habit_fields.up(conn)
        first = self.dump(conn)
        m0078_habit_fields.up(conn)
        self.assertEqual(self.dump(conn), first, "a second run changes nothing")
        logs = dict(first[0])
        kinds = {1: "workout", 2: "reading", 3: "count", 4: "duration", 5: "distance"}
        olds = {
            1: {
                "rows": [
                    {"exercise": "lat pulldown", "weight": 70, "reps": 10, "sets": 3, "note": ""}
                ]
            },
            2: {"amount": 24, "unit": "pages", "book": "dune"},
            3: {"amount": 6},
            4: {"minutes": 45},
            5: {"distance": 5.25, "unit": "mi", "minutes": None},
        }
        for log_id, kind in kinds.items():
            doc = json.loads(logs[log_id])
            self.assertEqual(doc["v"], 2)
            self.assertEqual(legacy_view(kind, doc), olds[log_id], kind)
        self.assertIsNone(logs[6])
        self.assertEqual(logs[7], "{not json")
        self.assertEqual(json.loads(logs[8]), {"amount": -4})
        self.assertEqual(
            first[1],
            [(1, "lb"), (2, "lb"), (3, "kg"), (4, "lb"), (5, "stone-ish"), (6, "kg"), (99, "h")],
        )
        self.assertTrue(all(fields is None for _, fields in first[2]))

    def test_missing_tables_are_left_alone(self):
        conn = create_engine("sqlite://").connect()
        m0078_habit_fields.up(conn)
        self.assertEqual(conn.execute(text("SELECT name FROM sqlite_master")).fetchall(), [])


class StoredRowsTests(ApiTest):
    def test_toggle_off_drops_a_v2_day(self):
        with self.db() as db:
            habit = Habit(name="run", kind="run")
            db.add(habit)
            db.commit()
            hid = habit.id
        day = date.today().isoformat()
        self.client.post(
            f"/api/habits/{hid}/toggle",
            json={"date": day, "data": {"v": 2, "entries": [{"values": {"minutes": 20}}]}},
        )
        self.client.post(f"/api/habits/{hid}/toggle", json={"date": day, "done": False})
        with self.db() as db:
            self.assertEqual(db.query(HabitLog).filter_by(habit_id=hid).count(), 0)


if __name__ == "__main__":
    unittest.main()
