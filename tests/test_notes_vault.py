import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        n = nv.create(
            title="grocery list",
            content="milk eggs",
            tags=["home"],
            items=[{"text": "buy milk", "done": False}],
            due="2026-07-01",
        )
        got = nv.get(n["id"])
        self.assertEqual(got["title"], "grocery list")
        self.assertEqual(got["content"], "milk eggs")
        self.assertEqual(got["tags"], ["home"])
        self.assertEqual(got["items"], [{"text": "buy milk", "done": False}])
        self.assertEqual(got["due"], "2026-07-01")
        self.assertFalse(got["pinned"])
        self.assertFalse(got["archived"])

    def test_real_file_on_disk(self):
        nv.create(
            title="hello",
            content="body text",
            pinned=True,
            tags=["a", "b"],
            items=[{"text": "do x", "done": True}],
        )
        p = self.tmp / "Notes" / "hello.md"
        self.assertTrue(p.is_file())
        raw = p.read_text("utf-8")
        self.assertIn("pinned: true", raw)
        self.assertIn('tags: ["a", "b"]', raw)
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

    def test_metadata_patch_preserves_unknown_frontmatter_body_and_crlf(self):
        path = self.tmp / "Notes" / "obsidian.md"
        path.parent.mkdir(parents=True)
        raw = (
            "---\r\n"
            "aliases:\r\n"
            "  - keep this exactly\r\n"
            "custom-key: future syntax # comment\r\n"
            "pinned: false\r\n"
            "---\r\n"
            "# heading\r\n\r\n"
            "> [!note] untouched\r\n"
            "- [ ] trailing task\r\n"
        )
        path.write_bytes(raw.encode("utf-8"))

        updated = nv.update("obsidian", {"pinned": True})

        self.assertTrue(updated["pinned"])
        self.assertEqual(
            path.read_bytes(), raw.replace("pinned: false", "pinned: true").encode("utf-8")
        )

    def test_metadata_patch_delimits_dotted_and_unicode_top_level_keys(self):
        path = self.tmp / "Notes" / "custom-keys.md"
        path.parent.mkdir(parents=True)
        raw = (
            "---\n"
            "due: 2026-07-30\n"
            "custom.property: keep dotted key\n"
            "标签: 保留\n"
            "pinned: false\n"
            "---\n"
            "body\n"
        )
        path.write_text(raw, "utf-8")

        nv.update("custom-keys", {"due": "2026-08-01"})

        self.assertEqual(
            path.read_text("utf-8"),
            raw.replace("due: 2026-07-30", "due: 2026-08-01"),
        )

    def test_metadata_patch_keeps_utf8_bom_at_the_start(self):
        path = self.tmp / "Notes" / "bom.md"
        path.parent.mkdir(parents=True)
        raw = "\ufeff# heading\r\n\r\nbody\r\n"
        path.write_bytes(raw.encode("utf-8"))

        nv.update("bom", {"pinned": True})

        updated = path.read_bytes()
        self.assertTrue(updated.startswith(b"\xef\xbb\xbf---\r\n"))
        self.assertEqual(updated.count(b"\xef\xbb\xbf"), 1)
        self.assertNotIn(b"---\r\n\xef\xbb\xbf", updated)

    def test_clearing_the_only_frontmatter_key_removes_the_empty_block(self):
        path = self.tmp / "Notes" / "only-managed-key.md"
        path.parent.mkdir(parents=True)
        path.write_text("\ufeff---\r\npinned: true\r\n---\r\nbody\r\n", "utf-8")

        nv.update("only-managed-key", {"pinned": False})

        self.assertEqual(path.read_bytes(), "\ufeffbody\r\n".encode("utf-8"))
        nv.update("only-managed-key", {"tags": ["later"]})
        self.assertEqual(
            path.read_bytes(),
            '\ufeff---\r\ntags: ["later"]\r\n---\r\nbody\r\n'.encode("utf-8"),
        )

    def test_horizontal_rules_are_not_misclassified_as_frontmatter(self):
        path = self.tmp / "Notes" / "horizontal.md"
        path.parent.mkdir(parents=True)
        raw = "---\nfirst section\n---\nsecond section\n"
        path.write_text(raw, "utf-8")

        updated = nv.update("horizontal", {"pinned": True})

        self.assertTrue(updated["pinned"])
        self.assertEqual(path.read_text("utf-8"), "---\npinned: true\n---\n" + raw)
        self.assertEqual(updated["content"], raw.rstrip())

    def test_indented_yaml_scalar_dashes_do_not_close_frontmatter(self):
        path = self.tmp / "Notes" / "scalar.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "---\ndescription: |\n  ---\npinned: false\n---\nbody\n"
        path.write_text(raw, "utf-8")
        nv.update("scalar", {"pinned": True})
        self.assertEqual(path.read_text("utf-8"), raw.replace("pinned: false", "pinned: true"))

    def test_complex_managed_yaml_is_rejected_without_changing_the_note(self):
        path = self.tmp / "Notes" / "complex-due.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "---\ndue: >-\n  2026-07-30\ncustom: keep\n---\nbody\n"
        path.write_text(raw, "utf-8")

        with self.assertRaisesRegex(vault_md.DocumentConflictError, "complex 'due'"):
            nv.update("complex-due", {"due": "2026-08-01"})

        self.assertEqual(path.read_text("utf-8"), raw)

    def test_blank_and_comment_separators_do_not_make_scalar_metadata_complex(self):
        path = self.tmp / "Notes" / "separators.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = '---\ntags: ["old"]\n\n# keep this comment\ncustom: keep\n---\nbody\n'
        path.write_text(raw, "utf-8")

        nv.update("separators", {"tags": ["new"]})

        self.assertEqual(
            path.read_text("utf-8"),
            raw.replace('tags: ["old"]', 'tags: ["new"]'),
        )

    def test_comment_only_frontmatter_stays_frontmatter_when_metadata_is_added(self):
        path = self.tmp / "Notes" / "comments.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "---\n# owner comment\n---\nbody\n"
        path.write_text(raw, "utf-8")

        nv.update("comments", {"pinned": True})

        self.assertEqual(
            path.read_text("utf-8"),
            "---\n# owner comment\npinned: true\n---\nbody\n",
        )

    def test_quoted_managed_key_is_replaced_without_adding_a_duplicate(self):
        path = self.tmp / "Notes" / "quoted.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "---\n\"tags\": [old]\n'due': 2026-07-30\ncustom: keep\n---\nbody\n"
        path.write_text(raw, "utf-8")

        nv.update("quoted", {"tags": ["new"], "due": "2026-08-01"})

        updated = path.read_text("utf-8")
        self.assertEqual(updated.count("tags:"), 1)
        self.assertEqual(updated.count("due:"), 1)
        self.assertEqual(
            updated,
            '---\ntags: ["new"]\ndue: 2026-08-01\ncustom: keep\n---\nbody\n',
        )

    def test_title_only_rename_preserves_the_note_bytes(self):
        old = self.tmp / "Notes" / "old name.md"
        old.parent.mkdir(parents=True)
        raw = b"---\ncustom: keep\n---\n# exact\n\n<!-- unknown -->\n"
        old.write_bytes(raw)

        updated = nv.update("old name", {"title": "new name"})

        self.assertEqual(updated["id"], "new name")
        self.assertFalse(old.exists())
        self.assertEqual((self.tmp / "Notes" / "new name.md").read_bytes(), raw)

    def test_title_only_rename_rechecks_the_source_hash(self):
        old = self.tmp / "Notes" / "raced.md"
        old.parent.mkdir(parents=True)
        old.write_text("owner version", "utf-8")
        original_rename = vault_md.rename

        def race(rel, new_rel, expected_hash=None):
            old.write_text("external version", "utf-8")
            return original_rename(rel, new_rel, expected_hash=expected_hash)

        with mock.patch.object(vault_md, "rename", side_effect=race):
            with self.assertRaises(vault_md.DocumentConflictError):
                nv.update("raced", {"title": "renamed"})

        self.assertEqual(old.read_text("utf-8"), "external version")
        self.assertFalse((self.tmp / "Notes" / "renamed.md").exists())

    def test_content_patch_keeps_unknown_frontmatter_and_trailing_items(self):
        path = self.tmp / "Notes" / "mixed.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "---\ncustom: keep exactly\ntags: [old]\n---\nold body\n\n- [x] keep task",
            "utf-8",
        )

        nv.update("mixed", {"content": "new body with [[link]]"})

        self.assertEqual(
            path.read_text("utf-8"),
            "---\ncustom: keep exactly\ntags: [old]\n---\nnew body with [[link]]\n\n- [x] keep task",
        )

    def test_stale_noop_update_still_fails_closed(self):
        nid = nv.create(title="stale", content="keep")["id"]
        path = self.tmp / "Notes" / "stale.md"
        before = path.read_bytes()

        with self.assertRaises(vault_md.DocumentConflictError):
            nv.update(nid, {"pinned": False}, expected_hash="stale-hash")

        self.assertEqual(path.read_bytes(), before)

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

    def test_tag_yaml_punctuation_roundtrips_without_splitting_or_comments(self):
        nid = nv.create(title="punctuation", tags=["old"])["id"]
        tags = ["alpha,beta", "hash # tag", 'quote " tag', "[bracket]", "台北"]

        updated = nv.update(nid, {"tags": tags})

        self.assertEqual(updated["tags"], tags)
        self.assertEqual(nv.get(nid)["tags"], tags)
        raw = (self.tmp / "Notes" / "punctuation.md").read_text("utf-8")
        self.assertIn(
            'tags: ["alpha,beta", "hash # tag", "quote \\" tag", "[bracket]", "台北"]',
            raw,
        )

    # ── search / filter / counts ──────────────────────────────────────────────
    def test_search_title_content_tags(self):
        nv.create(title="grocery list", content="milk eggs", tags=["home"])
        nv.create(title="work plan", content="ship the thing", tags=["office"])

        def titles(q):
            return sorted(r["title"] for r in nv.list_notes(q=q))

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
        n = nv.create(
            title="todo",
            items=[
                {"text": "buy milk", "done": False},
                {"text": "  ", "done": True},  # blank -> dropped
                {"text": "call mom", "done": True},
                {"bogus": 1},  # malformed -> dropped
            ],
        )
        self.assertEqual(
            nv.get(n["id"])["items"],
            [
                {"text": "buy milk", "done": False},
                {"text": "call mom", "done": True},
            ],
        )

    def test_toggle_item_via_update(self):
        nid = nv.create(title="t", items=[{"text": "a", "done": False}])["id"]
        n = nv.update(nid, {"items": [{"text": "a", "done": True}]})
        self.assertTrue(n["items"][0]["done"])

    def test_checklist_only_patch_preserves_existing_separator_bytes(self):
        nid = nv.create(title="spacing", content="body", items=[{"text": "a", "done": False}])["id"]
        path = self.tmp / "Notes" / f"{nid}.md"
        raw = path.read_text("utf-8")
        item = raw.index("- [ ] a")
        raw = raw[:item].rstrip("\n") + "\n\n\n" + raw[item:]
        path.write_text(raw, "utf-8")
        nv.update(nid, {"items": [{"text": "a", "done": True}]})
        self.assertIn("body\n\n\n- [x] a", path.read_text("utf-8"))

    def test_content_and_items_separate(self):
        n = nv.create(
            title="mix", content="some notes here", items=[{"text": "step 1", "done": False}]
        )
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
