import base64
import hashlib
import re
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


def _basic(secret: str) -> dict:
    raw = base64.b64encode(f"obsidian:{secret}".encode()).decode()
    return {"authorization": f"Basic {raw}"}


class DocsWebdavTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-dav-")
        self.root = Path(self.tmp.name)
        self.settings_patch = mock.patch.object(
            core.settings, "_SETTINGS_FILE", self.root / "settings.json"
        )
        self.settings_patch.start()
        core.settings._clear_settings_cache()
        self.vault = self.root / "Vault"
        (self.vault / "school").mkdir(parents=True)
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "app.json").write_text("{}")
        (self.vault / "_assets").mkdir()
        (self.vault / "_assets" / "pic.png").write_bytes(b"\x89PNG")
        (self.vault / "hello.md").write_text("# hello\n", "utf-8")
        (self.vault / "school" / "ics4u notes.md").write_text("js notes\n", "utf-8")
        core.settings.save_settings({"vault_dir": str(self.vault)})

    def tearDown(self):
        core.settings._clear_settings_cache()
        self.settings_patch.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mode(self, mode: str) -> dict:
        response = self.client.post("/api/setup/obsidian-lan", json={"mode": mode})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_off_by_default(self):
        self.assertEqual(self.client.request("PROPFIND", "/dav/docs/").status_code, 404)
        self.assertEqual(self.client.get("/dav/docs/hello.md").status_code, 404)

    def test_read_mode_lists_and_reads_but_never_writes(self):
        token = self._mode("read")["token"]
        auth = _basic(token)
        options = self.client.options("/dav/docs/", headers=auth)
        self.assertEqual(options.status_code, 200)
        self.assertIn("PROPFIND", options.headers["allow"])

        listing = self.client.request("PROPFIND", "/dav/docs/", headers={**auth, "Depth": "1"})
        self.assertEqual(listing.status_code, 207)
        self.assertIn("hello.md", listing.text)
        self.assertIn("/dav/docs/school/", listing.text)
        self.assertNotIn(".obsidian", listing.text)

        deep = self.client.request("PROPFIND", "/dav/docs/", headers={**auth, "Depth": "infinity"})
        self.assertIn("ics4u%20notes.md", deep.text)
        self.assertIn("_assets/pic.png", deep.text)

        body = self.client.get("/dav/docs/hello.md", headers=auth)
        self.assertEqual(body.text, "# hello\n")
        digest = hashlib.sha256(b"# hello\n").hexdigest()
        self.assertEqual(body.headers["etag"], f'"{digest}"')
        self.assertEqual(self.client.head("/dav/docs/hello.md", headers=auth).status_code, 200)

        denied = self.client.put("/dav/docs/hello.md", content=b"changed", headers=auth)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual((self.vault / "hello.md").read_text(), "# hello\n")
        for method in ("DELETE", "MOVE", "COPY"):
            self.assertEqual(
                self.client.request(method, "/dav/docs/hello.md", headers=auth).status_code, 405
            )
        self.assertTrue((self.vault / "hello.md").exists())

    def test_hidden_folders_and_escapes_are_refused(self):
        auth = _basic(self._mode("read")["token"])
        self.assertEqual(
            self.client.get("/dav/docs/.obsidian/app.json", headers=auth).status_code, 404
        )
        self.assertIn(
            self.client.get("/dav/docs/%2e%2e/%2e%2e/etc/passwd", headers=auth).status_code,
            (403, 404),
        )

    def test_a_wrong_password_is_challenged(self):
        self._mode("read")
        response = self.client.get("/dav/docs/hello.md", headers=_basic("alles_wrong"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["www-authenticate"])

    def test_a_read_token_cannot_write_even_when_writes_are_on(self):
        write_token = self._mode("write")["token"]
        read_only = self.client.post("/api/tokens", json={"name": "other", "scopes": ["read"]})
        read_token = read_only.json()["token"]
        refused = self.client.put("/dav/docs/new.md", content=b"x", headers=_basic(read_token))
        self.assertEqual(refused.status_code, 403)
        self.assertFalse((self.vault / "new.md").exists())
        ok = self.client.put("/dav/docs/new.md", content=b"x", headers=_basic(write_token))
        self.assertEqual(ok.status_code, 201)

    def test_write_mode_saves_through_docs_and_keeps_a_revision(self):
        auth = _basic(self._mode("write")["token"])
        created = self.client.put("/dav/docs/school/new.md", content=b"first\n", headers=auth)
        self.assertEqual(created.status_code, 201)
        self.assertEqual((self.vault / "school" / "new.md").read_text(), "first\n")

        tag = created.headers["etag"]
        updated = self.client.put(
            "/dav/docs/school/new.md", content=b"second\n", headers={**auth, "If-Match": tag}
        )
        self.assertEqual(updated.status_code, 204)
        self.assertEqual((self.vault / "school" / "new.md").read_text(), "second\n")
        revisions = self.client.get(
            "/api/vault-md/safety/revisions", params={"path": "school/new.md"}
        )
        self.assertEqual(revisions.status_code, 200)
        self.assertGreaterEqual(len(revisions.json().get("revisions", revisions.json())), 1)

        stale = self.client.put(
            "/dav/docs/school/new.md", content=b"lost?\n", headers={**auth, "If-Match": tag}
        )
        self.assertEqual(stale.status_code, 412)
        self.assertEqual((self.vault / "school" / "new.md").read_text(), "second\n")

    def test_write_mode_only_saves_markdown_and_makes_folders(self):
        auth = _basic(self._mode("write")["token"])
        self.assertEqual(
            self.client.put("/dav/docs/pic.png", content=b"x", headers=auth).status_code, 403
        )
        self.assertEqual(
            self.client.request("MKCOL", "/dav/docs/ideas", headers=auth).status_code, 201
        )
        self.assertTrue((self.vault / "ideas").is_dir())
        self.assertEqual(
            self.client.request("MKCOL", "/dav/docs/ideas", headers=auth).status_code, 405
        )

    def test_turning_it_off_ends_the_token(self):
        token = self._mode("read")["token"]
        self.assertEqual(
            self.client.get("/dav/docs/hello.md", headers=_basic(token)).status_code, 200
        )
        self._mode("off")
        self.assertEqual(
            self.client.get("/dav/docs/hello.md", headers=_basic(token)).status_code, 404
        )
        self._mode("read")
        self.assertEqual(
            self.client.get("/dav/docs/hello.md", headers=_basic(token)).status_code, 401
        )

    def test_status_shows_a_local_address_and_the_mode(self):
        status = self.client.get("/api/setup/obsidian-lan").json()
        self.assertEqual(status["mode"], "off")
        shown = self._mode("read")
        self.assertEqual(shown["mode"], "read")
        self.assertTrue(re.match(r"^alles_", shown["token"]))
        self.assertNotIn("token", self.client.get("/api/setup/obsidian-lan").json())

    def test_bad_mode_is_refused(self):
        response = self.client.post("/api/setup/obsidian-lan", json={"mode": "everything"})
        self.assertEqual(response.status_code, 400)
