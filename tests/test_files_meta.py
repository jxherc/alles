"""audit fixes: renaming a file must carry its tags/star (not orphan them) and reject a
collision with a clean 400 (not crash); deleting must clear its tag metadata."""

import tempfile
from pathlib import Path
from unittest import mock

from sqlalchemy import event

import services.files_store as fstore
from core.database import FileComment, FileTag, FileVersion
from tests._client import ApiTest


class FilesMetaTests(ApiTest):
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

    def _w(self, rel, body="x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

    def _starred(self):
        r = self.client.get("/api/files/starred").json()
        rows = r if isinstance(r, list) else r.get("items", [])
        return [x["path"] for x in rows]

    def _capture_sql(self, fn):
        sql = []

        def before_cursor_execute(_conn, _cursor, statement, _params, _ctx, _many):
            sql.append(" ".join(statement.lower().split()))

        event.listen(self.eng, "before_cursor_execute", before_cursor_execute)
        try:
            res = fn()
        finally:
            event.remove(self.eng, "before_cursor_execute", before_cursor_execute)
        return res, sql

    def _assert_no_full_scan(self, sql, tables):
        for table in tables:
            bad = [s for s in sql if f" from {table}" in s and " where " not in s]
            self.assertEqual(bad, [], f"full scan on {table}: {bad[:1]}")

    def test_rename_carries_tags_and_star(self):
        self._w("a.txt")
        self.client.put("/api/files/star?path=a.txt", json={"starred": True})
        self.client.put("/api/files/tags?path=a.txt", json={"tags": ["work"]})
        r = self.client.post("/api/files/rename", json={"path": "a.txt", "to": "c.txt"})
        self.assertEqual(r.status_code, 200)
        starred = self._starred()
        self.assertIn("c.txt", starred)
        self.assertNotIn("a.txt", starred)

    def test_rename_onto_existing_is_400(self):
        self._w("a.txt")
        self._w("b.txt")
        r = self.client.post("/api/files/rename", json={"path": "a.txt", "to": "b.txt"})
        self.assertEqual(r.status_code, 400)

    def test_empty_tags_creates_no_row(self):
        from core.database import FileTag

        self._w("a.txt")
        self.client.put("/api/files/tags?path=a.txt", json={"tags": [], "color": ""})
        db = self.db()
        self.assertEqual(db.query(FileTag).filter_by(path="a.txt").count(), 0)
        db.close()

    def test_delete_clears_tag_metadata(self):
        self._w("a.txt")
        self.client.put("/api/files/star?path=a.txt", json={"starred": True})
        self.client.delete("/api/files/delete?path=a.txt")
        self.assertNotIn("a.txt", self._starred())

    def test_rename_metadata_queries_are_path_scoped(self):
        self._w("docs/a.txt")
        d = self.db()
        d.add_all(
            [
                FileTag(path="docs/a.txt", tags="work", starred=True),
                FileTag(path="other.txt", tags="keep"),
                FileComment(path="docs/a.txt", body="move"),
                FileComment(path="other.txt", body="keep"),
                FileVersion(path="docs/a.txt", sha="1", size=1, stored="blob-a"),
                FileVersion(path="other.txt", sha="2", size=1, stored="blob-b"),
            ]
        )
        d.commit()
        d.close()

        res, sql = self._capture_sql(
            lambda: self.client.post("/api/files/rename", json={"path": "docs", "to": "archive"})
        )

        self.assertEqual(res.status_code, 200)
        self._assert_no_full_scan(sql, ("file_tags", "file_comments", "file_versions"))
        d = self.db()
        self.assertEqual(d.query(FileTag).filter_by(path="archive/a.txt").count(), 1)
        self.assertEqual(d.query(FileTag).filter_by(path="other.txt").count(), 1)
        d.close()

    def test_delete_metadata_queries_are_path_scoped(self):
        self._w("docs/a.txt")
        d = self.db()
        d.add_all(
            [
                FileTag(path="docs/a.txt", tags="work", starred=True),
                FileTag(path="other.txt", tags="keep"),
                FileComment(path="docs/a.txt", body="drop"),
                FileComment(path="other.txt", body="keep"),
            ]
        )
        d.commit()
        d.close()

        res, sql = self._capture_sql(
            lambda: self.client.request("DELETE", "/api/files/delete", params={"path": "docs"})
        )

        self.assertEqual(res.status_code, 200)
        self._assert_no_full_scan(sql, ("file_tags", "file_comments"))
        d = self.db()
        self.assertEqual(d.query(FileTag).filter_by(path="docs/a.txt").count(), 0)
        self.assertEqual(d.query(FileTag).filter_by(path="other.txt").count(), 1)
        d.close()
