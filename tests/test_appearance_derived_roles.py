"""A theme save must preserve the palette that the browser just previewed."""

import copy
import unittest

from services.appearance import DARK_BASE, LIGHT_BASE, default_appearance, effective, normalize

PALETTES = {
    "paper": {
        "bg": "#faf8f5",
        "text": "#3b3836",
        "panel": "#ffffff",
        "faint": "#d5d0c8",
        "accent": "#b07d3a",
    },
    "lavender": {
        "bg": "#f3eef8",
        "text": "#3d3551",
        "panel": "#faf7ff",
        "faint": "#cec3de",
        "accent": "#9b6dcc",
    },
    "midnight": {
        "bg": "#0d1117",
        "text": "#c9d1d9",
        "panel": "#161b22",
        "faint": "#30363d",
        "accent": "#58a6ff",
    },
}
ROLES = ("raised", "hover", "soft", "muted", "quiet", "lineStrong")


class AppearanceDerivedRoleTests(unittest.TestCase):
    def test_preset_palette_survives_save_and_repeated_read_without_dark_role_injection(self):
        for preset, colors in PALETTES.items():
            with self.subTest(preset=preset):
                body = {"preset": preset, "colors": dict(colors), "accentCustom": False}
                original = copy.deepcopy(body)
                saved = normalize(body)
                self.assertEqual(saved["colors"], colors)
                self.assertEqual(effective({"appearance": saved})["colors"], colors)
                self.assertEqual(normalize(saved), saved)
                self.assertEqual(body, original)

    def test_custom_palettes_keep_missing_roles_derived_too(self):
        colors = {**PALETTES["paper"], "accent": "#123456"}
        self.assertEqual(normalize({"preset": "custom", "colors": colors})["colors"], colors)

    def test_explicit_role_overrides_survive_even_when_they_equal_dark_defaults(self):
        colors = {**PALETTES["paper"], **{key: DARK_BASE[key] for key in ROLES}}
        saved = normalize({"preset": "custom", "colors": colors})
        self.assertEqual(saved["colors"], colors)
        self.assertEqual(effective({"appearance": saved})["colors"], colors)

    def test_invalid_optional_roles_are_dropped_for_client_derivation(self):
        for role in ROLES:
            with self.subTest(role=role):
                colors = {**PALETTES["lavender"], role: "invalid color"}
                saved = normalize({"preset": "lavender", "colors": colors})
                self.assertEqual(saved["colors"], PALETTES["lavender"])

    def test_complete_canonical_palettes_retain_every_explicit_role(self):
        for preset, colors in [("dark", DARK_BASE), ("light", LIGHT_BASE)]:
            with self.subTest(preset=preset):
                self.assertEqual(normalize({"preset": preset, "colors": colors})["colors"], colors)

    def test_missing_palette_uses_the_requested_base_mode(self):
        self.assertEqual(normalize({})["colors"], default_appearance()["colors"])
        self.assertEqual(normalize({"preset": "light"})["colors"], LIGHT_BASE)

    def test_invalid_required_color_keeps_a_valid_mode_appropriate_fallback(self):
        saved = normalize({"preset": "light", "colors": {"bg": "invalid", "accent": "#abc"}})
        self.assertEqual(saved["colors"]["bg"], LIGHT_BASE["bg"])
        self.assertEqual(saved["colors"]["text"], LIGHT_BASE["text"])
        self.assertEqual(saved["colors"]["accent"], "#abc")

    def test_legacy_light_migration_uses_new_light_roles_without_injected_dark_overrides(self):
        old = {
            "preset": "light",
            "colors": {
                "bg": "#f5f4f1",
                "text": "#111111",
                "panel": "#efede9",
                "faint": "#d4d2ce",
                "accent": "#818cf8",
            },
        }
        self.assertEqual(effective({"appearance": old})["colors"], LIGHT_BASE)


if __name__ == "__main__":
    unittest.main()
