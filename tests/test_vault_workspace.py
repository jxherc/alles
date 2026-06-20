import tempfile
from pathlib import Path
from unittest import mock

from core.database import AutomationRule, Task
from services import vault_md
from tests._client import ApiTest


class WorkspaceAiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        vault_md.write(
            "notes/python.md",
            "---\ntags: lang\n---\n# Python\nPython is a high-level programming language for scripts.",
        )
        vault_md.write("notes/cooking.md", "# Cooking\nRecipes for pasta and bread. No code here.")

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    # ---- ask ----
    def test_ask_returns_sources(self):
        d = self.client.get("/api/vault-md/ask", params={"q": "programming language"}).json()
        self.assertTrue(d["sources"])
        self.assertEqual(d["sources"][0]["ref"], "notes/python.md")

    def test_ask_empty_q_empty(self):
        d = self.client.get("/api/vault-md/ask", params={"q": ""}).json()
        self.assertEqual(d["sources"], [])

    def test_ask_ranks_relevant_first(self):
        d = self.client.get(
            "/api/vault-md/ask", params={"q": "high level scripting language"}
        ).json()
        refs = [s["ref"] for s in d["sources"]]
        self.assertIn("notes/python.md", refs)
        self.assertEqual(refs[0], "notes/python.md")

    # ---- clip ----
    def test_clip_creates_note(self):
        d = self.client.post(
            "/api/vault-md/clip", json={"title": "Hello World", "content": "body"}
        ).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["path"], "clips/Hello World.md")
        self.assertTrue(vault_md.read("clips/Hello World.md").get("exists"))

    def test_clip_sanitises_title(self):
        d = self.client.post("/api/vault-md/clip", json={"title": "Great Article!?/<>"}).json()
        self.assertNotIn("!", d["path"])
        self.assertNotIn("/", d["path"].replace("clips/", ""))

    def test_clip_includes_source_and_body(self):
        self.client.post(
            "/api/vault-md/clip",
            json={"title": "T", "url": "https://ex.com/a", "content": "the body"},
        )
        txt = vault_md.read("clips/T.md")["content"]
        self.assertIn("https://ex.com/a", txt)
        self.assertIn("the body", txt)

    # ---- bookmarklet ----
    def test_bookmarklet_uses_request_origin(self):
        d = self.client.get("/api/vault-md/clipper-bookmarklet").json()
        self.assertNotIn("YOUR_ALLES_ORIGIN", d["bookmarklet"])
        self.assertIn("testserver", d["bookmarklet"])

    def test_bookmarklet_targets_clip_endpoint(self):
        d = self.client.get("/api/vault-md/clipper-bookmarklet").json()
        self.assertIn("/api/vault-md/clip", d["bookmarklet"])

    # ---- forms ----
    def test_form_submit_creates_table(self):
        d = self.client.post(
            "/api/vault-md/form-submit",
            json={
                "target": "log",
                "fields": ["name", "note"],
                "values": {"name": "a", "note": "hi"},
            },
        ).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["count"], 1)
        txt = vault_md.read("log.md")["content"]
        self.assertIn("| name | note |", txt)
        self.assertIn("| a | hi |", txt)

    def test_form_submit_appends_second_row(self):
        self.client.post(
            "/api/vault-md/form-submit",
            json={"target": "log", "fields": ["name"], "values": {"name": "a"}},
        )
        d = self.client.post(
            "/api/vault-md/form-submit",
            json={"target": "log", "fields": ["name"], "values": {"name": "b"}},
        ).json()
        self.assertEqual(d["count"], 2)
        txt = vault_md.read("log.md")["content"]
        self.assertEqual(txt.count("| name |"), 1)  # one header only
        self.assertIn("| a |", txt)
        self.assertIn("| b |", txt)

    def test_form_submit_preserves_body(self):
        vault_md.write("log.md", "# Submissions\nintro text\n")
        self.client.post(
            "/api/vault-md/form-submit",
            json={"target": "log", "fields": ["x"], "values": {"x": "1"}},
        )
        txt = vault_md.read("log.md")["content"]
        self.assertIn("intro text", txt)
        self.assertIn("| 1 |", txt)

    def test_form_submit_empty_target_400(self):
        r = self.client.post("/api/vault-md/form-submit", json={"target": "", "values": {"a": "1"}})
        self.assertEqual(r.status_code, 400)

    # ---- charts in query blocks ----
    def test_parse_query_spec_chart(self):
        spec = vault_md.parse_query_spec("tag: lang\ngroup: tags\nchart: bar")
        self.assertEqual(spec["chart"], "bar")
        self.assertEqual(spec["group"], "tags")

    def test_query_block_passes_chart_and_group_counts(self):
        vault_md.write("a.md", "---\nkind: x\n---\nbody")
        vault_md.write("b.md", "---\nkind: x\n---\nbody")
        vault_md.write("c.md", "---\nkind: y\n---\nbody")
        out = vault_md.query_block("group: kind\nchart: pie")
        self.assertEqual(out["chart"], "pie")
        counts = {g["key"]: g["count"] for g in out["groups"]}
        self.assertEqual(counts.get("x"), 2)
        self.assertEqual(counts.get("y"), 1)

    # ---- in-doc automation (base-cell edit fires a doc_tag rule) ----
    def test_indoc_automation_base_cell_fires_rule(self):
        vault_md.write("proj/a.md", "# A\nthis is #urgent work")
        db = self.db()
        db.add(
            AutomationRule(
                name="r1",
                trigger="doc_tag",
                trigger_arg="urgent",
                action="create_task",
                action_arg="handle {name}",
                enabled=True,
            )
        )
        db.commit()
        db.close()
        self.client.post(
            "/api/vault-md/base-cell", json={"path": "proj/a.md", "key": "status", "value": "open"}
        )
        db = self.db()
        self.assertEqual(db.query(Task).count(), 1)
        db.close()

    def test_indoc_automation_once_per_doc(self):
        vault_md.write("proj/a.md", "# A\nthis is #urgent work")
        db = self.db()
        db.add(
            AutomationRule(
                name="r1",
                trigger="doc_tag",
                trigger_arg="urgent",
                action="create_task",
                action_arg="handle {name}",
                enabled=True,
            )
        )
        db.commit()
        db.close()
        for _ in range(3):
            self.client.post(
                "/api/vault-md/base-cell",
                json={"path": "proj/a.md", "key": "status", "value": "open"},
            )
        db = self.db()
        self.assertEqual(db.query(Task).count(), 1)
        db.close()
