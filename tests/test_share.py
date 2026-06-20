import tempfile
from pathlib import Path
from unittest import mock

from core.database import Message, Photo, Session
from services import files_store, photos_store, share, vault_md
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

    def test_api_post_bad_kind_400(self):
        r = self.client.post("/api/share", json={"kind": "weird", "ref": "x"})
        self.assertEqual(r.status_code, 400)

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
