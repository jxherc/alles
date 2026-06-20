import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest

EXT = Path(__file__).resolve().parent.parent / "extension"


class AutofillMatchTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9d3-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _add(self, name, url, user="me", pw="pw", typ="login"):
        self.client.post(
            "/api/vault",
            json={
                "name": name,
                "type": typ,
                "username": user,
                "fields": {"username": user, "password": pw, "url": url},
            },
            headers=self.h,
        )

    def _match(self, domain, headers=None):
        return self.client.get(
            "/api/vault/match",
            params={"domain": domain},
            headers=headers if headers is not None else self.h,
        )

    def test_match_by_host(self):
        self._add("GitHub", "https://github.com/login")
        m = self._match("github.com").json()
        self.assertEqual([x["name"] for x in m], ["GitHub"])

    def test_match_strips_www(self):
        self._add("GitHub", "https://www.github.com")
        self.assertEqual(len(self._match("github.com").json()), 1)

    def test_match_subdomain(self):
        self._add("GitHub", "https://github.com")
        self.assertEqual(len(self._match("gist.github.com").json()), 1)

    def test_no_match_empty(self):
        self._add("GitHub", "https://github.com")
        self.assertEqual(self._match("example.org").json(), [])

    def test_match_requires_unlock(self):
        self.assertEqual(self._match("github.com", headers={}).status_code, 403)

    def test_match_returns_credentials(self):
        self._add("GitHub", "https://github.com", user="octocat", pw="s3cret")
        m = self._match("github.com").json()[0]
        self.assertEqual(m["username"], "octocat")
        self.assertEqual(m["password"], "s3cret")

    def test_match_only_logins(self):
        self._add("GitHub", "https://github.com")
        # a secure note that happens to mention a url shouldn't autofill
        self.client.post(
            "/api/vault",
            json={"name": "note", "type": "note", "fields": {"notes": "github.com is great"}},
            headers=self.h,
        )
        self.assertEqual(len(self._match("github.com").json()), 1)

    def test_match_case_insensitive(self):
        self._add("GitHub", "https://github.com")
        self.assertEqual(len(self._match("GitHub.com").json()), 1)


class ExtensionFilesTests(ApiTest):
    def test_extension_manifest_valid_mv3(self):
        man = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["manifest_version"], 3)
        self.assertTrue(man.get("name"))

    def test_extension_has_content_script(self):
        man = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        cs = man["content_scripts"][0]["js"][0]
        self.assertTrue((EXT / cs).is_file())
