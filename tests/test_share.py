import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.responses import FileResponse

from core.database import FileOperationPathClaim, Message, Photo, Session, Share, StorageLocation
from routes import shared as shared_routes
from services import files_store, photos_store, share, storage_backends, vault_md
from tests._client import ApiTest

# 1x1 png
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f1f0000000049454e44ae426082"
)


class ShareServiceTests(ApiTest):
    """services/share.py — pure helpers against the test db."""

    def test_mint_idempotent(self):
        d = self.db()
        a = share.mint(d, "doc", "note.md")
        b = share.mint(d, "doc", "note.md")
        self.assertEqual(a.token, b.token)

    def test_mint_diff_ref_diff_token(self):
        d = self.db()
        a = share.mint(d, "doc", "a.md")
        b = share.mint(d, "doc", "b.md")
        self.assertNotEqual(a.token, b.token)

    def test_file_share_uses_normalized_location_identity(self):
        d = self.db()
        original = share.mint(d, "file", "folder/./note.txt")
        same_file = share.mint(d, "file", "folder/note.txt")
        self.assertEqual(original.token, same_file.token)

    def test_file_share_revoke_accepts_an_equivalent_path(self):
        d = self.db()
        original = share.mint(d, "file", "folder/./note.txt")
        self.assertTrue(share.revoke_ref(d, "file", "folder/note.txt"))
        self.assertIsNone(share.lookup(d, original.token))

    def test_file_share_revoke_survives_a_disabled_location(self):
        with tempfile.TemporaryDirectory() as root:
            d = self.db()
            location = StorageLocation(
                id="disabled-share-location",
                name="disabled share location",
                kind="local",
                access="managed",
                root_path=root,
                enabled=True,
            )
            d.add(location)
            d.commit()
            original = share.mint(d, "file", "note.txt", location_id=location.id)
            location.enabled = False
            d.commit()

            with self.assertRaisesRegex(RuntimeError, "disabled"):
                share.mint(d, "file", "another.txt", location_id=location.id)

            original_revoke = share._revoke_ref_claimed

            def revoke_with_claim(*args, **kwargs):
                self.assertEqual(d.query(FileOperationPathClaim).count(), 1)
                return original_revoke(*args, **kwargs)

            with mock.patch.object(
                share,
                "_revoke_ref_claimed",
                side_effect=revoke_with_claim,
            ):
                self.assertTrue(share.revoke_ref(d, "file", "note.txt", location_id=location.id))
            self.assertIsNone(share.lookup(d, original.token))
            self.assertEqual(d.query(FileOperationPathClaim).count(), 0)
            d.close()

    def test_remote_share_does_not_reassign_a_legacy_default_local_token(self):
        d = self.db()
        d.add(
            StorageLocation(
                id="remote",
                name="remote",
                kind="webdav",
                access="managed",
                endpoint="https://files.example.test/webdav",
                enabled=True,
            )
        )
        legacy = Share(token="legacy-local", kind="file", ref="same.txt")
        d.add(legacy)
        d.commit()

        remote = share.mint(d, "file", "same.txt", location_id="remote")

        self.assertNotEqual(remote.token, legacy.token)
        self.assertIsNone(legacy.location_id)
        self.assertIsNone(legacy.normalized_path)

    def test_lookup_by_token(self):
        d = self.db()
        s = share.mint(d, "file", "x/y.txt")
        got = share.lookup(d, s.token)
        self.assertIsNotNone(got)
        self.assertEqual(got.kind, "file")
        self.assertEqual(got.ref, "x/y.txt")

    def test_token_for_none_then_set(self):
        d = self.db()
        self.assertIsNone(share.token_for(d, "doc", "z.md"))
        s = share.mint(d, "doc", "z.md")
        self.assertEqual(share.token_for(d, "doc", "z.md"), s.token)

    def test_revoke_by_token(self):
        d = self.db()
        s = share.mint(d, "doc", "r.md")
        self.assertTrue(share.revoke(d, s.token))
        self.assertIsNone(share.lookup(d, s.token))
        self.assertFalse(share.revoke(d, s.token))

    def test_file_revoke_by_token_holds_its_path_claim(self):
        d = self.db()
        s = share.mint(d, "file", "claimed.txt")
        original_revoke = share._revoke_token_claimed

        def revoke_with_claim(*args, **kwargs):
            self.assertEqual(d.query(FileOperationPathClaim).count(), 1)
            return original_revoke(*args, **kwargs)

        with mock.patch.object(
            share,
            "_revoke_token_claimed",
            side_effect=revoke_with_claim,
        ):
            self.assertTrue(share.revoke(d, s.token))

        self.assertIsNone(share.lookup(d, s.token))
        self.assertEqual(d.query(FileOperationPathClaim).count(), 0)
        d.close()

    def test_revoke_ref(self):
        d = self.db()
        share.mint(d, "doc", "rr.md")
        self.assertTrue(share.revoke_ref(d, "doc", "rr.md"))
        self.assertIsNone(share.token_for(d, "doc", "rr.md"))

    def test_bad_kind_raises(self):
        d = self.db()
        with self.assertRaises(ValueError):
            share.mint(d, "nonsense", "a.md")

    def test_empty_ref_raises(self):
        d = self.db()
        with self.assertRaises(ValueError):
            share.mint(d, "doc", "   ")

    def test_level_default_view_and_download(self):
        d = self.db()
        a = share.mint(d, "file", "f1")
        self.assertEqual(a.level, "view")
        b = share.mint(d, "file", "f2", level="download")
        self.assertEqual(b.level, "download")
        # idempotent mint can upgrade level
        c = share.mint(d, "file", "f1", level="download")
        self.assertEqual(c.token, a.token)
        self.assertEqual(c.level, "download")

    def test_md_to_html_rules(self):
        html = share.md_to_html(
            "# Title\n\nsome **bold** and `code` and [x](http://e.com)\n\n- one\n- two"
        )
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertIn('<a href="http://e.com"', html)
        self.assertIn("<li>one</li>", html)
        # html is escaped
        self.assertIn("&lt;script&gt;", share.md_to_html("<script>"))
        # fenced code
        self.assertIn("<pre>", share.md_to_html("```\nx=1\n```"))

    def test_shared_folder_distinguishes_unknown_size_from_zero_bytes(self):
        location = SimpleNamespace(id="remote", kind="webdav")
        with (
            mock.patch.object(
                storage_backends,
                "item",
                return_value={"type": "dir"},
            ),
            mock.patch.object(
                storage_backends,
                "listdir",
                return_value={
                    "items": [
                        {
                            "path": "folder/unknown.bin",
                            "type": "file",
                            "size": None,
                        },
                        {
                            "path": "folder/empty.bin",
                            "type": "file",
                            "size": 0,
                        },
                    ]
                },
            ),
        ):
            entries = shared_routes._shared_folder_entries(location, "folder")

        self.assertEqual(entries, [("empty.bin", 0), ("unknown.bin", None)])
        html = shared_routes._folder_html("folder", "token", entries, "view")
        self.assertIn("size unknown", html)
        self.assertIn("0 B", html)

    def test_shared_folder_counts_directories_and_rejects_out_of_root_entries(self):
        location = SimpleNamespace(id="remote", kind="webdav")
        directory_listing = {
            "items": [
                {"path": "folder/one", "type": "dir", "size": 0},
                {"path": "folder/two", "type": "dir", "size": 0},
                {"path": "folder/three", "type": "dir", "size": 0},
            ]
        }
        with (
            mock.patch.object(shared_routes, "MAX_SHARED_FOLDER_ITEMS", 2, create=True),
            mock.patch.object(storage_backends, "item", return_value={"type": "dir"}),
            mock.patch.object(
                storage_backends,
                "listdir",
                side_effect=lambda _location, path: (
                    directory_listing if path == "folder" else {"items": []}
                ),
            ),
        ):
            with self.assertRaisesRegex(storage_backends.StorageBackendError, "too many"):
                shared_routes._shared_folder_entries(location, "folder")

        with (
            mock.patch.object(storage_backends, "item", return_value={"type": "dir"}),
            mock.patch.object(
                storage_backends,
                "listdir",
                return_value={
                    "items": [
                        {"path": "sibling/private.txt", "type": "file", "size": 7},
                    ]
                },
            ),
        ):
            with self.assertRaisesRegex(storage_backends.StorageBackendError, "outside"):
                shared_routes._shared_folder_entries(location, "folder")

    def test_shared_folder_rejects_non_file_listing_objects(self):
        location = SimpleNamespace(id="remote", kind="webdav")
        with (
            mock.patch.object(storage_backends, "item", return_value={"type": "dir"}),
            mock.patch.object(
                storage_backends,
                "listdir",
                return_value={
                    "items": [
                        {"path": "folder/link", "type": "symlink", "size": 7},
                    ]
                },
            ),
        ):
            with self.assertRaisesRegex(storage_backends.StorageBackendError, "unsupported"):
                shared_routes._shared_folder_entries(location, "folder")

    def test_root_shared_folder_rejects_missing_or_empty_listing_paths(self):
        location = SimpleNamespace(id="remote", kind="webdav")
        for item in ({"type": "file", "size": 1}, {"path": "", "type": "dir"}):
            with (
                self.subTest(item=item),
                mock.patch.object(storage_backends, "item", return_value={"type": "dir"}),
                mock.patch.object(
                    storage_backends,
                    "listdir",
                    return_value={"items": [item]},
                ),
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError, "path is invalid"
                ):
                    shared_routes._shared_folder_entries(location, "")

    def test_remote_shared_response_preserves_name_and_cleans_up_on_send_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "opaque-transfer-id"
            target.write_bytes(b"shared")
            response = shared_routes._file_resp(
                target,
                "download",
                filename="note.txt",
                cleanup_path=target,
            )

            self.assertIn('filename="note.txt"', response.headers["content-disposition"])

            async def fail_delivery(_response, _scope, _receive, _send):
                raise RuntimeError("client disconnected")

            def remove(path):
                Path(path).unlink(missing_ok=True)

            with (
                mock.patch.object(storage_backends, "remove_temporary", side_effect=remove),
                mock.patch.object(FileResponse, "__call__", new=fail_delivery),
            ):
                with self.assertRaisesRegex(RuntimeError, "client disconnected"):
                    asyncio.run(response({}, None, None))

            self.assertFalse(target.exists())


class ShareApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "vault").mkdir()
        (root / "files").mkdir()
        (root / "photos").mkdir()
        self._patches = [
            mock.patch.object(vault_md, "vault_dir", lambda: root / "vault"),
            mock.patch.object(files_store, "files_dir", lambda: root / "files"),
            mock.patch.object(photos_store, "photos_dir", lambda: root / "photos"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_api_post_mint(self):
        r = self.client.post("/api/share", json={"kind": "doc", "ref": "note.md"})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["token"])
        self.assertEqual(j["url"], f"/s/{j['token']}")
        self.assertEqual(j["kind"], "doc")

    def test_api_mints_password_share_without_returning_secret(self):
        r = self.client.post(
            "/api/share",
            json={
                "kind": "doc",
                "ref": "protected.md",
                "password": "hunter2",
                "expires_at": "2099-01-01T00:00:00",
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["password_protected"])
        self.assertEqual(body["expires_at"], "2099-01-01T00:00:00Z")
        self.assertNotIn("password", body)
        self.assertNotIn("password_hash", body)
        state = self.client.get("/api/share", params={"kind": "doc", "ref": "protected.md"}).json()
        self.assertTrue(state["password_protected"])

    def test_api_post_bad_kind_400(self):
        r = self.client.post("/api/share", json={"kind": "weird", "ref": "x"})
        self.assertEqual(r.status_code, 400)

    def test_api_rejects_invalid_expiry(self):
        response = self.client.post(
            "/api/share",
            json={"kind": "doc", "ref": "bad-expiry.md", "expires_at": "not-a-date"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid ISO", response.json()["detail"])

    def test_api_get_state(self):
        before = self.client.get("/api/share", params={"kind": "doc", "ref": "g.md"}).json()
        self.assertIsNone(before["token"])
        tok = self.client.post("/api/share", json={"kind": "doc", "ref": "g.md"}).json()["token"]
        after = self.client.get("/api/share", params={"kind": "doc", "ref": "g.md"}).json()
        self.assertEqual(after["token"], tok)

    def test_api_delete_revokes(self):
        tok = self.client.post("/api/share", json={"kind": "doc", "ref": "d.md"}).json()["token"]
        r = self.client.request("DELETE", "/api/share", json={"kind": "doc", "ref": "d.md"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_view_doc_html(self):
        vault_md.write("note.md", "# Hello\n\n**bold** body")
        tok = self.client.post("/api/share", json={"kind": "doc", "ref": "note.md"}).json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("<h1>Hello</h1>", r.text)
        self.assertIn("<strong>bold</strong>", r.text)
        self.assertIn("read-only", r.text)

    def test_view_file_inline(self):
        (files_store.files_dir() / "hi.txt").write_text("plain file body", "utf-8")
        tok = self.client.post("/api/share", json={"kind": "file", "ref": "hi.txt"}).json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("plain file body", r.text)
        self.assertNotIn("attachment", r.headers.get("content-disposition", ""))

    def test_view_file_download(self):
        (files_store.files_dir() / "dl.txt").write_text("download me", "utf-8")
        tok = self.client.post(
            "/api/share", json={"kind": "file", "ref": "dl.txt", "level": "download"}
        ).json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers.get("content-disposition", "").lower())

    def test_root_folder_share_serves_its_listed_children(self):
        (files_store.files_dir() / "root-child.txt").write_text("root child", "utf-8")
        minted = self.client.post(
            "/api/share",
            json={"kind": "folder", "ref": "/", "level": "view"},
        )
        self.assertEqual(minted.status_code, 200)
        token = minted.json()["token"]
        listing = self.client.get(f"/s/{token}")
        self.assertEqual(listing.status_code, 200)
        self.assertIn("root-child.txt", listing.text)
        child = self.client.get(f"/s/{token}/root-child.txt")
        self.assertEqual(child.status_code, 200)
        self.assertEqual(child.text, "root child")

    def test_folder_share_rejects_direct_hidden_path_requests(self):
        root = files_store.files_dir() / "shared"
        (root / ".git").mkdir(parents=True)
        (root / ".env").write_text("secret", encoding="utf-8")
        (root / ".git" / "config").write_text("private", encoding="utf-8")
        minted = self.client.post(
            "/api/share",
            json={"kind": "folder", "ref": "shared", "level": "view"},
        )
        self.assertEqual(minted.status_code, 200)
        token = minted.json()["token"]

        self.assertEqual(self.client.get(f"/s/{token}/.env").status_code, 404)
        self.assertEqual(self.client.get(f"/s/{token}/.git/config").status_code, 404)

    def test_folder_share_never_follows_a_symlink_into_a_sibling(self):
        files = files_store.files_dir()
        shared = files / "shared"
        private = files / "private"
        shared.mkdir()
        private.mkdir()
        (private / "secret.txt").write_text("not shared", "utf-8")
        try:
            (shared / "link.txt").symlink_to(private / "secret.txt")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        minted = self.client.post(
            "/api/share",
            json={"kind": "folder", "ref": "shared", "level": "view"},
        )
        self.assertEqual(minted.status_code, 200)
        token = minted.json()["token"]

        self.assertEqual(self.client.get(f"/s/{token}").status_code, 404)
        child = self.client.get(f"/s/{token}/link.txt")
        self.assertEqual(child.status_code, 404)
        self.assertNotIn("not shared", child.text)

    def test_view_photo_image(self):
        (photos_store.photos_dir() / "p.png").write_bytes(_PNG)
        d = self.db()
        ph = Photo(filename="p.png", original_name="p.png")
        d.add(ph)
        d.commit()
        pid = ph.id
        d.close()
        tok = self.client.post("/api/share", json={"kind": "photo", "ref": pid}).json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("image/"))
        self.assertEqual(r.content, _PNG)

    def test_view_unknown_404(self):
        self.assertEqual(self.client.get("/s/nope-not-a-token").status_code, 404)

    def test_view_revoked_404(self):
        tok = self.client.post("/api/share", json={"kind": "doc", "ref": "rev.md"}).json()["token"]
        vault_md.write("rev.md", "# x")
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 200)
        self.client.request("DELETE", "/api/share", json={"kind": "doc", "ref": "rev.md"})
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_session_fallback_still_works(self):
        d = self.db()
        s = Session(name="legacy chat", model="aide")
        d.add(s)
        d.commit()
        d.add(Message(session_id=s.id, role="user", content="legacy hello"))
        d.commit()
        sid = s.id
        d.close()
        tok = self.client.post(f"/api/sessions/{sid}/share").json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("legacy hello", r.text)
