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
        ss.upsert_skill(
            "Summarize", "shorten long text", "when asked for a tl;dr", "1. read\n2. condense"
        )
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
        body = "step one\n---\nstep two"  # body containing a --- line
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

    def test_seed_starters_once_and_deletion_sticks(self):
        n = ss.seed_starters()
        self.assertEqual(n, len(ss._STARTERS))
        self.assertEqual(len(ss.list_skills()), len(ss._STARTERS))
        # sentinel → a second seed is a no-op, even after the user deletes one
        ss.delete_skill(ss.list_skills()[0]["slug"])
        self.assertEqual(ss.seed_starters(), 0)
        self.assertEqual(len(ss.list_skills()), len(ss._STARTERS) - 1)

    def test_record_use_counts_and_ranks_to_top(self):
        ss.upsert_skill("Alpha", "a")
        ss.upsert_skill("Beta", "b")
        ss.record_use("beta")
        ss.record_use("beta")
        got = {s["slug"]: s for s in ss.list_skills()}
        self.assertEqual(got["beta"]["uses"], 2)
        self.assertEqual(got["alpha"]["uses"], 0)
        # most-used sorts first
        self.assertEqual(ss.list_skills()[0]["slug"], "beta")

    def test_pin_sorts_above_usage(self):
        ss.upsert_skill("Used", "x")
        ss.upsert_skill("Pinned", "y")
        ss.record_use("used")
        ss.record_use("used")
        self.assertTrue(ss.set_pinned("pinned", True))
        self.assertEqual(ss.list_skills()[0]["slug"], "pinned")
        self.assertTrue(ss.list_skills()[0]["pinned"])
        # unpin → the used one comes back to the top
        ss.set_pinned("pinned", False)
        self.assertEqual(ss.list_skills()[0]["slug"], "used")

    def test_delete_clears_usage(self):
        ss.upsert_skill("Gone", "z")
        ss.record_use("gone")
        ss.delete_skill("gone")
        self.assertEqual(ss._load_usage(), {})
        # re-creating with the same slug starts fresh, not stale counts
        ss.upsert_skill("Gone", "z")
        self.assertEqual(ss.get_skill("gone")["uses"], 0)

    def test_match_boosts_used_skills(self):
        ss.upsert_skill("Email A", "draft emails", "when composing an email")
        ss.upsert_skill("Email B", "draft emails", "when composing an email")
        ss.record_use("email-b")
        # identical text → usage breaks the tie
        self.assertEqual(ss.match_skills("compose an email")[0]["slug"], "email-b")

    def test_seed_library_installs_whole_catalog_once(self):
        fake = [
            {"slug": "one", "name": "One", "description": "d1", "when_to_use": "", "body": "b1"},
            {"slug": "two", "name": "Two", "description": "d2", "when_to_use": "", "body": "b2"},
        ]
        with mock.patch("services.skills_catalog.items", return_value=fake):
            self.assertEqual(ss.seed_library(), 2)
            self.assertEqual(len(ss.list_skills()), 2)
            # sentinel → second run is a no-op even after deleting one
            ss.delete_skill("one")
            self.assertEqual(ss.seed_library(), 0)
            self.assertEqual(len(ss.list_skills()), 1)


if __name__ == "__main__":
    unittest.main()
