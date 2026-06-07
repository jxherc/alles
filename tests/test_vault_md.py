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
        self.assertNotIn("ignore", names)   # non-md excluded

    def test_backlinks(self):
        vault_md.write("one.md", "see [[target]] here")
        vault_md.write("two.md", "also [[Target]] and [[other]]")
        vault_md.write("target.md", "i am the target")
        bl = vault_md.backlinks("target")
        names = {b["name"] for b in bl}
        self.assertEqual(names, {"one", "two"})   # case-insensitive, excludes self

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
        self.assertEqual(res[0]["name"], "alpha")   # prefix match ranks first

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
        self.assertEqual(home["degree"], 3)   # 2 out + 1 in


if __name__ == "__main__":
    unittest.main()
