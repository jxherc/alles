"""coverage for services/skills_catalog.py — the built-in skill library loader.
locks in the fallback-to-_BASE behavior, slug de-dup, and category-from-filename mapping."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import skills_catalog as sc


class CatalogLoadTests(unittest.TestCase):
    def setUp(self):
        sc._cat_map = None  # reset the module-level category cache between tests

    def tearDown(self):
        sc._cat_map = None

    def _with_lib(self, files: dict):
        # files: {filename: python list to dump as json}; returns a patch ctx on _LIB_DIR
        d = tempfile.mkdtemp(prefix="skilllib-")
        for name, data in files.items():
            Path(d, name).write_text(json.dumps(data), "utf-8")
        return mock.patch.object(sc, "_LIB_DIR", Path(d))

    def test_falls_back_to_base_when_empty(self):
        with mock.patch.object(sc, "_LIB_DIR", Path(tempfile.mkdtemp())):
            names = {x["name"] for x in sc._load()}
        self.assertIn("Summarize", names)  # _BASE fallback

    def test_loads_from_files_with_category_from_stem(self):
        with self._with_lib({"coding.json": [{"name": "Refactor", "body": "x"}]}):
            rows = sc.items()
        ref = next(r for r in rows if r["name"] == "Refactor")
        self.assertEqual(ref["category"], "coding")  # filename → category

    def test_malformed_file_is_skipped_not_fatal(self):
        d = tempfile.mkdtemp(prefix="skilllib-")
        Path(d, "good.json").write_text(json.dumps([{"name": "Keep", "body": "y"}]), "utf-8")
        Path(d, "bad.json").write_text("{not valid json", "utf-8")
        with mock.patch.object(sc, "_LIB_DIR", Path(d)):
            names = {x["name"] for x in sc._load()}
        self.assertIn("Keep", names)  # the good file still loaded despite the broken one

    def test_items_dedupes_by_slug(self):
        with self._with_lib(
            {"a.json": [{"name": "Dup Skill"}], "b.json": [{"name": "Dup Skill"}]}
        ):
            rows = [r for r in sc.items() if r["name"] == "Dup Skill"]
        self.assertEqual(len(rows), 1)  # same name → same slug → kept once

    def test_get_and_category_for(self):
        with self._with_lib({"writing.json": [{"name": "Outline", "body": "z"}]}):
            rows = sc.items()
            slug = next(r["slug"] for r in rows if r["name"] == "Outline")
            self.assertEqual(sc.get(slug)["name"], "Outline")
            self.assertEqual(sc.category_for(slug), "writing")
            self.assertIsNone(sc.get("no-such-slug"))

    def test_entries_without_name_are_dropped(self):
        with self._with_lib({"x.json": [{"description": "no name here"}, {"name": "Has Name"}]}):
            names = {x["name"] for x in sc._load()}
        self.assertIn("Has Name", names)
        self.assertNotIn("", names)


if __name__ == "__main__":
    unittest.main()
