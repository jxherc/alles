import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
import routes.vault as vault_routes
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
        self.tok = self.client.post(
            "/api/vault/unlock", json={"password": "master-password-1"}
        ).json()["token"]
        self.h = {"X-Vault-Token": self.tok}

    def tearDown(self):
        vault_routes._unlock_tokens.pop(self.tok, None)
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _add(self, name, url, user="me", pw="pw", typ="login"):
        response = self.client.post(
            "/api/vault",
            json={
                "name": name,
                "type": typ,
                "username": user,
                "fields": {"username": user, "password": pw, "url": url},
            },
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _match(self, domain, headers=None):
        return self.client.get(
            "/api/vault/match",
            params={"domain": domain},
            headers=headers if headers is not None else self.h,
        )

    def test_retired_route_is_gone_with_or_without_a_valid_token(self):
        for headers in (self.h, {}):
            with self.subTest(headers=bool(headers)):
                response = self._match("github.com", headers=headers)
                self.assertEqual(response.status_code, 410)
                self.assertIn("retired", response.json()["detail"])

    def test_retired_route_never_returns_credentials(self):
        self._add("GitHub", "https://github.com", user="octocat", pw="s3cret")
        response = self._match("github.com")
        self.assertEqual(response.status_code, 410)
        self.assertNotIn("octocat", response.text)
        self.assertNotIn("s3cret", response.text)

    def test_rejected_extension_call_revokes_the_exact_unlock_token(self):
        self.assertIn(self.tok, vault_routes._unlock_tokens)
        self.assertEqual(self._match("github.com").status_code, 410)
        self.assertNotIn(self.tok, vault_routes._unlock_tokens)

    def test_normal_passwords_web_reveal_still_works(self):
        created = self._add("GitHub", "https://github.com", user="octocat", pw="s3cret")
        response = self.client.get(
            f"/api/vault/{created['id']}/reveal",
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"]["password"], "s3cret")


class ExtensionFilesTests(ApiTest):
    def test_extension_manifest_valid_mv3(self):
        man = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["manifest_version"], 3)
        self.assertTrue(man.get("name"))

    def test_extension_requests_only_current_tab_storage_idle_and_optional_hosts(self):
        man = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(man["permissions"]), {"activeTab", "scripting", "storage", "idle"})
        self.assertNotIn("host_permissions", man)
        self.assertNotIn("content_scripts", man)
        self.assertNotIn("<all_urls>", man["optional_host_permissions"])
        self.assertEqual(man["background"], {"service_worker": "background.js"})
        self.assertTrue((EXT / "background.js").exists())
        self.assertFalse((EXT / "content.js").exists())
        self.assertTrue((EXT / "popup.js").exists())

    def test_extension_uses_paired_storage_and_top_frame_only(self):
        source = "\n".join(path.read_text("utf-8") for path in EXT.iterdir() if path.is_file())
        self.assertNotIn("X-Vault-Token", source)
        self.assertIn("chrome.storage.local", source)
        self.assertIn("chrome.storage.session", source)
        self.assertNotIn("<all_urls>", source)
        self.assertIn("frameIds: [0]", source)
        self.assertNotIn("allFrames", source)
        self.assertIn("new-password", source)
        self.assertNotIn(".submit(", source)
