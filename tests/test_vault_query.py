import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


def _seed():
    vault_md.write(
        "a.md", "---\nstatus: active\npriority: 3\ntags: [work, urgent]\n---\n#inline body"
    )
    vault_md.write("b.md", "---\nstatus: done\npriority: 1\ntags: [home]\n---\nbody")
    vault_md.write("proj/c.md", "---\nstatus: active\npriority: 5\n---\nno tags here")
    vault_md.write("d.md", "plain note, no frontmatter #misc")


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()
        _seed()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def names(self, rows):
        return sorted(r["name"] for r in rows)

    def test_eq_property(self):
        rows = vault_md.query_notes([{"field": "status", "op": "eq", "value": "active"}])
        self.assertEqual(self.names(rows), ["a", "c"])

    def test_ne_includes_missing(self):
        rows = vault_md.query_notes([{"field": "status", "op": "ne", "value": "done"}])
        self.assertEqual(self.names(rows), ["a", "c", "d"])

    def test_tag_filter(self):
        rows = vault_md.query_notes([{"field": "tag", "op": "eq", "value": "work"}])
        self.assertEqual(self.names(rows), ["a"])

    def test_inline_tag_counts(self):
        rows = vault_md.query_notes([{"field": "tag", "op": "eq", "value": "misc"}])
        self.assertEqual(self.names(rows), ["d"])

    def test_folder_filter(self):
        rows = vault_md.query_notes([{"field": "folder", "op": "eq", "value": "proj"}])
        self.assertEqual(self.names(rows), ["c"])

    def test_exists_and_missing(self):
        has = vault_md.query_notes([{"field": "priority", "op": "exists"}])
        self.assertEqual(self.names(has), ["a", "b", "c"])
        miss = vault_md.query_notes([{"field": "status", "op": "missing"}])
        self.assertEqual(self.names(miss), ["d"])

    def test_contains_on_list_prop(self):
        rows = vault_md.query_notes([{"field": "tags", "op": "contains", "value": "urgent"}])
        self.assertEqual(self.names(rows), ["a"])

    def test_numeric_gt(self):
        rows = vault_md.query_notes([{"field": "priority", "op": "gt", "value": "2"}])
        self.assertEqual(self.names(rows), ["a", "c"])

    def test_sort_desc_and_limit(self):
        rows = vault_md.query_notes(
            [{"field": "priority", "op": "exists"}], sort={"field": "priority", "dir": "desc"}
        )
        self.assertEqual([r["name"] for r in rows], ["c", "a", "b"])
        capped = vault_md.query_notes([{"field": "priority", "op": "exists"}], limit=2)
        self.assertEqual(len(capped), 2)

    def test_multiple_filters_and(self):
        rows = vault_md.query_notes(
            [
                {"field": "status", "op": "eq", "value": "active"},
                {"field": "priority", "op": "gt", "value": "4"},
            ]
        )
        self.assertEqual(self.names(rows), ["c"])

    def test_row_shape(self):
        rows = vault_md.query_notes([{"field": "name", "op": "eq", "value": "a"}])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["props"]["status"], "active")
        self.assertIn("work", r["tags"])
        self.assertTrue(r["path"].endswith("a.md"))


class QueryApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.vp = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.vp.start()
        _seed()

    def tearDown(self):
        self.vp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_api_query(self):
        r = self.client.post(
            "/api/vault-md/query",
            json={"filters": [{"field": "status", "op": "eq", "value": "active"}]},
        )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["count"], 2)
        self.assertEqual(sorted(x["name"] for x in d["results"]), ["a", "c"])


if __name__ == "__main__":
    unittest.main()
