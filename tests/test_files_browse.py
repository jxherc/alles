import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from services import files_store as fstore
from tests._client import ApiTest


class FilesBrowseTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _w(self, rel, body, mtime=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    # ---- duplicates ----
    def test_dup_groups_identical(self):
        self._w("a.txt", "same content here")
        self._w("sub/b.txt", "same content here")
        self._w("c.txt", "unrelated")
        groups = self.client.get("/api/files/duplicates").json()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(groups[0]["paths"]), ["a.txt", "sub/b.txt"])

    def test_dup_group_carries_size(self):
        body = "x" * 42
        self._w("a.txt", body)
        self._w("b.txt", body)
        g = self.client.get("/api/files/duplicates").json()["groups"][0]
        self.assertEqual(g["size"], 42)

    def test_dup_ignores_singletons(self):
        self._w("a.txt", "one")
        self._w("b.txt", "two")
        self._w("c.txt", "three")
        self.assertEqual(self.client.get("/api/files/duplicates").json()["groups"], [])

    def test_dup_ignores_empty(self):
        # two empty files have identical (empty) content but must NOT be flagged
        self._w("e1.txt", "")
        self._w("e2.txt", "")
        self.assertEqual(self.client.get("/api/files/duplicates").json()["groups"], [])

    def test_dup_sorted_by_group_size(self):
        # a 3-file group should sort before a 2-file group
        for n in ("a", "b", "c"):
            self._w(f"{n}.txt", "trio")
        self._w("d.txt", "duo")
        self._w("e.txt", "duo")
        groups = self.client.get("/api/files/duplicates").json()["groups"]
        self.assertEqual([len(g["paths"]) for g in groups], [3, 2])

    # ---- preview ----
    def test_preview_docx_text(self):
        from docx import Document

        doc = Document()
        doc.add_paragraph("Hello from a docx")
        doc.add_paragraph("second paragraph")
        doc.save(str(self.root / "report.docx"))
        d = self.client.get("/api/files/preview?path=report.docx").json()
        self.assertEqual(d["kind"], "docx")
        self.assertIn("Hello from a docx", d["text"])
        self.assertIn("second paragraph", d["text"])

    def test_preview_txt(self):
        self._w("notes.txt", "plain text body")
        d = self.client.get("/api/files/preview?path=notes.txt").json()
        self.assertEqual(d["kind"], "text")
        self.assertEqual(d["text"], "plain text body")

    def test_preview_unsupported(self):
        self._w("blob.bin", b"\x00\x01\x02")
        self.assertEqual(
            self.client.get("/api/files/preview?path=blob.bin").json()["kind"], "unsupported"
        )

    def test_preview_missing_404(self):
        r = self.client.get("/api/files/preview?path=nope.txt")
        self.assertEqual(r.status_code, 404)

    def test_preview_xlsx_graceful(self):
        # openpyxl isn't installed in this env — must degrade gracefully, not crash
        self._w("sheet.xlsx", b"not really xlsx")
        d = self.client.get("/api/files/preview?path=sheet.xlsx").json()
        self.assertEqual(d["kind"], "xlsx")
        self.assertIn("error", d)

    # ---- activity ----
    def test_activity_recent_first(self):
        now = time.time()
        self._w("old.txt", "o", mtime=now - 5 * 86400)
        self._w("new.txt", "n", mtime=now - 1 * 86400)
        items = self.client.get("/api/files/activity").json()["items"]
        self.assertEqual([i["path"] for i in items], ["new.txt", "old.txt"])

    def test_activity_excludes_old(self):
        now = time.time()
        self._w("recent.txt", "r", mtime=now - 2 * 86400)
        self._w("ancient.txt", "a", mtime=now - 90 * 86400)
        items = self.client.get("/api/files/activity?days=30").json()["items"]
        self.assertEqual([i["path"] for i in items], ["recent.txt"])

    def test_activity_limit(self):
        now = time.time()
        for i in range(5):
            self._w(f"f{i}.txt", str(i), mtime=now - i * 3600)
        items = self.client.get("/api/files/activity?limit=2").json()["items"]
        self.assertEqual(len(items), 2)
