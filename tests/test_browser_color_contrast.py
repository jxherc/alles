"""Keep owned browser contrast checks from accepting translucent text."""

import ast
import re
import unittest
from pathlib import Path

driver = Path(__file__).with_name("pw_backup_help_error_color.py")
functions = [
    node
    for node in ast.parse(driver.read_text()).body
    if isinstance(node, ast.FunctionDef) and node.name in {"rgb", "contrast"}
]
namespace = {"re": re}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(driver), "exec"), namespace)
contrast = namespace["contrast"]


class BrowserColorContrastTests(unittest.TestCase):
    def test_opaque_reference_colors_have_known_ratios(self):
        self.assertEqual(contrast("#000000", "#ffffff"), 21)
        self.assertAlmostEqual(contrast("rgb(166, 66, 66)", "rgb(238, 236, 232)"), 5.1155619033)
        self.assertEqual(contrast("rgba(0, 0, 0, 1)", "#ffffff"), 21)

    def test_translucent_foreground_or_background_is_not_a_pass(self):
        for foreground, background in (
            ("rgba(0, 0, 0, 0)", "#ffffff"),
            ("rgba(0, 0, 0, 0.1)", "#ffffff"),
            ("#000000", "rgba(255, 255, 255, 0.5)"),
        ):
            with self.subTest(foreground=foreground, background=background):
                with self.assertRaisesRegex(AssertionError, "requires opaque colors"):
                    contrast(foreground, background)

    def test_unmeasured_color_formats_fail_instead_of_guessing(self):
        for foreground in ("transparent", "#00000080", "rgb(256, 0, 0)", "color(srgb 0 0 0)"):
            with self.subTest(foreground=foreground):
                with self.assertRaises(AssertionError):
                    contrast(foreground, "#ffffff")
