import shutil
import tempfile
import unittest
from pathlib import Path

from services import notes_vault as nv
from services import vault_md


class NotesVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = vault_md.vault_dir
        vault_md.vault_dir = lambda: self.tmp  # everything resolves through this

    def tearDown(self):
        vault_md.vault_dir = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── round-trip ────────────────────────────────────────────────────────────
    def test_create_read_roundtrip(self):
        n = nv.create(title="grocery list", content="milk eggs",
                      tags=["home"], items=[{"text": "buy milk", "done": False}], due="2026-07-01")
        got = nv.get(n["id"])
        self.assertEqual(got["title"], "grocery list")
        self.assertEqual(got["content"], "milk eggs")
        self.assertEqual(got["tags"], ["home"])
        self.assertEqual(got["items"], [{"text": "buy milk", "done": False}])
        self.assertEqual(got["due"], "2026-07-01")
        self.assertFalse(got["pinned"])
        self.assertFalse(got["archived"])

    def test_real_file_on_disk(self):
        n = nv.create(title="hello", content="body text",
                      pinned=True, tags=["a", "b"], items=[{"text": "do x", "done": True}])
        p = self.tmp / "Notes" / "hello.md"
        self.assertTrue(p.is_file())
        raw = p.read_text("utf-8")
        self.assertIn("pinned: true", raw)
        self.assertIn("tags: [a, b]", raw)
        self.assertIn("- [x] do x", raw)
        self.assertIn("body text", raw)

    # ── partial update never nulls untouched fields (pin toggle regression) ────
    def test_pin_toggle_preserves_title_and_content(self):
        nid = nv.create(title="keep me", content="important body")["id"]
        pinned = nv.update(nid, {"pinned": True})
        self.assertEqual(pinned["title"], "keep me")
        self.assertEqual(pinned["content"], "important body")
        self.assertTrue(pinned["pinned"])
        unp = nv.update(nid, {"pinned": False})
        self.assertEqual(unp["content"], "important body")
        self.assertFalse(unp["pinned"])
        cleared = nv.update(nid, {"content": ""})  # explicit empty must stick
        self.assertEqual(cleared["content"], "")

    # ── tags ──────────────────────────────────────────────────────────────────
    def test_tags_normalized(self):
        n = nv.create(title="t", content="c", tags=["Work", "work", " Urgent "])
        self.assertEqual(n["tags"], ["work", "urgent"])

    def test_tags_accept_comma_string(self):
        n = nv.create(title="t2", tags="a, b ,a")
        self.assertEqual(n["tags"], ["a", "b"])

    def test_update_tags(self):
        nid = nv.create(title="tt", tags=["old"])["id"]
        n = nv.update(nid, {"tags": ["new", "shiny"]})
        self.assertEqual(n["tags"], ["new", "shiny"])

    # ── search / filter / counts ──────────────────────────────────────────────
    def test_search_title_content_tags(self):
        nv.create(title="grocery list", content="milk eggs", tags=["home"])
        nv.create(title="work plan", content="ship the thing", tags=["office"])
        titles = lambda q: sorted(r["title"] for r in nv.list_notes(q=q))
        self.assertEqual(titles("milk"), ["grocery list"])
        self.assertEqual(titles("office"), ["work plan"])
        self.assertEqual(titles("plan"), ["work plan"])

    def test_filter_by_tag(self):
        nv.create(title="a", tags=["x"])
        nv.create(title="b", tags=["y"])
        self.assertEqual([r["title"] for r in nv.list_notes(tag="x")], ["a"])

    def test_tag_counts(self):
        nv.create(title="a", tags=["x", "y"])
        nv.create(title="b", tags=["x"])
        self.assertEqual({t["tag"]: t["count"] for t in nv.tag_counts()}, {"x": 2, "y": 1})

    # ── archive ───────────────────────────────────────────────────────────────
    def test_archive_hides_and_excluded_from_tagcloud(self):
        nid = nv.create(title="bye", tags=["z"])["id"]
        nv.set_archived(nid, True)
        self.assertEqual(nv.list_notes(), [])
        self.assertEqual([r["title"] for r in nv.list_notes(archived=True)], ["bye"])
        self.assertEqual(nv.tag_counts(), [])  # archived tag not counted
        nv.set_archived(nid, False)
        self.assertEqual([r["title"] for r in nv.list_notes()], ["bye"])

    # ── checklist ─────────────────────────────────────────────────────────────
    def test_checklist_roundtrip_and_clean(self):
        n = nv.create(title="todo", items=[
            {"text": "buy milk", "done": False},
            {"text": "  ", "done": True},      # blank -> dropped
            {"text": "call mom", "done": True},
            {"bogus": 1},                       # malformed -> dropped
        ])
        self.assertEqual(nv.get(n["id"])["items"], [
            {"text": "buy milk", "done": False},
            {"text": "call mom", "done": True},
        ])

    def test_toggle_item_via_update(self):
        nid = nv.create(title="t", items=[{"text": "a", "done": False}])["id"]
        n = nv.update(nid, {"items": [{"text": "a", "done": True}]})
        self.assertTrue(n["items"][0]["done"])

    def test_content_and_items_separate(self):
        n = nv.create(title="mix", content="some notes here",
                      items=[{"text": "step 1", "done": False}])
        got = nv.get(n["id"])
        self.assertEqual(got["content"], "some notes here")
        self.assertEqual(got["items"], [{"text": "step 1", "done": False}])

    # ── due ───────────────────────────────────────────────────────────────────
    def test_due_stored_and_cleared(self):
        nid = nv.create(title="deadline", due="2026-07-01")["id"]
        self.assertEqual(nv.get(nid)["due"], "2026-07-01")
        self.assertEqual(nv.update(nid, {"due": ""})["due"], "")

    # ── retitle renames the file + fixes backlinks ────────────────────────────
    def test_retitle_renames_file_and_rewrites_links(self):
        a = nv.create(title="alpha", content="hi")["id"]
        nv.create(title="beta", content="see [[alpha]]")
        renamed = nv.update(a, {"title": "gamma"})
        self.assertEqual(renamed["id"], "gamma")
        self.assertFalse((self.tmp / "Notes" / "alpha.md").exists())
        self.assertTrue((self.tmp / "Notes" / "gamma.md").exists())
        beta = nv.get("beta")
        self.assertIn("[[gamma]]", beta["content"])

    def test_duplicate_title_gets_unique_name(self):
        a = nv.create(title="dupe")["id"]
        b = nv.create(title="dupe")["id"]
        self.assertNotEqual(a, b)
        self.assertEqual(a, "dupe")
        self.assertEqual(b, "dupe 2")

    def test_blank_title_falls_back(self):
        n = nv.create(title="", content="x")
        self.assertEqual(n["id"], "Untitled")

    # ── hand-authored obsidian note (no frontmatter) reads cleanly ────────────
    def test_hand_authored_note_reads(self):
        (self.tmp / "Notes").mkdir(parents=True)
        (self.tmp / "Notes" / "manual.md").write_text("# manual\n\njust prose", "utf-8")
        got = nv.get("manual")
        self.assertEqual(got["title"], "manual")
        self.assertIn("just prose", got["content"])
        self.assertEqual(got["tags"], [])
        self.assertEqual(got["items"], [])
        self.assertFalse(got["pinned"])

    def test_get_missing_returns_none(self):
        self.assertIsNone(nv.get("nope"))
        self.assertIsNone(nv.get("../escape"))


if __name__ == "__main__":
    unittest.main()
