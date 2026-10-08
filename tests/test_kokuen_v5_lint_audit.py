import hashlib
import re
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from scripts.check_kokuen_v5_lint import canonical_linter, reconcile, render_report

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
        summary = re.search(
            r"KOKUEN v5 lint audit: (\d+) errors, (\d+) warnings, (\d+) explained, "
            r"(\d+) unexplained, (\d+) stale",
            result.stdout,
        )
        self.assertIsNotNone(summary, result.stdout)
        errors, warnings, explained, unexplained, stale = map(int, summary.groups())
        self.assertEqual((errors, unexplained, stale), (0, 0, 0))
        self.assertEqual(warnings, explained)

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


class SemanticWarningRegistryTests(unittest.TestCase):
    def setUp(self):
        self.css = "\n/* secondary row detail */\n.meta { font-size: 12px; color: var(--k-muted); }"
        self.warning = {
            "severity": "WARN",
            "rule": "small-type",
            "path": "static/kokuen.css",
            # The canonical anchor includes the leading newline and comment.
            "line": 1,
            "message": "font-size 12px is below the 14px essential-text baseline in .meta",
        }
        self.entry = {
            "rule": self.warning["rule"],
            "message": self.warning["message"],
            "css_block_sha256": hashlib.sha256(self.css.encode("utf-8")).hexdigest(),
            "path": self.warning["path"],
            "selector": ".meta",
            "job": "secondary-metadata",
            "reason": "The row timestamp is secondary to the item title.",
        }

    def test_known_exact_role_is_accepted(self):
        audit = reconcile([self.warning], [self.entry], self.css)
        self.assertEqual(audit["failures"], [])
        self.assertEqual(audit["unexplained"], [])
        self.assertEqual(audit["stale"], [])
        self.assertEqual(len(audit["explained"]), 1)
        self.assertEqual(audit["explained"][0]["job"], "secondary-metadata")
        self.assertEqual(audit["explained"][0]["reason"], self.entry["reason"])

    def test_added_warning_is_unknown(self):
        css = self.css + "\n.other { font-size: 12px; }"
        added = {
            **self.warning,
            "line": 3,
            "message": self.warning["message"].replace(".meta", ".other"),
        }
        audit = reconcile([self.warning, added], [self.entry], css)
        self.assertTrue(audit["failures"])
        self.assertEqual(len(audit["explained"]), 1)
        self.assertEqual(len(audit["unexplained"]), 1)
        self.assertEqual(audit["unexplained"][0]["message"], added["message"])
        self.assertEqual(audit["stale"], [])

    def test_same_warning_with_changed_declaration_is_refused(self):
        css = self.css.replace("color: var(--k-muted)", "color: var(--k-text)")
        audit = reconcile([self.warning], [self.entry], css)
        self.assertTrue(audit["failures"])
        self.assertEqual(audit["explained"], [])
        self.assertEqual(len(audit["unexplained"]), 1)
        self.assertEqual(audit["unexplained"][0]["message"], self.warning["message"])
        self.assertEqual(audit["stale"], [self.entry])

    def test_deleted_warning_leaves_a_stale_entry(self):
        audit = reconcile([], [self.entry], "")
        self.assertTrue(audit["failures"])
        self.assertEqual(audit["stale"], [self.entry])
        self.assertEqual(audit["warnings"], [])

    def test_canonical_error_cannot_be_resolved_by_a_warning_entry(self):
        error = {**self.warning, "severity": "ERROR"}
        audit = reconcile([self.warning, error], [self.entry], self.css)
        self.assertEqual(audit["errors"], [error])
        self.assertEqual(len(audit["explained"]), 1)
        self.assertIn("1 hard errors", audit["failures"])
        self.assertIn("| ERROR |", render_report(audit))

    def test_rule_and_message_must_both_match(self):
        for field in ("rule", "message"):
            with self.subTest(field=field):
                warning = {**self.warning, field: "different canonical warning"}
                audit = reconcile([warning], [self.entry], self.css)
                self.assertTrue(audit["failures"])
                self.assertEqual(audit["explained"], [])
                self.assertEqual(audit["stale"], [self.entry])

    def test_registered_selector_must_match_the_actual_role(self):
        entry = {**self.entry, "selector": ".primary-title"}
        audit = reconcile([self.warning], [entry], self.css)
        self.assertTrue(audit["failures"])
        self.assertEqual(audit["explained"], [])
        self.assertEqual(audit["stale"], [entry])

    def test_warning_path_and_canonical_line_anchor_must_match(self):
        for changed in ({"path": "static/other.css"}, {"line": 3}):
            with self.subTest(changed=changed):
                audit = reconcile([{**self.warning, **changed}], [self.entry], self.css)
                self.assertTrue(audit["failures"])
                self.assertEqual(audit["explained"], [])

    def test_same_line_blocks_are_ambiguous(self):
        css = ".meta { font-size: 12px; }.other { font-size: 12px; }"
        audit = reconcile([self.warning], [self.entry], css)
        self.assertTrue(audit["failures"])
        self.assertIn("ambiguous", audit["unexplained"][0]["reason"])

    def test_duplicate_registry_entry_is_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate warning registry entry"):
            reconcile([self.warning], [self.entry, dict(self.entry)], self.css)

    def test_duplicate_canonical_warning_is_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate canonical warning identity"):
            reconcile([self.warning, dict(self.warning)], [self.entry], self.css)

    def test_empty_reason_or_job_and_invalid_registry_metadata_are_refused(self):
        for changed in (
            {"reason": " \n "},
            {"job": ""},
            {"path": "static/other.css"},
            {"css_block_sha256": "not-a-block-hash"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, "invalid warning registry entry"):
                    reconcile([self.warning], [{**self.entry, **changed}], self.css)

    def test_report_keeps_pending_warnings_and_stale_entries_visible(self):
        audit = reconcile([self.warning], [self.entry], self.css.replace("12px", "13px"))
        report = render_report(audit)
        self.assertIn("| PENDING |", report)
        self.assertIn("| STALE |", report)
        self.assertIn(self.entry["reason"], report)
        self.assertIn(self.entry["css_block_sha256"], report)


if __name__ == "__main__":
    unittest.main()
