import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import skills_store as ss


class SkillsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ss, "SKILLS_DIR", Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_slug_normalizes(self):
        self.assertEqual(ss._slug("PDF Form Filler!"), "pdf-form-filler")
        with self.assertRaises(ValueError):
            ss._slug("   ")

    def test_traversal_neutralized(self):
        # slugify turns separators into dashes, so the path can never escape the dir…
        p = ss._path("../../etc/passwd")
        self.assertTrue(str(p.resolve()).startswith(str(Path(self.tmp.name).resolve())))
        # …and a bare ".." slugifies to nothing usable → rejected outright
        with self.assertRaises(ValueError):
            ss._path("..")

    def test_upsert_get_list_delete(self):
        ss.upsert_skill("Summarize", "shorten long text", "when asked for a tl;dr", "1. read\n2. condense")
        skills = ss.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["slug"], "summarize")
        got = ss.get_skill("summarize")
        self.assertEqual(got["name"], "Summarize")
        self.assertEqual(got["when_to_use"], "when asked for a tl;dr")
        self.assertIn("condense", got["body"])
        self.assertTrue(ss.delete_skill("summarize"))
        self.assertEqual(ss.list_skills(), [])
        self.assertFalse(ss.delete_skill("summarize"))

    def test_upsert_overwrites_same_slug(self):
        ss.upsert_skill("Note Taker", "v1")
        ss.upsert_skill("Note Taker", "v2")
        self.assertEqual(len(ss.list_skills()), 1)
        self.assertEqual(ss.get_skill("note-taker")["description"], "v2")

    def test_frontmatter_roundtrip_preserves_body_with_dashes(self):
        body = "step one\n---\nstep two"          # body containing a --- line
        ss.upsert_skill("Tricky", "d", "", body)
        self.assertEqual(ss.get_skill("tricky")["body"], body)

    def test_match_ranks_by_overlap(self):
        ss.upsert_skill("PDF Filler", "fill pdf forms", "when the user has a pdf form to populate")
        ss.upsert_skill("Email Writer", "draft emails", "when composing an email")
        m = ss.match_skills("help me fill out this pdf form")
        self.assertEqual(m[0]["slug"], "pdf-filler")
        self.assertGreater(m[0]["score"], 0)

    def test_match_empty_query(self):
        ss.upsert_skill("X", "y")
        self.assertEqual(ss.match_skills(""), [])

    def test_search_filters(self):
        ss.upsert_skill("Alpha", "about cats")
        ss.upsert_skill("Beta", "about dogs")
        self.assertEqual([s["slug"] for s in ss.search("cats")], ["alpha"])


if __name__ == "__main__":
    unittest.main()
