import json
import tempfile
import unittest
from pathlib import Path

from services.localization import (
    CATALOG_DIR,
    load_catalog,
    localization_options,
    validate_catalogs,
)


class LocalizationCatalogTests(unittest.TestCase):
    def _catalog_copy(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for source in CATALOG_DIR.glob("*.json"):
            (root / source.name).write_bytes(source.read_bytes())
        return temporary, root

    def test_all_eight_catalogs_have_review_metadata_and_exact_parity(self):
        status = validate_catalogs()
        self.assertEqual(
            [item["id"] for item in status["languages"]],
            ["en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar"],
        )
        self.assertGreater(status["message_count"], 30)
        self.assertGreaterEqual(status["plural_count"], 1)
        self.assertTrue(all(item["catalog_valid"] for item in status["languages"]))
        self.assertTrue(all(item["review"]["reviewer"] for item in status["languages"]))

    def test_all_languages_that_passed_release_gates_are_selectable(self):
        languages = localization_options()["languages"]
        self.assertEqual(
            [item["id"] for item in languages if item["available"]],
            ["en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar"],
        )
        self.assertTrue(all(item["review_state"] for item in languages))
        self.assertEqual(localization_options()["currencies"][0]["value"], "")

    def test_load_catalog_returns_local_reviewed_content(self):
        catalog = load_catalog("zh-hant")
        self.assertEqual(catalog["language"], "zh-Hant")
        self.assertEqual(catalog["messages"]["locale.title"], "語言與地區")

    def test_missing_message_key_fails_parity(self):
        temporary, root = self._catalog_copy()
        self.addCleanup(temporary.cleanup)
        path = root / "fr.json"
        payload = json.loads(path.read_text("utf-8"))
        payload["messages"].pop("common.retry")
        path.write_text(json.dumps(payload), "utf-8")
        with self.assertRaisesRegex(ValueError, "message keys"):
            validate_catalogs(root, root / "manifest.json")

    def test_changed_placeholder_fails_parity(self):
        temporary, root = self._catalog_copy()
        self.addCleanup(temporary.cleanup)
        path = root / "es.json"
        payload = json.loads(path.read_text("utf-8"))
        payload["messages"]["schedule.confirmed"] = "programado {hora}"
        path.write_text(json.dumps(payload), "utf-8")
        with self.assertRaisesRegex(ValueError, "incorrect placeholders"):
            validate_catalogs(root, root / "manifest.json")

    def test_missing_locale_plural_form_fails_contract(self):
        temporary, root = self._catalog_copy()
        self.addCleanup(temporary.cleanup)
        path = root / "ar.json"
        payload = json.loads(path.read_text("utf-8"))
        payload["plurals"]["credits.item_count"].pop("few")
        path.write_text(json.dumps(payload), "utf-8")
        with self.assertRaisesRegex(ValueError, "incorrect categories"):
            validate_catalogs(root, root / "manifest.json")

    def test_stale_source_revision_and_unreviewed_catalog_fail(self):
        for field, value, error in (
            ("source_revision", "old", "stale source revision"),
            ("review", {"state": "draft"}, "editorial review"),
        ):
            with self.subTest(field=field):
                temporary, root = self._catalog_copy()
                path = root / "ja.json"
                payload = json.loads(path.read_text("utf-8"))
                payload[field] = value
                path.write_text(json.dumps(payload), "utf-8")
                with self.assertRaisesRegex(ValueError, error):
                    validate_catalogs(root, root / "manifest.json")
                temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
