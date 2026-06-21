import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings
from services.appearance import (
    DARK_BASE,
    LIGHT_BASE,
    default_appearance,
    from_legacy,
    normalize,
)
from tests._client import ApiTest


class AppearanceLogicTests(unittest.TestCase):
    def test_default_has_all_sections(self):
        a = default_appearance()
        for k in (
            "preset",
            "colors",
            "font",
            "density",
            "bgPattern",
            "frosted",
            "effect",
            "customThemes",
        ):
            self.assertIn(k, a)
        for c in ("bg", "text", "panel", "faint", "accent"):
            self.assertIn(c, a["colors"])

    def test_normalize_fills_missing(self):
        a = normalize({})
        self.assertEqual(a["font"], default_appearance()["font"])
        self.assertEqual(a["colors"]["bg"], DARK_BASE["bg"])

    def test_normalize_rejects_bad_font(self):
        self.assertEqual(normalize({"font": "comic-sans"})["font"], "sans")

    def test_normalize_rejects_bad_density(self):
        self.assertEqual(normalize({"density": "huge"})["density"], "comfortable")

    def test_normalize_rejects_bad_pattern(self):
        self.assertEqual(normalize({"bgPattern": "explosions"})["bgPattern"], "none")

    def test_normalize_keeps_valid_pattern(self):
        self.assertEqual(normalize({"bgPattern": "constellations"})["bgPattern"], "constellations")

    def test_normalize_clamps_intensity(self):
        self.assertEqual(normalize({"effect": {"intensity": 5}})["effect"]["intensity"], 1)
        self.assertEqual(normalize({"effect": {"intensity": -2}})["effect"]["intensity"], 0)

    def test_normalize_clamps_size(self):
        self.assertEqual(normalize({"effect": {"size": 9}})["effect"]["size"], 3)
        self.assertEqual(normalize({"effect": {"size": 0.01}})["effect"]["size"], 0.2)

    def test_normalize_drops_bad_hex(self):
        a = normalize({"colors": {"bg": "not-a-color", "accent": "#abcdef"}})
        self.assertEqual(a["colors"]["bg"], DARK_BASE["bg"])  # fell back
        self.assertEqual(a["colors"]["accent"], "#abcdef")  # kept

    def test_normalize_accepts_3char_hex(self):
        self.assertEqual(normalize({"colors": {"accent": "#abc"}})["colors"]["accent"], "#abc")

    def test_normalize_coerces_frosted_bool(self):
        self.assertTrue(normalize({"frosted": 1})["frosted"] is True)

    def test_normalize_custom_themes_dict(self):
        self.assertEqual(normalize({"customThemes": "nope"})["customThemes"], {})
        ct = {"mine": {"bg": "#000000"}}
        self.assertEqual(normalize({"customThemes": ct})["customThemes"], ct)

    def test_from_legacy_dark(self):
        a = from_legacy("", "")
        self.assertEqual(a["preset"], "dark")
        self.assertEqual(a["colors"]["bg"], DARK_BASE["bg"])

    def test_from_legacy_light_with_accent(self):
        a = from_legacy("light", "#ff0000")
        self.assertEqual(a["preset"], "light")
        self.assertEqual(a["colors"]["bg"], LIGHT_BASE["bg"])
        self.assertEqual(a["colors"]["accent"], "#ff0000")


class AppearanceApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._patcher = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._tmp.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        os.unlink(self._tmp.name)
        super().tearDown()

    def test_get_default_when_unset(self):
        r = self.client.get("/api/appearance")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["preset"], "dark")

    def test_put_then_get_roundtrip(self):
        body = {"preset": "custom", "colors": {"accent": "#123456"}, "font": "serif"}
        r = self.client.put("/api/appearance", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["colors"]["accent"], "#123456")
        self.assertEqual(r.json()["font"], "serif")
        got = self.client.get("/api/appearance").json()
        self.assertEqual(got["colors"]["accent"], "#123456")
        self.assertEqual(got["font"], "serif")

    def test_put_normalizes_bad_values(self):
        r = self.client.put(
            "/api/appearance", json={"font": "wingdings", "effect": {"intensity": 99}}
        )
        self.assertEqual(r.json()["font"], "sans")
        self.assertEqual(r.json()["effect"]["intensity"], 1)

    def test_get_falls_back_to_legacy(self):
        # legacy theme/accent present, no appearance object yet
        self.client.patch("/api/settings", json={"theme": "light", "accent": "#00ff00"})
        got = self.client.get("/api/appearance").json()
        self.assertEqual(got["preset"], "light")
        self.assertEqual(got["colors"]["accent"], "#00ff00")

    def test_put_syncs_legacy_fields(self):
        self.client.put(
            "/api/appearance", json={"preset": "light", "colors": {"accent": "#abcdef"}}
        )
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["theme"], "light")
        self.assertEqual(s["accent"], "#abcdef")
