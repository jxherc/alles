import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_create_read_write(self):
        vault_md.create("notes/hello")
        r = vault_md.read("notes/hello.md")
        self.assertTrue(r["exists"])
        self.assertIn("# hello", r["content"])
        vault_md.write("notes/hello.md", "updated [[world]]")
        self.assertEqual(vault_md.read("notes/hello.md")["content"], "updated [[world]]")

    def test_tree_nests_and_lists_md_only(self):
        vault_md.create("a.md")
        vault_md.create("sub/b.md")
        vault_md.write("ignore.txt", "x")
        t = vault_md.tree()
        names = {i["name"] for i in t["items"]}
        self.assertIn("a", names)
        self.assertIn("sub", names)
        self.assertNotIn("ignore", names)  # non-md excluded

    def test_rewrite_links_preserves_alias_and_heading(self):
        vault_md.write("a.md", "link to [[old]] here")
        vault_md.write("b.md", "alias [[old|Display]] and heading [[old#sec]]")
        vault_md.write("c.md", "unrelated [[other]]")
        changed = vault_md.rewrite_links("old", "new")
        self.assertEqual(set(changed), {"a.md", "b.md"})
        self.assertIn("[[new]]", vault_md.read("a.md")["content"])
        bc = vault_md.read("b.md")["content"]
        self.assertIn("[[new|Display]]", bc)  # alias kept
        self.assertIn("[[new#sec]]", bc)  # heading kept
        self.assertIn("[[other]]", vault_md.read("c.md")["content"])  # untouched

    def test_rewrite_links_case_insensitive_match(self):
        vault_md.write("a.md", "[[Old Note]] and [[old note]]")
        vault_md.rewrite_links("old note", "Renamed")
        self.assertEqual(vault_md.read("a.md")["content"], "[[Renamed]] and [[Renamed]]")

    def test_rewrite_links_noop_when_same(self):
        vault_md.write("a.md", "[[x]]")
        self.assertEqual(vault_md.rewrite_links("x", "x"), [])
        self.assertEqual(vault_md.rewrite_links("", "y"), [])

    def test_backlinks(self):
        vault_md.write("one.md", "see [[target]] here")
        vault_md.write("two.md", "also [[Target]] and [[other]]")
        vault_md.write("target.md", "i am the target")
        bl = vault_md.backlinks("target")
        names = {b["name"] for b in bl}
        self.assertEqual(names, {"one", "two"})  # case-insensitive, excludes self

    def test_wikilink_with_alias_and_heading(self):
        vault_md.write("x.md", "[[Note|shown text]] and [[Other#section]]")
        self.assertEqual(vault_md.outgoing_links("x.md"), ["Note", "Other"])

    def test_path_traversal_blocked(self):
        with self.assertRaises(ValueError):
            vault_md.read("../../etc/passwd")

    def test_search_ranks_prefix(self):
        vault_md.create("alpha.md")
        vault_md.create("beta-alpha.md")
        res = vault_md.search("alpha")
        self.assertEqual(res[0]["name"], "alpha")  # prefix match ranks first

    def test_full_text_search(self):
        vault_md.write("a.md", "the quick brown fox")
        vault_md.write("b.md", "nothing here")
        res = vault_md.full_text_search("brown")
        self.assertEqual([r["name"] for r in res], ["a"])
        self.assertIn("brown", res[0]["context"])

    def test_tags(self):
        vault_md.write("a.md", "a note #work #urgent")
        vault_md.write("b.md", "another #work item")
        tags = {t["tag"]: t["count"] for t in vault_md.all_tags()}
        self.assertEqual(tags["work"], 2)
        self.assertEqual(tags["urgent"], 1)
        self.assertEqual({n["name"] for n in vault_md.notes_with_tag("work")}, {"a", "b"})

    def test_tasks_rollup_and_toggle(self):
        vault_md.write("a.md", "# a\n- [ ] buy milk\n- [x] done thing\nplain line\n")
        vault_md.write("b.md", "- [ ] write tests")
        tasks = vault_md.all_tasks()
        texts = {(t["name"], t["text"], t["done"]) for t in tasks}
        self.assertIn(("a", "buy milk", False), texts)
        self.assertIn(("a", "done thing", True), texts)
        self.assertIn(("b", "write tests", False), texts)
        # open-only filter
        self.assertTrue(all(not t["done"] for t in vault_md.all_tasks(include_done=False)))
        # toggle the milk line (line index 1) done
        vault_md.set_task("a.md", 1, True)
        self.assertIn("- [x] buy milk", vault_md.read("a.md")["content"])
        with self.assertRaises(ValueError):
            vault_md.set_task("a.md", 3, True)  # "plain line" is not a task

    def test_save_asset_and_sys_dir_excluded(self):
        out = vault_md.save_asset("My Pic!.png", b"\x89PNG\r\n")
        self.assertTrue(out["path"].startswith("_assets/"))
        # dedupe on repeat
        out2 = vault_md.save_asset("My Pic!.png", b"x")
        self.assertNotEqual(out["path"], out2["path"])
        # assets dir must not leak into tree / search
        vault_md.create("real.md")
        names = {i["name"] for i in vault_md.tree()["items"]}
        self.assertNotIn("_assets", names)
        self.assertEqual([r["name"] for r in vault_md.search("My Pic")], [])

    def test_templates_seed(self):
        tmpls = {t["name"] for t in vault_md.list_templates()}
        self.assertTrue({"meeting", "daily", "project"} <= tmpls)
        # templates folder stays out of the notes tree
        self.assertNotIn("_templates", {i["name"] for i in vault_md.tree()["items"]})

    def test_unlinked_mentions(self):
        vault_md.write("target.md", "i am target")
        vault_md.write("linked.md", "see [[target]] here")  # already a link → not unlinked
        vault_md.write("plain.md", "i mention target in prose")  # plain mention → unlinked
        ment = {m["name"] for m in vault_md.unlinked_mentions("target")}
        self.assertIn("plain", ment)
        self.assertNotIn("linked", ment)
        self.assertNotIn("target", ment)  # excludes self

    def test_graph(self):
        vault_md.write("home.md", "go to [[about]] and [[contact]]")
        vault_md.write("about.md", "back [[home]]")
        vault_md.write("contact.md", "x")
        g = vault_md.graph()
        self.assertEqual(len(g["nodes"]), 3)
        pairs = {(e["source"], e["target"]) for e in g["edges"]}
        self.assertIn(("home", "about"), pairs)
        self.assertIn(("about", "home"), pairs)
        home = next(n for n in g["nodes"] if n["id"] == "home")
        self.assertEqual(home["degree"], 3)  # 2 out + 1 in


    def test_set_cell_keeps_a_list_prop_a_list(self):
        # editing a list-valued frontmatter cell must not flatten it to a comma string
        vault_md.write("n.md", "---\npeople:\n  - alice\n  - bob\n---\nbody")
        vault_md.set_cell("n.md", "people", "alice, bob, carol")
        props, _ = vault_md.parse_frontmatter(vault_md.read("n.md")["content"])
        self.assertEqual(props["people"], ["alice", "bob", "carol"])

    def test_set_cell_scalar_stays_scalar(self):
        vault_md.write("n2.md", "---\ntitle: hi\n---\nbody")
        vault_md.set_cell("n2.md", "title", "hello there")
        props, _ = vault_md.parse_frontmatter(vault_md.read("n2.md")["content"])
        self.assertEqual(props["title"], "hello there")


if __name__ == "__main__":
    unittest.main()
