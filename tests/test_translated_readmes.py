import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ("fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")
SOURCE_REVISION = "phase10-canonical-2026-07-21"


class TranslatedReadmeTests(unittest.TestCase):
    def test_every_translation_records_review_and_command_parity(self):
        required_fragments = (
            SOURCE_REVISION,
            "git clone https://github.com/jxherc/alles.git",
            "pip install -r requirements.lock",
            "python app.py",
            "docker build -t alles .",
            "-p 127.0.0.1:6769:6769",
            "../../specifications.md#security--read-before-exposing-it",
            "../../THIRD_PARTY_NOTICES.md",
            "../../LICENSE",
        )
        for language in TRANSLATIONS:
            with self.subTest(language=language):
                path = ROOT / "docs" / "readme" / f"README.{language}.md"
                text = path.read_text("utf-8")
                for fragment in required_fragments:
                    self.assertIn(fragment, text)

    def test_canonical_readme_links_every_reviewed_translation(self):
        text = (ROOT / "README.md").read_text("utf-8")
        for language in TRANSLATIONS:
            self.assertIn(f"docs/readme/README.{language}.md", text)


if __name__ == "__main__":
    unittest.main()
