import json
import shutil
import tempfile
import unittest
from pathlib import Path

from services import native_install
from services.credits import ROOT, verify_release_notice_set


class ReleaseNoticePackagingTests(unittest.TestCase):
    def test_current_generated_notice_set_is_complete_and_exact(self):
        result = verify_release_notice_set()
        notice_set = json.loads((ROOT / "credits" / "release-notice-files.json").read_text("utf-8"))
        self.assertEqual(result["file_count"], len(notice_set["files"]))
        self.assertGreater(result["file_count"], 400)

    def test_generated_license_directory_has_no_stale_files(self):
        index = json.loads((ROOT / "licenses" / "index.json").read_text("utf-8"))
        expected = {"licenses/index.json", *(item["path"] for item in index["files"])}
        actual = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "licenses").rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, expected)

    def test_explicit_license_sources_ship_complete_terms_not_source_code(self):
        manifest = json.loads((ROOT / "credits" / "manifest.json").read_text("utf-8"))
        entries = {entry["name"]: entry for entry in manifest["entries"]}
        expected_phrases = {
            "akahu": ("permission to use, copy, modify", "this permission notice appear"),
            "keyv": ("permission is hereby granted", "copyright notice and this permission notice"),
            "pluggy-sdk": (
                "permission is hereby granted",
                "copyright notice and this permission notice",
            ),
        }
        for package, phrases in expected_phrases.items():
            with self.subTest(package=package):
                paths = entries[package]["license_files"]
                self.assertEqual(len(paths), 1)
                text = (ROOT / paths[0]).read_text("utf-8").lower()
                for phrase in phrases:
                    self.assertIn(phrase, text)
                self.assertIn('the software is provided "as is"', text)
                self.assertNotIn("export declare class", text)

    def test_native_copy_preserves_the_exact_notice_set(self):
        notice_set = json.loads((ROOT / "credits" / "release-notice-files.json").read_text("utf-8"))
        support_files = [
            "credits/release-notice-files.json",
            *notice_set["files"],
        ]
        with tempfile.TemporaryDirectory(prefix="alles-notice-package-") as raw:
            base = Path(raw)
            source = base / "source"
            release = base / "release"
            for relative in support_files:
                destination = source / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            shutil.copytree(source, release, ignore=native_install._copy_ignore)
            result = verify_release_notice_set(release)
        self.assertEqual(result["file_count"], len(notice_set["files"]))

    def test_missing_release_notice_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="alles-notice-missing-") as raw:
            root = Path(raw)
            (root / "credits").mkdir()
            (root / "credits" / "release-notice-files.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_revision": "test",
                        "files": ["missing.txt"],
                    }
                ),
                "utf-8",
            )
            with self.assertRaises((FileNotFoundError, ValueError)):
                verify_release_notice_set(root)

    def test_container_build_checks_generated_credits_after_copy(self):
        dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
        self.assertIn("COPY requirements.txt requirements.lock ./", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.lock", dockerfile)
        copy_index = dockerfile.index("COPY . .")
        check_index = dockerfile.index("RUN python scripts/generate_credits.py")
        self.assertGreater(check_index, copy_index)
        dockerignore = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
        blocked = {line.strip().rstrip("/") for line in dockerignore if line.strip()}
        self.assertFalse(
            {"credits", "licenses", "ACKNOWLEDGMENTS.md", "THIRD_PARTY_NOTICES.md"} & blocked
        )
        self.assertTrue({".env", ".env.*", ".agent", ".Codex", ".codex", "AGENTS.md"} <= blocked)


if __name__ == "__main__":
    unittest.main()
