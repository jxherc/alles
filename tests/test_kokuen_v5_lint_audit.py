import re
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from scripts.check_kokuen_v5_lint import canonical_linter

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_kokuen_v5_lint.py"
CANONICAL_LINTER = canonical_linter()


class _ButtonTypeAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.missing = []

    def handle_starttag(self, tag, attrs):
        if tag == "button" and "type" not in dict(attrs):
            self.missing.append(self.getpos()[0])


class KokuenV5LintAuditTests(unittest.TestCase):
    def test_explicit_linter_override_is_not_replaced_by_discovery(self):
        with patch.dict("os.environ", {"KOKUEN_LINTER": "~/custom-kokuen/lint.py"}):
            self.assertEqual(canonical_linter(), Path.home() / "custom-kokuen" / "lint.py")

    @unittest.skipUnless(CANONICAL_LINTER.is_file(), "canonical KOKUEN checkout is not installed")
    def test_every_overlay_warning_is_reviewed(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 errors, 195 warnings, 195 explained, 0 unexplained", result.stdout)

    def test_inline_product_text_respects_the_twelve_pixel_floor(self):
        rem_pattern = re.compile(r"font-size\s*:\s*(0?\.[0-9]+)rem")
        pixel_pattern = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)px")
        sources = [
            ROOT / "static" / "index.html",
            *(ROOT / "static").glob("*.css"),
            *(ROOT / "static" / "js").glob("*.js"),
        ]
        violations = []
        for source in sources:
            for line_number, line in enumerate(source.read_text(errors="ignore").splitlines(), 1):
                for match in rem_pattern.finditer(line):
                    if float(match.group(1)) < 0.75:
                        violations.append(
                            f"{source.relative_to(ROOT)}:{line_number}: {match.group(0)}"
                        )
                for match in pixel_pattern.finditer(line):
                    if float(match.group(1)) < 12:
                        violations.append(
                            f"{source.relative_to(ROOT)}:{line_number}: {match.group(0)}"
                        )
        self.assertEqual(violations, [], "inline text below 12px:\n" + "\n".join(violations))

    def test_static_buttons_declare_non_submitting_behavior(self):
        audit = _ButtonTypeAudit()
        audit.feed((ROOT / "static" / "index.html").read_text())
        self.assertEqual(
            audit.missing, [], f"button tags missing explicit type on lines {audit.missing}"
        )


if __name__ == "__main__":
    unittest.main()
