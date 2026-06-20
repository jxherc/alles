import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import skills_github, skills_store
from tests._client import ApiTest

SKILL_MD = (
    "---\nname: Deploy\ndescription: ship it\nwhen_to_use: deploying\n---\n\n1. build\n2. push\n"
)


class _StoreBase(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp(prefix="skills10c-")
        self.p = mock.patch.object(skills_store, "SKILLS_DIR", Path(self._d))
        self.p.start()

    def tearDown(self):
        self.p.stop()


class SourceTrackingTests(_StoreBase):
    def test_source_roundtrips(self):
        skills_store.upsert_skill("Deploy", "ship it", "deploying", "do it", source="https://x/y")
        self.assertEqual(skills_store.get_skill("deploy")["source"], "https://x/y")

    def test_serialize_includes_source(self):
        md = skills_store._serialize("N", "d", "w", "body", source="https://s")
        self.assertIn("source: https://s", md)
        self.assertEqual(skills_store._parse(md)["meta"]["source"], "https://s")

    def test_upsert_without_source_omits_line(self):
        skills_store.upsert_skill("Plain", "p", "", "body")
        self.assertEqual(skills_store.get_skill("plain")["source"], "")
        md = skills_store.export_md("plain")
        self.assertNotIn("source:", md)

    def test_source_in_list(self):
        skills_store.upsert_skill("Deploy", "d", "", "b", source="https://x/y")
        row = next(s for s in skills_store.list_skills() if s["slug"] == "deploy")
        self.assertEqual(row["source"], "https://x/y")


class ExportTests(_StoreBase):
    def test_export_md_returns_full(self):
        skills_store.upsert_skill("Deploy", "ship it", "deploying", "step one")
        md = skills_store.export_md("deploy")
        self.assertTrue(md.startswith("---"))
        self.assertIn("name: Deploy", md)
        self.assertIn("step one", md)

    def test_export_unknown_none(self):
        self.assertIsNone(skills_store.export_md("ghost"))

    def test_export_all_bundle(self):
        skills_store.upsert_skill("A", "a", "", "ba")
        skills_store.upsert_skill("B", "b", "", "bb")
        bundle = skills_store.export_all()
        slugs = {b["slug"] for b in bundle}
        self.assertEqual(slugs, {"a", "b"})
        self.assertTrue(all("md" in b and b["md"].startswith("---") for b in bundle))


class GithubSourceTests(_StoreBase):
    def test_import_sets_source(self):
        with mock.patch.object(skills_github, "_fetch", return_value=SKILL_MD):
            res = skills_github.import_from_github(
                "https://github.com/o/r/blob/main/deploy/SKILL.md"
            )
        slug = res["imported"][0]
        self.assertEqual(
            skills_store.get_skill(slug)["source"],
            "https://github.com/o/r/blob/main/deploy/SKILL.md",
        )

    def test_update_re_fetches(self):
        with mock.patch.object(skills_github, "_fetch", return_value=SKILL_MD):
            skills_github.import_from_github("https://github.com/o/r/blob/main/deploy/SKILL.md")
        updated = SKILL_MD.replace("1. build", "1. build the new way")
        with mock.patch.object(skills_github, "_fetch", return_value=updated):
            r = skills_store.update_from_source("deploy")
        self.assertTrue(r["updated"])
        self.assertIn("the new way", skills_store.get_skill("deploy")["body"])

    def test_update_no_source_noop(self):
        skills_store.upsert_skill("Local", "l", "", "body")
        self.assertFalse(skills_store.update_from_source("local")["updated"])


class SkillsApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._d = tempfile.mkdtemp(prefix="skills10capi-")
        self.p = mock.patch.object(skills_store, "SKILLS_DIR", Path(self._d))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def test_api_export_markdown(self):
        skills_store.upsert_skill("Deploy", "ship", "", "step one")
        r = self.client.get("/api/skills/deploy/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("name: Deploy", r.text)

    def test_api_update(self):
        with mock.patch.object(skills_github, "_fetch", return_value=SKILL_MD):
            self.client.post(
                "/api/skills/import-github",
                json={"url": "https://github.com/o/r/blob/main/deploy/SKILL.md"},
            )
        updated = SKILL_MD.replace("1. build", "1. rebuilt")
        with mock.patch.object(skills_github, "_fetch", return_value=updated):
            r = self.client.post("/api/skills/deploy/update")
        self.assertEqual(r.status_code, 200)
        self.assertIn("rebuilt", skills_store.get_skill("deploy")["body"])
