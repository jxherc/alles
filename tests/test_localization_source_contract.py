import json
import re
import unittest
from pathlib import Path

from services.localization import validate_catalogs

ROOT = Path(__file__).resolve().parent.parent
JS_ROOT = ROOT / "static" / "js"


class LocalizationSourceContractTests(unittest.TestCase):
    def test_named_core_flow_sources_reference_real_catalog_keys(self):
        status = validate_catalogs()
        catalog = json.loads((ROOT / "static" / "locales" / "en.json").read_text("utf-8"))
        keys = set(catalog["messages"]) | set(catalog["plurals"])
        referenced: set[str] = set()
        literal_key = re.compile(r"\b(?:t|tr|tp|trp)\(\s*['\"]([a-z0-9_.-]+)['\"]")
        html_key = re.compile(r'data-i18n(?:-placeholder|-aria-label|-title)?="([a-z0-9_.-]+)"')
        for flow in status["coverage_contract"]["localized_core_flows"]:
            flow_referenced: set[str] = set()
            for source in flow["sources"]:
                text = (ROOT / source).read_text("utf-8")
                flow_referenced.update(literal_key.findall(text))
                flow_referenced.update(html_key.findall(text))
            referenced.update(flow_referenced)
            for prefix in flow["key_prefixes"]:
                self.assertTrue(
                    any(key.startswith(prefix) for key in flow_referenced),
                    f"{flow['id']} does not reference {prefix}",
                )
        self.assertEqual(sorted(referenced - keys), [])

    def test_coverage_contract_records_non_interface_language_boundaries(self):
        boundaries = validate_catalogs()["coverage_contract"]["source_language_boundaries"]
        combined = " ".join(boundaries)
        for required in ("owner", "third-party", "paths", "legacy specialist"):
            self.assertIn(required, combined)

    def test_product_modules_do_not_force_en_us_or_format_around_shared_helpers(self):
        violations = []
        direct_locale_output = re.compile(
            r"\.toLocale(?:DateString|TimeString|String)\s*\(|"
            r"new\s+Intl\.(?:DateTimeFormat|NumberFormat|ListFormat|RelativeTimeFormat|PluralRules)\s*\("
        )
        for path in sorted(JS_ROOT.glob("*.js")):
            if path.name == "i18n.js":
                continue
            text = path.read_text("utf-8")
            if "en-US" in text:
                violations.append(f"{path.name}: hard-coded en-US")
            for match in direct_locale_output.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.name}:{line}: bypasses shared locale helpers")
        self.assertEqual(violations, [])

    def test_static_localized_copy_uses_catalog_keys(self):
        html = (ROOT / "static" / "index.html").read_text("utf-8")
        required_keys = {
            "locale.title",
            "locale.description",
            "locale.interface_language",
            "locale.format_title",
            "locale.region",
            "locale.timezone",
            "locale.clock",
            "locale.first_day",
            "locale.currency",
            "locale.save",
        }
        for key in required_keys:
            self.assertIn(f'data-i18n="{key}"', html)


if __name__ == "__main__":
    unittest.main()
