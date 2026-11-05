import base64
import hashlib
import re
import tempfile
from pathlib import Path
from unittest import mock

import core.auth
import core.settings
from tests._client import ApiTest


def _basic(secret: str) -> dict:
    raw = base64.b64encode(f"obsidian:{secret}".encode()).decode()
    return {"authorization": f"Basic {raw}"}


class _DavCase(ApiTest):
    def setUp(self):
        super().setUp()
        core.auth._login_fails.clear()
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


class DocsWebdavTest(_DavCase):
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
        for method, code in (("DELETE", 403), ("MOVE", 403), ("COPY", 405)):
            self.assertEqual(
                self.client.request(method, "/dav/docs/hello.md", headers=auth).status_code, code
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

    def test_write_mode_saves_any_file_and_makes_folders(self):
        auth = _basic(self._mode("write")["token"])
        # remotely save's connection check writes a file with no extension
        put = self.client.put("/dav/docs/pic.png", content=b"\x89PNG1", headers=auth)
        self.assertEqual(put.status_code, 201)
        self.assertEqual((self.vault / "pic.png").read_bytes(), b"\x89PNG1")
        again = self.client.put("/dav/docs/pic.png", content=b"two", headers=auth)
        self.assertEqual(again.status_code, 204)
        self.assertEqual(self.client.get("/dav/docs/pic.png", headers=auth).content, b"two")
        hidden = self.client.put("/dav/docs/.obsidian/x.json", content=b"{}", headers=auth)
        self.assertEqual(hidden.status_code, 404)
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

    def test_the_plugin_address_is_the_parent_of_the_docs_endpoint(self):
        shown = self.client.get("/api/setup/obsidian-lan").json()
        self.assertTrue(shown["url"].endswith(":80/dav") or shown["url"].endswith("/dav"))
        self.assertEqual(shown["folder"], "docs")
        self.assertEqual(shown["vault_name"], "Vault")
        self.assertFalse(shown["https"])

    def test_an_https_address_the_owner_came_through_is_used_for_the_link(self):
        host = self.client.get("/api/setup/obsidian-lan", params={"origin": "https://testserver"})
        self.assertEqual(host.json()["url"], "https://testserver/dav")
        self.assertTrue(host.json()["https"])
        # an origin that is not this server's own host, or is this machine, is not trusted
        for origin in ("https://evil.example", "http://localhost:6769", "javascript:alert(1)", ""):
            got = self.client.get("/api/setup/obsidian-lan", params={"origin": origin}).json()
            self.assertNotIn("evil.example", got["url"])
            self.assertFalse(got["https"], origin)
        made = self.client.post(
            "/api/setup/obsidian-lan", json={"mode": "write", "origin": "https://testserver"}
        )
        self.assertEqual(made.json()["url"], "https://testserver/dav")

    def test_bad_mode_is_refused(self):
        response = self.client.post("/api/setup/obsidian-lan", json={"mode": "everything"})
        self.assertEqual(response.status_code, 400)


class DocsWebdavSyncTest(_DavCase):
    """DELETE and MOVE, the two calls a Remotely Save sync needs beyond saving."""

    def setUp(self):
        super().setUp()
        self.auth = _basic(self._mode("write")["token"])

    def _trash(self) -> list[dict]:
        return self.client.get("/api/vault-md/trash").json()

    def _move(self, src, dst, **headers):
        return self.client.request(
            "MOVE", "/dav/docs/" + src, headers={**self.auth, "Destination": dst, **headers}
        )

    def test_delete_moves_a_note_to_trash_and_it_can_come_back(self):
        gone = self.client.delete("/dav/docs/hello.md", headers=self.auth)
        self.assertEqual(gone.status_code, 204)
        self.assertFalse((self.vault / "hello.md").exists())
        rows = self._trash()
        self.assertEqual([row["path"] for row in rows], ["hello.md"])
        back = self.client.post("/api/vault-md/trash/restore", json={"id": rows[0]["id"]})
        self.assertEqual(back.status_code, 200, back.text)
        self.assertEqual((self.vault / "hello.md").read_text(), "# hello\n")

    def test_delete_a_folder_trashes_the_whole_folder(self):
        self.assertEqual(self.client.delete("/dav/docs/school", headers=self.auth).status_code, 204)
        self.assertFalse((self.vault / "school").exists())
        listing = self.client.request("PROPFIND", "/dav/docs/school/", headers=self.auth)
        self.assertEqual(listing.status_code, 404)
        self.assertEqual([row["path"] for row in self._trash()], ["school"])

    def test_delete_misses_and_refusals(self):
        self.assertEqual(
            self.client.delete("/dav/docs/nope.md", headers=self.auth).status_code, 404
        )
        self.assertEqual(self.client.delete("/dav/docs/", headers=self.auth).status_code, 403)
        hidden = self.client.delete("/dav/docs/.obsidian/app.json", headers=self.auth)
        self.assertEqual(hidden.status_code, 404)
        self.assertTrue((self.vault / ".obsidian" / "app.json").exists())
        up = self.client.delete("/dav/docs/%2e%2e/outside.md", headers=self.auth)
        self.assertIn(up.status_code, (403, 404))

    def test_the_connection_check_scratch_folder_is_not_kept_in_trash(self):
        folder = "/dav/docs/rs-test-folder-abc/"
        self.assertEqual(self.client.request("MKCOL", folder, headers=self.auth).status_code, 201)
        file = folder + "rs-test-file-abc"
        first = self.client.put(file, content=b"\0" * 100, headers=self.auth)
        self.assertEqual(first.status_code, 201)
        second = self.client.put(file, content=b"\0" * 200, headers=self.auth)
        self.assertEqual(second.status_code, 204)
        self.assertEqual(len(self.client.get(file, headers=self.auth).content), 200)
        self.assertEqual(self.client.delete(file, headers=self.auth).status_code, 204)
        self.assertEqual(self.client.delete(folder, headers=self.auth).status_code, 204)
        self.assertFalse((self.vault / "rs-test-folder-abc").exists())
        self.assertEqual(self._trash(), [])

    def test_delete_and_move_need_a_write_token(self):
        made = self.client.post("/api/tokens", json={"name": "r", "scopes": ["read"]})
        read = _basic(made.json()["token"])
        self.assertEqual(self.client.delete("/dav/docs/hello.md", headers=read).status_code, 403)
        moved = self.client.request(
            "MOVE", "/dav/docs/hello.md", headers={**read, "Destination": "/dav/docs/b.md"}
        )
        self.assertEqual(moved.status_code, 403)
        wrong = self.client.delete("/dav/docs/hello.md", headers=_basic("alles_wrong"))
        self.assertEqual(wrong.status_code, 401)
        self.assertTrue((self.vault / "hello.md").exists())

    def test_move_renames_a_file_with_a_full_url_or_a_path(self):
        done = self._move("hello.md", "http://testserver/dav/docs/school/hi%20there.md")
        self.assertEqual(done.status_code, 201)
        self.assertEqual((self.vault / "school" / "hi there.md").read_text(), "# hello\n")
        self.assertFalse((self.vault / "hello.md").exists())
        again = self._move("school/hi%20there.md", "/dav/docs/back.md")
        self.assertEqual(again.status_code, 201)
        self.assertTrue((self.vault / "back.md").is_file())

    def test_move_renames_a_folder_and_keeps_what_is_inside(self):
        self.assertEqual(self._move("school", "/dav/docs/class").status_code, 201)
        self.assertEqual((self.vault / "class" / "ics4u notes.md").read_text(), "js notes\n")
        listing = self.client.request("PROPFIND", "/dav/docs/", headers={**self.auth, "Depth": "1"})
        self.assertIn("/dav/docs/class/", listing.text)
        self.assertNotIn("/dav/docs/school/", listing.text)

    def test_move_over_a_file_trashes_the_old_one_and_overwrite_f_refuses(self):
        (self.vault / "other.md").write_text("other\n", "utf-8")
        refused = self._move("hello.md", "/dav/docs/other.md", Overwrite="F")
        self.assertEqual(refused.status_code, 412)
        self.assertEqual((self.vault / "other.md").read_text(), "other\n")
        done = self._move("hello.md", "/dav/docs/other.md")
        self.assertEqual(done.status_code, 204)
        self.assertEqual((self.vault / "other.md").read_text(), "# hello\n")
        self.assertEqual([row["path"] for row in self._trash()], ["other.md"])

    def test_move_refusals(self):
        self.assertEqual(self._move("nope.md", "/dav/docs/x.md").status_code, 404)
        self.assertEqual(self._move("hello.md", "/dav/docs/missing/x.md").status_code, 409)
        self.assertEqual(self._move("hello.md", "/dav/docs/hello.md").status_code, 403)
        self.assertEqual(self._move("school", "/dav/docs/school/inner").status_code, 403)
        self.assertEqual(self._move("hello.md", "/dav/docs/.obsidian/x.md").status_code, 403)
        self.assertEqual(self._move("hello.md", "/dav/docs/%2e%2e/x.md").status_code, 403)
        self.assertEqual(self._move("hello.md", "/elsewhere/x.md").status_code, 502)
        other = self._move("hello.md", "http://elsewhere.test/dav/docs/x.md")
        self.assertEqual(other.status_code, 502)
        self.assertEqual(self._move("hello.md", "").status_code, 502)
        self.assertEqual(self._move(".obsidian/app.json", "/dav/docs/x.json").status_code, 404)
        self.assertTrue((self.vault / "hello.md").exists())
        self.assertTrue((self.vault / ".obsidian" / "app.json").exists())

    def test_links_in_the_folder_are_never_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret\n", "utf-8")
        (self.vault / "link").symlink_to(outside, target_is_directory=True)
        (self.vault / "inner.md").symlink_to(self.vault / "hello.md")
        for method in ("GET", "PUT", "DELETE"):
            for path in ("link/secret.md", "link", "inner.md"):
                response = self.client.request(
                    method, "/dav/docs/" + path, content=b"x", headers=self.auth
                )
                self.assertIn(response.status_code, (403, 404), (method, path))
        self.assertEqual(self._move("link", "/dav/docs/taken").status_code, 404)
        self.assertEqual(self._move("hello.md", "/dav/docs/link/x.md").status_code, 403)
        self.assertEqual((outside / "secret.md").read_text(), "secret\n")
        self.assertEqual(list(outside.iterdir()), [outside / "secret.md"])
        self.assertTrue((self.vault / "link").is_symlink())
        listing = self.client.request("PROPFIND", "/dav/docs/", headers={**self.auth, "Depth": "1"})
        self.assertNotIn("link", listing.text)

    def test_propfind_shapes_clients_rely_on(self):
        zero = {**self.auth, "Depth": "0"}
        root = self.client.request("PROPFIND", "/dav/docs", headers=zero)
        self.assertEqual(root.status_code, 207)
        self.assertEqual(root.text.count("<d:response>"), 1)
        self.assertIn("<d:collection/>", root.text)
        for path in ("/dav/docs/school", "/dav/docs/school/"):
            one = self.client.request("PROPFIND", path, headers={**self.auth, "Depth": "1"})
            self.assertEqual(one.text.count("<d:response>"), 2)
            self.assertIn("<d:href>/dav/docs/school/</d:href>", one.text)
        gone = self.client.request("PROPFIND", "/dav/docs/missing/", headers=self.auth)
        self.assertEqual(gone.status_code, 404)
        info = self.client.request("PROPFIND", "/dav/docs/hello.md", headers=zero)
        self.assertEqual(info.text.count("<d:response>"), 1)
        self.assertIn("<d:getcontentlength>8</d:getcontentlength>", info.text)
        options = self.client.options("/dav/docs/", headers=self.auth)
        for method in ("DELETE", "MOVE", "MKCOL", "PUT"):
            self.assertIn(method, options.headers["allow"])
        self.assertEqual(options.headers["dav"], "1")
