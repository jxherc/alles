"""a search-only browser extension (nov 7): andromeda as the default search in chromium browsers
without the vault or pairing"""

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("ALLES_DATA", tempfile.mkdtemp(prefix="alles-search-extension-"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class SearchExtensionTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def _zip(self, origin):
        response = self.client.get("/api/andromeda/search-extension", params={"origin": origin})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("andromeda-search-extension.zip", response.headers["content-disposition"])
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_the_manifest_makes_andromeda_the_default_search_at_that_address(self):
        bundle = self._zip("https://alles.example.com/somewhere?x=1")
        manifest = json.loads(bundle.read("manifest.json"))
        self.assertEqual(manifest["manifest_version"], 3)
        provider = manifest["chrome_settings_overrides"]["search_provider"]
        self.assertTrue(provider["is_default"])
        self.assertEqual(provider["keyword"], "andromeda")
        self.assertEqual(
            provider["search_url"], "https://alles.example.com/?app=andromeda&q={searchTerms}"
        )
        # nothing but the manifest and its icons: no vault code, no secrets
        self.assertEqual(
            sorted(bundle.namelist()),
            [
                "icons/icon-128.png",
                "icons/icon-16.png",
                "icons/icon-32.png",
                "icons/icon-48.png",
                "manifest.json",
            ],
        )
        for name in manifest["icons"].values():
            self.assertTrue(bundle.read(name).startswith(b"\x89PNG"), name)

    def test_its_keyword_never_matches_the_vault_extensions_shortcut(self):
        # both installed at once, two engines on one keyword sent a plain address bar search to
        # the vault extension's own chrome-extension:// page (err_file_not_found)
        vault = json.loads((ROOT / "extension" / "manifest.json").read_text("utf-8"))
        manifest = json.loads(self._zip("https://alles.example.com").read("manifest.json"))
        keyword = manifest["chrome_settings_overrides"]["search_provider"]["keyword"]
        self.assertNotEqual(keyword, vault["omnibox"]["keyword"])

    def test_a_tailnet_or_lan_address_works_too(self):
        manifest = json.loads(self._zip("http://100.79.59.4:6769").read("manifest.json"))
        self.assertEqual(
            manifest["chrome_settings_overrides"]["search_provider"]["search_url"],
            "http://100.79.59.4:6769/?app=andromeda&q={searchTerms}",
        )

    def test_a_bad_address_is_refused(self):
        for origin in ("", "javascript:alert(1)", "https://user:pw@example.com", "ftp://x.example"):
            response = self.client.get("/api/andromeda/search-extension", params={"origin": origin})
            self.assertEqual(response.status_code, 400, origin)


if __name__ == "__main__":
    unittest.main()
