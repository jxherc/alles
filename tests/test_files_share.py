import tempfile
from pathlib import Path
from unittest import mock

from services import files_store as fstore
from tests._client import ApiTest


class FilesShareTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()
        (self.root / "proj").mkdir()
        (self.root / "proj" / "spec.txt").write_text("the spec")
        (self.root / "proj" / "notes.txt").write_text("some notes")
        (self.root / "proj" / "sub").mkdir()
        (self.root / "proj" / "sub" / "deep.txt").write_text("deep file")
        (self.root / "secret.txt").write_text("top secret")  # sibling, outside proj

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mint(self, kind, ref, level="view"):
        return self.client.post("/api/share", json={"kind": kind, "ref": ref, "level": level})

    # ---- folder share ----
    def test_folder_share_mints_token(self):
        r = self._mint("folder", "proj")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["token"])

    def test_folder_viewer_lists_files(self):
        tok = self._mint("folder", "proj").json()["token"]
        html = self.client.get(f"/s/{tok}").text
        self.assertIn("spec.txt", html)
        self.assertIn("notes.txt", html)
        self.assertIn("sub/deep.txt", html)
        self.assertNotIn("secret.txt", html)  # sibling never exposed

    def test_folder_viewer_serves_child(self):
        tok = self._mint("folder", "proj").json()["token"]
        r = self.client.get(f"/s/{tok}/spec.txt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "the spec")

    def test_folder_serves_nested_child(self):
        tok = self._mint("folder", "proj").json()["token"]
        r = self.client.get(f"/s/{tok}/sub/deep.txt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "deep file")

    def test_folder_child_blocks_traversal(self):
        tok = self._mint("folder", "proj").json()["token"]
        # encoded .. so the client doesn't normalize it away before it reaches routing
        r = self.client.get(f"/s/{tok}/%2e%2e/secret.txt")
        self.assertEqual(r.status_code, 404)

    def test_folder_share_revoke_404(self):
        tok = self._mint("folder", "proj").json()["token"]
        self.client.request("DELETE", "/api/share", json={"kind": "folder", "ref": "proj"})
        self.assertEqual(self.client.get(f"/s/{tok}").status_code, 404)

    def test_file_share_download_disposition(self):
        tok = self._mint("file", "proj/spec.txt", level="download").json()["token"]
        r = self.client.get(f"/s/{tok}")
        self.assertIn("attachment", r.headers.get("content-disposition", ""))

    def test_folder_child_download_disposition(self):
        tok = self._mint("folder", "proj", level="download").json()["token"]
        r = self.client.get(f"/s/{tok}/spec.txt")
        self.assertIn("attachment", r.headers.get("content-disposition", ""))

    # ---- file comments ----
    def _add(self, path="proj/spec.txt", body="hi", parent_id=None):
        payload = {"path": path, "body": body}
        if parent_id:
            payload["parent_id"] = parent_id
        return self.client.post("/api/files/comments", json=payload)

    def test_comment_add_and_list(self):
        self._add(body="first comment")
        threads = self.client.get("/api/files/comments?path=proj/spec.txt").json()["threads"]
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["body"], "first comment")

    def test_comment_reply_threads(self):
        root = self._add(body="root").json()
        self._add(body="a reply", parent_id=root["id"])
        threads = self.client.get("/api/files/comments?path=proj/spec.txt").json()["threads"]
        self.assertEqual(len(threads), 1)
        self.assertEqual(len(threads[0]["replies"]), 1)
        self.assertEqual(threads[0]["replies"][0]["body"], "a reply")

    def test_comment_resolve_toggles(self):
        root = self._add().json()
        r1 = self.client.post(f"/api/files/comments/{root['id']}/resolve").json()
        self.assertTrue(r1["resolved"])
        r2 = self.client.post(f"/api/files/comments/{root['id']}/resolve").json()
        self.assertFalse(r2["resolved"])

    def test_comment_delete_removes_replies(self):
        root = self._add(body="root").json()
        self._add(body="reply", parent_id=root["id"])
        self.client.delete(f"/api/files/comments/{root['id']}")
        threads = self.client.get("/api/files/comments?path=proj/spec.txt").json()["threads"]
        self.assertEqual(threads, [])

    def test_comment_empty_body_400(self):
        r = self.client.post("/api/files/comments", json={"path": "proj/spec.txt", "body": "   "})
        self.assertEqual(r.status_code, 400)

    def test_comment_path_required_400(self):
        r = self.client.post("/api/files/comments", json={"body": "orphan"})
        self.assertEqual(r.status_code, 400)

    def test_listing_carries_comment_count(self):
        self._add(path="proj/spec.txt", body="one")
        self._add(path="proj/spec.txt", body="two")
        items = self.client.get("/api/files/list?path=proj").json()["items"]
        spec = next(i for i in items if i["path"] == "proj/spec.txt")
        self.assertEqual(spec["comments"], 2)
