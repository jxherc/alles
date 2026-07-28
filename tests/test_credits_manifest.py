import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import generate_credits
from services.credits import load_credit_detail, load_credits_manifest
from tests._client import ApiTest


class CreditsManifestTests(ApiTest):
    def test_python_sdist_license_discovery_reads_an_in_memory_tar_archive(self):
        payload = io.BytesIO()
        license_text = b"sdist license grant"
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            member = tarfile.TarInfo("example-1.0/LICENSE")
            member.size = len(license_text)
            archive.addfile(member, io.BytesIO(license_text))
        metadata = json.dumps(
            {
                "urls": [
                    {
                        "packagetype": "sdist",
                        "url": "https://example.test/example-1.0.tar.gz",
                        "digests": {"sha256": ""},
                    }
                ]
            }
        ).encode()
        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                generate_credits,
                "_download",
                side_effect=[metadata, payload.getvalue()],
            ),
        ):
            candidates = generate_credits._python_archive_license_candidates(
                "example", "1.0", Path(raw)
            )

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].read_bytes(), license_text)

    def test_python_sdist_keeps_distinct_nested_license_paths(self):
        payload = io.BytesIO()
        files = {
            "example-1.0/LICENSE": b"project grant",
            "example-1.0/vendor/dependency/LICENSE": b"vendored grant",
        }
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        metadata = json.dumps(
            {
                "urls": [
                    {
                        "packagetype": "sdist",
                        "url": "https://example.test/example-1.0.tar.gz",
                        "digests": {"sha256": ""},
                    }
                ]
            }
        ).encode()
        with (
            tempfile.TemporaryDirectory() as raw,
            mock.patch.object(
                generate_credits,
                "_download",
                side_effect=[metadata, payload.getvalue()],
            ),
        ):
            candidates = generate_credits._python_archive_license_candidates(
                "example", "1.0", Path(raw)
            )
            contents = {
                candidate.relative_to(raw).as_posix(): candidate.read_bytes()
                for candidate in candidates
            }

        self.assertEqual(set(contents.values()), set(files.values()))
        self.assertEqual(len(contents), 2)

    def test_node_license_discovery_includes_nested_package_licenses(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            root_license = root / "LICENSE"
            nested_license = root / "src" / "component" / "LICENSE.md"
            nested_license.parent.mkdir(parents=True)
            root_license.write_text("root grant", "utf-8")
            nested_license.write_text("nested grant", "utf-8")
            self.assertEqual(
                generate_credits._license_candidates(root),
                [root_license, nested_license],
            )

    def test_authors_files_are_not_accepted_as_license_grants(self):
        self.assertIsNone(generate_credits.LICENSE_FILE_RE.match("AUTHORS"))
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            authors = root / "licenses" / "AUTHORS"
            license_file = root / "licenses" / "LICENSE.txt"
            authors.parent.mkdir()
            authors.write_text("names only", "utf-8")
            license_file.write_text("license grant", "utf-8")
            distribution = mock.Mock()
            distribution.files = [Path("licenses/AUTHORS"), Path("licenses/LICENSE.txt")]
            distribution.locate_file.side_effect = lambda item: root / item
            self.assertEqual(
                generate_credits._python_license_candidates(distribution), [license_file]
            )
        manifest = json.loads(generate_credits.MANIFEST_PATH.read_text("utf-8"))
        license_paths = [
            path for entry in manifest["entries"] for path in entry.get("license_files", [])
        ]
        self.assertFalse(
            any(generate_credits._license_text_role(path) != "license" for path in license_paths)
        )

    def test_multiline_package_license_uses_classifier_identifier(self):
        metadata = mock.Mock()
        metadata.get.side_effect = lambda name: (
            "The MIT License (MIT)\n\nfull license body" if name == "License" else None
        )
        metadata.get_all.return_value = ["License :: OSI Approved :: MIT License"]
        self.assertEqual(generate_credits._license_value(metadata), "MIT")

    def test_placeholder_metadata_license_defers_to_vendored_text(self):
        metadata = mock.Mock()
        metadata.get.side_effect = lambda name: "UNKNOWN" if name == "License" else None
        metadata.get_all.return_value = []
        self.assertEqual(generate_credits._license_value(metadata), "")
        self.assertEqual(
            generate_credits._infer_license(
                ["Permission is hereby granted, free of charge, to any person"]
            ),
            "MIT",
        )

    def test_notice_table_cells_cannot_create_extra_markdown_rows(self):
        manifest = {
            "source_revision": "test",
            "boundaries": {},
            "entries": [
                {
                    "name": "package|name",
                    "version": "1.0\nignored",
                    "license": "MIT\nfull text",
                    "source_url": "https://example.test/source",
                    "license_files": [],
                    "notice_files": [],
                }
            ],
        }
        notices = generate_credits._notices(manifest)
        self.assertIn("| package\\|name | `1.0 ignored` | MIT full text |", notices)
        self.assertNotIn("\nfull text", notices)

    def test_current_manifest_is_complete_and_metadata_only(self):
        data = load_credits_manifest()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["coverage"]["entry_count"], len(data["entries"]))
        self.assertGreater(data["coverage"]["entry_count"], 0)
        self.assertTrue(data["coverage"]["complete"])
        self.assertEqual(data["coverage"]["gap_count"], 0)
        xterm = next(item for item in data["entries"] if item["id"] == "xterm-js")
        self.assertEqual(xterm["local_file_count"], 1)
        self.assertNotIn("license_texts", xterm)
        self.assertNotIn("notice_texts", xterm)

    def test_detail_loads_only_the_selected_local_text(self):
        xterm = load_credit_detail("xterm-js")
        self.assertEqual(len(xterm["license_texts"]), 1)
        self.assertIn("Permission is hereby granted", xterm["license_texts"][0]["text"])
        self.assertEqual(xterm["notice_texts"], [])
        with self.assertRaises(KeyError):
            load_credit_detail("not-a-real-credit")

    def test_manifest_rejects_duplicate_ids(self):
        entry = {
            "id": "same",
            "name": "same",
            "category": "code",
            "summary": "test",
            "version": "1.0.0",
            "license": "MIT",
            "source_url": "https://example.com/source",
            "bundled": False,
            "notice_required": False,
            "license_files": [],
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "credits.json"
            path.write_text(json.dumps({"schema_version": 1, "entries": [entry, entry]}), "utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                load_credits_manifest(path)

    def test_credits_api_returns_only_validated_manifest_data(self):
        response = self.client.get("/api/credits")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["coverage"]["entry_count"], len(data["entries"]))
        self.assertTrue(all(item["source_url"].startswith("https://") for item in data["entries"]))
        self.assertNotIn("license_files", data["entries"][0])
        self.assertNotIn("license_texts", data["entries"][0])
        self.assertLess(len(response.content), 500_000)

    def test_python_source_inventory_matches_every_direct_requirement(self):
        root = Path(__file__).resolve().parent.parent
        sources = json.loads((root / "credits" / "sources.json").read_text("utf-8"))
        listed = {item["package"].lower() for item in sources["python"]}
        pinned = set()
        pattern = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==")
        for raw in (root / "requirements.txt").read_text("utf-8").splitlines():
            if match := pattern.match(raw.strip()):
                pinned.add(match.group(1).lower())
        self.assertEqual(listed, pinned)

    def test_credit_detail_api_is_lazy_and_missing_ids_are_404(self):
        response = self.client.get("/api/credits/xterm-js")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "xterm-js")
        self.assertIn("Permission is hereby granted", data["license_texts"][0]["text"])
        missing = self.client.get("/api/credits/not-a-real-credit")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
