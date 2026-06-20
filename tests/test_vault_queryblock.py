import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from services import vault_md
from tests._client import ApiTest


class QuerySpecTests(ApiTest):
    def test_parse_tag_filter(self):
        s = vault_md.parse_query_spec("tag: project")
        self.assertEqual(s["filters"], [{"field": "tag", "op": "eq", "value": "project"}])

    def test_parse_sort_dir(self):
        s = vault_md.parse_query_spec("sort: modified desc")
        self.assertEqual(s["sort"], {"field": "modified", "dir": "desc"})

    def test_parse_limit(self):
        self.assertEqual(vault_md.parse_query_spec("limit: 5")["limit"], 5)

    def test_parse_group(self):
        self.assertEqual(vault_md.parse_query_spec("group: status")["group"], "status")

    def test_parse_property_filter(self):
        s = vault_md.parse_query_spec("status: open")
        self.assertEqual(s["filters"], [{"field": "status", "op": "eq", "value": "open"}])

    def test_parse_ignores_blank_and_comments(self):
        s = vault_md.parse_query_spec("\n# a comment\nlimit: 3\n")
        self.assertEqual(s["limit"], 3)
        self.assertEqual(s["filters"], [])


class QueryBlockApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        vault_md.write("a.md", "---\nstatus: open\n---\ntask a #project")
        vault_md.write("b.md", "---\nstatus: done\n---\ntask b #project")
        vault_md.write("c.md", "---\nstatus: open\n---\nunrelated note")

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_query_block_filters_by_tag(self):
        d = self.client.post("/api/vault-md/query-block", json={"spec": "tag: project"}).json()
        names = {r["name"] for r in d["rows"]}
        self.assertEqual(names, {"a", "b"})

    def test_query_block_property_filter(self):
        d = self.client.post("/api/vault-md/query-block", json={"spec": "status: open"}).json()
        names = {r["name"] for r in d["rows"]}
        self.assertEqual(names, {"a", "c"})

    def test_query_block_grouping(self):
        d = self.client.post(
            "/api/vault-md/query-block", json={"spec": "tag: project\ngroup: status"}
        ).json()
        groups = {g["key"]: {r["name"] for r in g["rows"]} for g in d["groups"]}
        self.assertEqual(groups.get("open"), {"a"})
        self.assertEqual(groups.get("done"), {"b"})

    def test_query_block_limit(self):
        d = self.client.post("/api/vault-md/query-block", json={"spec": "limit: 1"}).json()
        self.assertEqual(len(d["rows"]), 1)


class SavedViewTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.sf.write(b"{}")
        self.sf.close()
        self._p = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self.sf.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        Path(self.sf.name).unlink(missing_ok=True)
        super().tearDown()

    def test_save_and_list_view(self):
        self.client.post("/api/vault-md/views", json={"name": "open tasks", "spec": "status: open"})
        views = self.client.get("/api/vault-md/views").json()["views"]
        self.assertEqual(views[0]["name"], "open tasks")

    def test_save_view_upsert(self):
        self.client.post("/api/vault-md/views", json={"name": "v", "spec": "a: 1"})
        self.client.post("/api/vault-md/views", json={"name": "v", "spec": "a: 2"})
        views = self.client.get("/api/vault-md/views").json()["views"]
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]["spec"], "a: 2")

    def test_save_view_requires_name(self):
        r = self.client.post("/api/vault-md/views", json={"name": "", "spec": "x"})
        self.assertEqual(r.status_code, 400)

    def test_delete_view(self):
        self.client.post("/api/vault-md/views", json={"name": "gone", "spec": "x"})
        self.client.request("DELETE", "/api/vault-md/views", params={"name": "gone"})
        self.assertEqual(self.client.get("/api/vault-md/views").json()["views"], [])
