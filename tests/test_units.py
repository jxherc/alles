"""units: conversions that round trip, the owner's display choices, and the body profile."""

import unittest
from unittest import mock

from services import andromeda_answers, units
from tests._client import ApiTest


class ConversionTests(unittest.TestCase):
    def test_round_trips_come_back_exact(self):
        pairs = [
            ("lb", "kg"),
            ("kg", "lb"),
            ("cm", "in"),
            ("in", "ft"),
            ("km", "mi"),
            ("ml", "floz"),
            ("glass", "ml"),
            ("c", "f"),
            ("f", "c"),
            ("g", "oz"),
        ]
        for a, b in pairs:
            for value in (0, 1, 2.5, 37, 70, 180.3, 1000):
                with self.subTest(a=a, b=b, value=value):
                    back = units.change(units.change(value, a, b), b, a)
                    self.assertAlmostEqual(back, value, places=9)

    def test_known_values(self):
        self.assertAlmostEqual(units.change(100, "kg", "lb"), 220.462262, places=5)
        self.assertAlmostEqual(units.change(1, "mi", "km"), 1.609344)
        self.assertAlmostEqual(units.change(100, "c", "f"), 212)
        self.assertAlmostEqual(units.change(8, "glass", "floz"), 64, places=3)
        self.assertEqual(units.to_feet_inches(180), (5, 10.9))
        self.assertEqual(units.to_feet_inches(182.88), (6, 0.0))
        self.assertAlmostEqual(units.from_feet_inches(5, 11), 180.34)

    def test_names_and_kinds(self):
        self.assertEqual(units.canonical("Lbs"), "lb")
        self.assertEqual(units.canonical("pounds"), "lb")
        self.assertEqual(units.canonical("kilos"), "kg")
        self.assertEqual(units.canonical("oz", "volume"), "floz")
        self.assertEqual(units.canonical("oz"), "oz")
        self.assertIsNone(units.canonical("kg", "length"))
        self.assertIsNone(units.canonical(""))
        self.assertEqual(units.dimension("mi"), "length")

    def test_refuses_mixed_kinds(self):
        for a, b in (("kg", "km"), ("c", "lb"), ("nope", "kg")):
            with self.subTest(a=a, b=b), self.assertRaises(units.UnitError):
                units.change(1, a, b)

    def test_andromeda_reads_the_same_tables(self):
        self.assertIs(andromeda_answers._UNITS, units.UNITS)
        self.assertAlmostEqual(andromeda_answers.convert(1, "mi", "km"), 1.609344)


class PreferenceTests(unittest.TestCase):
    def test_defaults_and_junk(self):
        self.assertEqual(units.preferences(None)["weight"], "lb")
        self.assertEqual(
            units.preferences({"weight": "kg", "distance": "furlong"})["distance"], "km"
        )
        self.assertEqual(units.preferences({"weight": "kg"})["weight"], "kg")

    def test_check_refuses_unknown_choices(self):
        self.assertEqual(units.check_preferences({"height": "ft_in"}), {"height": "ft_in"})
        for bad in ({"weight": "stone"}, {"speed": "mph"}, ["kg"]):
            with self.subTest(bad=bad), self.assertRaises(units.UnitError):
                units.check_preferences(bad)

    def test_display_in_the_owners_unit(self):
        value, unit = units.for_display(70, "kg", "weight", {"weight": "lb"})
        self.assertEqual(unit, "lb")
        self.assertAlmostEqual(value, 154.3235835)
        value, unit = units.for_display(180, "cm", "height", {"height": "ft_in"})
        self.assertEqual(unit, "in")

    def test_body_units(self):
        self.assertEqual(units.body_unit("weight", "LBS"), "lb")
        self.assertEqual(units.body_unit("weight", "", {"weight": "kg"}), "kg")
        self.assertEqual(units.body_unit("height", "", {"height": "ft_in"}), "in")
        self.assertEqual(units.body_unit("measurement", "inches"), "in")
        self.assertEqual(units.body_unit("body_fat", "whatever"), "%")
        self.assertEqual(units.body_unit("sleep", "h"), "h")
        with self.assertRaises(units.UnitError):
            units.body_unit("weight", "cm")


class BodyProfileApiTests(ApiTest):
    def test_profile_units_and_measurements(self):
        saved = {}

        def load():
            return dict(saved)

        def save(patch):
            saved.update(patch)

        with (
            mock.patch("core.settings.load_settings", load),
            mock.patch("core.settings.save_settings", save),
        ):
            for body in (
                {"kind": "height", "value": 180, "unit": "cm", "date": "2026-10-01"},
                {"kind": "weight", "value": 150, "unit": "lbs", "date": "2026-10-01"},
                {"kind": "weight", "value": 68, "unit": "kg", "date": "2026-10-20"},
                {"kind": "body_fat", "value": 18, "date": "2026-10-20"},
                {
                    "kind": "measurement",
                    "label": "arm left",
                    "value": 13,
                    "unit": "in",
                    "date": "2026-10-20",
                },
                {
                    "kind": "measurement",
                    "label": "arm right",
                    "value": 13.5,
                    "unit": "in",
                    "date": "2026-10-20",
                },
            ):
                response = self.client.post("/api/health", json=body)
                self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["unit"], "in")
            profile = self.client.get("/api/health/profile").json()
            self.assertEqual(profile["units"]["weight"], "lb")
            self.assertEqual(profile["height"]["unit"], "cm")
            self.assertEqual((profile["weight"]["value"], profile["weight"]["unit"]), (68, "kg"))
            self.assertEqual(profile["body_fat"]["unit"], "%")
            self.assertEqual(set(profile["measurements"]), {"arm left", "arm right"})

            changed = self.client.put(
                "/api/health/units", json={"units": {"weight": "kg", "height": "ft_in"}}
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(changed.json()["units"]["height"], "ft_in")
            empty = self.client.post("/api/health", json={"kind": "weight", "value": 70})
            self.assertEqual(empty.json()["unit"], "kg", "an empty unit takes the owner's choice")

            refused = self.client.put("/api/health/units", json={"units": {"weight": "stone"}})
            self.assertEqual(refused.status_code, 400)
            wrong = self.client.post(
                "/api/health", json={"kind": "weight", "value": 70, "unit": "cm"}
            )
            self.assertEqual(wrong.status_code, 400)
            unnamed = self.client.post(
                "/api/health", json={"kind": "measurement", "value": 30, "unit": "in"}
            )
            self.assertEqual(unnamed.status_code, 400)

    def test_workout_card_picks_up_the_days_body_weight(self):
        self.client.post(
            "/api/health", json={"kind": "weight", "value": 150, "unit": "lb", "date": "2026-10-01"}
        )
        habit = self.client.post("/api/habits", json={"name": "gym", "kind": "workout"}).json()
        cards = self.client.get("/api/habits/overview?date_q=2026-10-05").json()["habits"]
        card = next(card for card in cards if card["id"] == habit["id"])
        self.assertEqual(card["body_weight"], {"date": "2026-10-01", "value": 150.0, "unit": "lb"})
        earlier = self.client.get("/api/habits/overview?date_q=2026-09-01").json()["habits"]
        self.assertIsNone(next(c for c in earlier if c["id"] == habit["id"])["body_weight"])


if __name__ == "__main__":
    unittest.main()
