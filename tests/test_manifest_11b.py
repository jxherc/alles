"""11b-2 — PWA install polish: the manifest + index head carry what iOS/Android need
to install a polished home-screen app (orientation, categories, shortcuts, scope/id,
mobile-web-app-capable). Served straight off the real app, so this drives /manifest.json
and / through the TestClient and reads the static files for the icon-existence checks.
"""

import json
import re
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

    def test_shortcuts_stay_same_origin(self):
        for sc in self._manifest()["shortcuts"]:
            url = sc["url"]
            self.assertTrue(url.startswith("/"), f"shortcut should be relative: {url}")
            self.assertFalse(
                url.startswith("//"), f"shortcut should not be protocol-relative: {url}"
            )
            self.assertNotIn("localhost", url)

    def test_shortcuts_target_app_query(self):
        got = {sc["short_name"]: sc["url"] for sc in self._manifest()["shortcuts"]}
        want = {
            "Aide": "/?app=aide",
            "Andromeda": "/?app=andromeda",
            "Plan": "/?app=plan",
        }
        for name, url in want.items():
            self.assertEqual(got.get(name), url)

    def test_shortcut_query_boots_app_nav(self):
        js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("_p.get('app')", js)
        self.assertIn("_p.get('view')", js)
        self.assertIn("navigateTo(_v)", js)

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

    def test_shell_cache_stamp_is_consistent(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        worker = (STATIC / "sw.js").read_text(encoding="utf-8")
        app_stamp = re.search(r"const _v = '(\d+)'", html)
        style_stamp = re.search(r"style\.css\?v=(\d+)", html)
        worker_stamp = re.search(r"const STAMP = '(\d+)'", worker)
        self.assertIsNotNone(app_stamp)
        self.assertIsNotNone(style_stamp)
        self.assertIsNotNone(worker_stamp)
        self.assertEqual(
            {app_stamp.group(1), style_stamp.group(1), worker_stamp.group(1)},
            {"303"},
        )

    def test_precache_uses_the_shell_stamp_and_every_linked_stylesheet(self):
        urls = self.client.get("/api/pwa/precache").json()["urls"]
        self.assertIn("/static/style.css?v=303", urls)
        self.assertNotIn("/static/style.css?v=6", urls)
        self.assertIn("/static/vendor/xterm/xterm.css?v=6.0.0", urls)
        self.assertIn("/static/vendor/xterm/xterm.mjs?v=6.0.0", urls)
        self.assertIn("/static/vendor/xterm/addon-fit.mjs?v=0.11.0", urls)
        self.assertIn("/static/kokuen.css?v=21", urls)
        for module in (
            "models.js?v=212",
            "dropdown.js?v=212",
            "specialist_groups.js?v=5",
            "kokuen.js?v=1",
            "andromeda.js?v=247",
        ):
            self.assertIn(f"/static/js/{module}", urls)
        for language in ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar"):
            self.assertIn(f"/static/locales/{language}.json", urls)
        self.assertIn("/static/locales/manifest.json", urls)

    def test_styles_use_network_first_cache_updates(self):
        worker = (STATIC / "sw.js").read_text(encoding="utf-8")
        self.assertIn("const NETWORK_FIRST_STATIC = ['.js', '.mjs', '.css'];", worker)
        self.assertIn(
            "NETWORK_FIRST_STATIC.some(ext => url.pathname.endsWith(ext))",
            worker,
        )
        self.assertIn("e.respondWith(networkFirstStatic(e.request))", worker)
        network_first = worker[
            worker.index("async function networkFirstStatic") : worker.index(
                "self.addEventListener('fetch'"
            )
        ]
        self.assertIn("if (resp.ok)", network_first)
        self.assertNotIn("if (!resp.ok)", network_first)
        self.assertLess(network_first.index("if (resp.ok)"), network_first.index("c.put"))
        self.assertRegex(
            network_first,
            r"catch \(err\)\s*\{\s*const hit = await c\.match\(request\);"
            r"\s*if \(hit\) return hit;",
        )
