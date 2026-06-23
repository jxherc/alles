"""regression tests for the 8th bug-hunt iteration:
- _esc must escape quotes so a photo caption can't break out of an HTML attribute (stored XSS)
- CSV export must neutralize spreadsheet formula injection (cells starting = + - @)
- CORS must not pair allow_origins=* with credentials
"""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"


class EscTests(unittest.TestCase):
    def test_esc_escapes_quotes(self):
        from routes.shared import _esc

        out = _esc('"><script>alert(1)</script>')
        self.assertNotIn('"', out)  # the attribute-breaking quote is gone
        self.assertNotIn("<script>", out)
        self.assertIn("&quot;", out)
        self.assertIn("&lt;script&gt;", out)

    def test_esc_single_quote(self):
        from routes.shared import _esc

        self.assertIn("&#39;", _esc("it's"))


class CsvInjectionTests(unittest.TestCase):
    def test_formula_cells_neutralized(self):
        from services.exporters import to_csv

        out = to_csv(
            [
                {"title": '=HYPERLINK("http://evil","x")'},
                {"title": "@SUM(1+1)"},
                {"title": "+1+1"},
                {"title": "-1+1"},
            ]
        )
        # no data cell may START with a formula trigger (after CSV quoting is parsed away)
        import csv
        import io

        rows = list(csv.DictReader(io.StringIO(out)))
        for r in rows:
            self.assertTrue(r["title"].startswith("'"))  # neutralized with a leading apostrophe
            self.assertFalse(r["title"][0] in ("=", "+", "-", "@"))

    def test_plain_value_unchanged(self):
        from services.exporters import to_csv

        out = to_csv([{"name": "Alice"}])
        self.assertIn("Alice", out)
        self.assertNotIn("'Alice", out)


class CorsTests(unittest.TestCase):
    def test_cors_not_wildcard_with_credentials(self):
        from fastapi.testclient import TestClient

        from app import app

        c = TestClient(app)
        # a credentialed cross-origin preflight must NOT come back allowing credentials with "*"
        r = c.options(
            "/api/settings",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        acac = r.headers.get("access-control-allow-credentials", "")
        self.assertNotEqual(acac.lower(), "true")


if __name__ == "__main__":
    unittest.main()
