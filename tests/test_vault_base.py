import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class BaseViewTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        vault_md.write("projects/alpha.md", "---\nstatus: active\nowner: me\n---\nAlpha project")
        vault_md.write("projects/beta.md", "---\nstatus: done\n---\nBeta project")
        vault_md.write("tasks/t1.md", "---\nproject: Alpha\nhours: 3\n---\ntask 1")
        vault_md.write("tasks/t2.md", "---\nproject: Alpha\nhours: 5\n---\ntask 2")
        vault_md.write("tasks/t3.md", "---\nproject: Beta\nhours: 2\n---\ntask 3")

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_base_view_rows_in_folder(self):
        d = self.client.get("/api/vault-md/base", params={"folder": "projects"}).json()
        self.assertEqual({r["name"] for r in d["rows"]}, {"alpha", "beta"})

    def test_base_view_columns_union(self):
        d = self.client.get("/api/vault-md/base", params={"folder": "projects"}).json()
        self.assertIn("status", d["columns"])
        self.assertIn("owner", d["columns"])

    def test_base_view_excludes_other_folders(self):
        d = self.client.get("/api/vault-md/base", params={"folder": "projects"}).json()
        self.assertFalse(any(r["name"].startswith("t") for r in d["rows"]))

    def test_base_view_sort(self):
        d = self.client.get(
            "/api/vault-md/base",
            params={"folder": "projects", "sort_field": "name", "sort_dir": "desc"},
        ).json()
        self.assertEqual([r["name"] for r in d["rows"]], ["beta", "alpha"])

    def test_base_cell_edit_writes_frontmatter(self):
        r = self.client.post(
            "/api/vault-md/base-cell",
            json={"path": "projects/alpha.md", "key": "status", "value": "paused"},
        ).json()
        self.assertEqual(r["properties"]["status"], "paused")
        # persisted
        props, _ = vault_md.parse_frontmatter(vault_md.read("projects/alpha.md")["content"])
        self.assertEqual(props["status"], "paused")

    def test_base_cell_add_new_key(self):
        self.client.post(
            "/api/vault-md/base-cell",
            json={"path": "projects/beta.md", "key": "owner", "value": "you"},
        )
        props, _ = vault_md.parse_frontmatter(vault_md.read("projects/beta.md")["content"])
        self.assertEqual(props["owner"], "you")

    def test_base_cell_empty_removes_key(self):
        self.client.post(
            "/api/vault-md/base-cell",
            json={"path": "projects/alpha.md", "key": "owner", "value": ""},
        )
        props, _ = vault_md.parse_frontmatter(vault_md.read("projects/alpha.md")["content"])
        self.assertNotIn("owner", props)

    def test_base_cell_preserves_body(self):
        self.client.post(
            "/api/vault-md/base-cell",
            json={"path": "projects/alpha.md", "key": "status", "value": "x"},
        )
        self.assertIn("Alpha project", vault_md.read("projects/alpha.md")["content"])

    def test_rollup_count(self):
        d = self.client.get(
            "/api/vault-md/base-rollup",
            params={"folder": "projects", "relation": "project", "agg": "count"},
        ).json()
        by = {r["name"]: r["value"] for r in d["rows"]}
        self.assertEqual(by["alpha"], 2)
        self.assertEqual(by["beta"], 1)

    def test_rollup_sum(self):
        d = self.client.get(
            "/api/vault-md/base-rollup",
            params={"folder": "projects", "relation": "project", "target": "hours", "agg": "sum"},
        ).json()
        by = {r["name"]: r["value"] for r in d["rows"]}
        self.assertEqual(by["alpha"], 8.0)
        self.assertEqual(by["beta"], 2.0)

    def test_rollup_handles_wikilink_relation(self):
        vault_md.write("tasks/t4.md", "---\nproject: [[Alpha]]\nhours: 1\n---\ntask 4")
        d = self.client.get(
            "/api/vault-md/base-rollup",
            params={"folder": "projects", "relation": "project", "agg": "count"},
        ).json()
        by = {r["name"]: r["value"] for r in d["rows"]}
        self.assertEqual(by["alpha"], 3)
