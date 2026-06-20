"""11b-2 — PWA install polish: the manifest + index head carry what iOS/Android need
to install a polished home-screen app (orientation, categories, shortcuts, scope/id,
mobile-web-app-capable). Served straight off the real app, so this drives /manifest.json
and / through the TestClient and reads the static files for the icon-existence checks.
"""

import json
from pathlib import Path

from tests._client import ApiTest

STATIC = Path(__file__).resolve().parent.parent / "static"


class ManifestTests(ApiTest):
    def _manifest(self):
        r = self.client.get("/manifest.json")
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_manifest_served(self):
        r = self.client.get("/manifest.json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r.headers.get("content-type", ""))

    def test_has_core_fields(self):
        m = self._manifest()
        for k in ("name", "short_name", "start_url", "display", "theme_color", "background_color"):
            self.assertIn(k, m, f"manifest missing {k}")
        self.assertEqual(m["display"], "standalone")

    def test_icons_exist(self):
        m = self._manifest()
        self.assertTrue(m.get("icons"))
        for ic in m["icons"]:
            rel = ic["src"].lstrip("/").replace("static/", "", 1)
            self.assertTrue((STATIC / rel).exists(), f"icon file missing: {ic['src']}")

    def test_maskable_icon_present(self):
        m = self._manifest()
        purposes = " ".join(ic.get("purpose", "") for ic in m["icons"])
        self.assertIn("maskable", purposes)

    def test_has_orientation(self):
        self.assertIn("orientation", self._manifest())

    def test_has_categories(self):
        m = self._manifest()
        self.assertIsInstance(m.get("categories"), list)
        self.assertTrue(m["categories"])

    def test_has_scope_and_id(self):
        m = self._manifest()
        self.assertIn("scope", m)
        self.assertIn("id", m)

    def test_has_shortcuts(self):
        m = self._manifest()
        self.assertIsInstance(m.get("shortcuts"), list)
        self.assertGreaterEqual(len(m["shortcuts"]), 1)

    def test_shortcuts_have_url_and_name(self):
        for sc in self._manifest()["shortcuts"]:
            self.assertTrue(sc.get("name"))
            self.assertTrue(sc.get("url"))

    def test_index_has_viewport(self):
        html = self.client.get("/").text
        self.assertIn('name="viewport"', html)
        self.assertIn("width=device-width", html)

    def test_index_has_mobile_web_app_capable(self):
        # Android (non-apple) standalone hint — was missing before 11b
        html = self.client.get("/").text
        self.assertIn('name="mobile-web-app-capable"', html)

    def test_index_has_apple_meta(self):
        html = self.client.get("/").text
        self.assertIn("apple-mobile-web-app-capable", html)
        self.assertIn("apple-touch-icon", html)

    def test_manifest_is_valid_json_file(self):
        # the static file itself must parse (the route just streams it)
        json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
