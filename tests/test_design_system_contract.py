import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "design-system"


class DesignSystemContractTests(unittest.TestCase):
    def test_required_sources_exist_and_have_no_placeholders(self):
        required = (
            "README.md",
            "PRODUCT.md",
            "PRINCIPLES.md",
            "BRAND.md",
            "FOUNDATIONS.md",
            "COMPONENTS.md",
            "PATTERNS.md",
            "CONTENT.md",
            "ACCESSIBILITY.md",
            "RESPONSIVE.md",
            "MOTION.md",
            "OUTPUT-CONTRACT.md",
            "QA-CHECKLIST.md",
            "UI-BRIEF.md",
        )
        for name in required:
            path = SYSTEM / name
            self.assertTrue(path.is_file(), name)
            self.assertNotIn("TODO", path.read_text(encoding="utf-8"), name)

    def test_project_skill_is_valid_source_map(self):
        skill = ROOT / ".agents/skills/ui-product-designer/SKILL.md"
        text = skill.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: ui-product-designer\n"))
        self.assertIn("design-system/FOUNDATIONS.md", text)
        self.assertIn("docs/mockups/", text)
        self.assertNotIn("TODO", text)

    def test_token_files_are_json_and_aliases_resolve(self):
        token_paths = set()
        aliases = []

        def walk(value, parts=()):
            if isinstance(value, dict):
                if "$value" in value:
                    token_paths.add(".".join(parts))
                    token_value = value["$value"]
                    if isinstance(token_value, str):
                        aliases.extend(re.findall(r"\{([^}]+)\}", token_value))
                for key, child in value.items():
                    if not key.startswith("$"):
                        walk(child, (*parts, key))
            elif isinstance(value, list):
                for child in value:
                    walk(child, parts)

        for name in (
            "primitives.tokens.json",
            "semantic.tokens.json",
            "components.tokens.json",
        ):
            with (SYSTEM / "tokens" / name).open(encoding="utf-8") as handle:
                walk(json.load(handle))

        self.assertTrue(token_paths)
        self.assertEqual([], sorted(set(aliases) - token_paths))

    def test_spacing_contract_is_exact(self):
        with (SYSTEM / "tokens/primitives.tokens.json").open(encoding="utf-8") as handle:
            tokens = json.load(handle)
        values = [entry["$value"]["value"] for entry in tokens["space"].values()]
        self.assertEqual([0, 4, 8, 12, 16, 24, 32, 48, 64], values)

        with (SYSTEM / "tokens/semantic.tokens.json").open(encoding="utf-8") as handle:
            semantic = json.load(handle)["space"]
        self.assertEqual("{space.300}", semantic["card"]["$value"])
        self.assertEqual("{space.400}", semantic["header"]["$value"])
        self.assertEqual("{space.400}", semantic["region"]["$value"])
        self.assertEqual("{space.600}", semantic["section"]["$value"])
        self.assertEqual("{space.800}", semantic["major"]["$value"])

    def test_runtime_exposes_portable_kokuen_v3_tokens(self):
        css = (ROOT / "static" / "kokuen.css").read_text(encoding="utf-8")
        expected = {
            "--k-space-0": "0",
            "--k-space-1": "4px",
            "--k-space-2": "8px",
            "--k-space-3": "12px",
            "--k-space-4": "16px",
            "--k-space-5": "24px",
            "--k-space-6": "32px",
            "--k-space-7": "48px",
            "--k-space-8": "64px",
        }
        for token, value in expected.items():
            with self.subTest(token=token):
                self.assertRegex(css, rf"{re.escape(token)}:\s*{re.escape(value)};")
                self.assertIn(f"--ui-space-{token.rsplit('-', 1)[1]}: var({token});", css)
        for token in (
            "canvas",
            "surface",
            "text",
            "muted",
            "border",
            "border-strong",
            "focus",
            "error",
            "success",
            "control-height",
            "page-gutter",
            "content-max",
            "radius-control",
            "radius-container",
        ):
            self.assertIn(f"--ui-{token}:", css)

    def test_focus_is_neutral_and_active_state_keeps_the_accent(self):
        with (SYSTEM / "tokens/semantic.tokens.json").open(encoding="utf-8") as handle:
            themes = json.load(handle)["theme"]
        self.assertEqual(
            "{color.dark.lineStrong}", themes["dark"]["color"]["border"]["focus"]["$value"]
        )
        self.assertEqual(
            "{color.light.lineStrong}", themes["light"]["color"]["border"]["focus"]["$value"]
        )
        self.assertEqual(
            "{color.shared.accentDark}", themes["dark"]["color"]["action"]["active"]["$value"]
        )
        self.assertEqual(
            "{color.shared.accentLight}", themes["light"]["color"]["action"]["active"]["$value"]
        )

    def test_text_colors_clear_wcag_aa(self):
        with (SYSTEM / "tokens/primitives.tokens.json").open(encoding="utf-8") as handle:
            tokens = json.load(handle)["color"]

        def luminance(color):
            self.assertEqual(color["colorSpace"], "srgb")
            self.assertEqual(color["alpha"], 1)
            channels = color["components"]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(foreground, background):
            lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
            return (lighter + 0.05) / (darker + 0.05)

        for theme in ("dark", "light"):
            background = tokens[theme]["page"]["$value"]
            for role in ("text", "soft", "muted", "quiet"):
                with self.subTest(theme=theme, role=role):
                    self.assertGreaterEqual(
                        contrast(tokens[theme][role]["$value"], background), 4.5
                    )

        for role in ("accent", "permission", "danger", "success"):
            for theme in ("Dark", "Light"):
                with self.subTest(theme=theme, role=role):
                    self.assertGreaterEqual(
                        contrast(
                            tokens["shared"][f"{role}{theme}"]["$value"],
                            tokens[theme.lower()]["page"]["$value"],
                        ),
                        4.5,
                    )


if __name__ == "__main__":
    unittest.main()
