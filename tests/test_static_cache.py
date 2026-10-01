import os
import tempfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from tests._client import ApiTest


class StaticCacheTests(ApiTest):
    def setUp(self):
        super().setUp()
        from app import NoCacheStatic

        self.assets = tempfile.TemporaryDirectory(prefix="alles-static-cache-")
        self.root = Path(self.assets.name)
        (self.root / "app.js").write_text("const value = 1;\n")
        (self.root / "app.css").write_text("body { color: black; }\n")
        (self.root / "page.html").write_text("<p>example</p>\n")
        static_app = Starlette(routes=[Mount("/static", NoCacheStatic(directory=self.root))])
        self.asset_client = TestClient(static_app)

    def tearDown(self):
        self.asset_client.close()
        self.assets.cleanup()
        super().tearDown()

    def test_code_is_private_and_requires_revalidation(self):
        for asset in ("app.js", "app.css"):
            with self.subTest(asset=asset):
                response = self.asset_client.get(f"/static/{asset}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "private, no-cache")
                self.assertIn("etag", response.headers)
                self.assertIn("last-modified", response.headers)
                cached = self.asset_client.get(
                    f"/static/{asset}", headers={"If-None-Match": response.headers["etag"]}
                )
                self.assertEqual(cached.status_code, 304)
                self.assertEqual(cached.content, b"")
                self.assertEqual(cached.headers["cache-control"], "private, no-cache")

    def test_last_modified_validation_is_preserved(self):
        response = self.asset_client.get("/static/app.css")
        cached = self.asset_client.get(
            "/static/app.css",
            headers={"If-Modified-Since": response.headers["last-modified"]},
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_changed_code_at_the_same_url_returns_fresh_bytes(self):
        path = self.root / "app.js"
        response = self.asset_client.get("/static/app.js")
        timestamp = path.stat().st_mtime
        path.write_text("const value = 2;\n")
        os.utime(path, (timestamp + 2, timestamp + 2))
        changed = self.asset_client.get(
            "/static/app.js", headers={"If-None-Match": response.headers["etag"]}
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.text, "const value = 2;\n")
        self.assertNotEqual(changed.headers["etag"], response.headers["etag"])
        self.assertNotEqual(changed.headers["last-modified"], response.headers["last-modified"])

    def test_html_and_service_worker_are_not_retained(self):
        self.assertIn(
            "no-store", self.asset_client.get("/static/page.html").headers["cache-control"]
        )
        for path in ("/", "/sw.js"):
            with self.subTest(path=path):
                self.assertIn("no-store", self.client.get(path).headers["cache-control"])
