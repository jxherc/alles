import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from services.backup_recovery import (
    DATA_CLASS_POLICIES,
    LOCATION_ROLES,
    ArchiveLimits,
    RecoveryError,
    create_recovery_archive,
    current_schema_version,
    discard_staged_recovery,
    refresh_prepared_recovery,
    stage_recovery_archive,
    staging_root,
    validate_relative_path,
    verify_staged_recovery,
)


class BackupRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.live = self.base / "data"
        self.live.mkdir()
        self._make_alles_db(self.live / "aide.db", versions=(1,))
        (self.live / "settings.json").write_text('{"theme":"dark"}', "utf-8")
        (self.live / "vault" / "Notes").mkdir(parents=True)
        (self.live / "vault" / "Notes" / "hello.md").write_text("hello", "utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _make_alles_db(path: Path, *, versions=()):
        from core.migrations.runner import discover

        migration_names = {module.VERSION: module.NAME for module in discover()}
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            for version in versions:
                name = migration_names.get(version, f"m{version}")
                conn.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                    (version, name, "2026-01-01T00:00:00"),
                )
            conn.commit()

    def _archive(self) -> Path:
        archive = self.base / "backup.zip"
        create_recovery_archive(self.live, archive)
        return archive

    @staticmethod
    def _rewrite_archive(source: Path, dest: Path, mutate):
        with zipfile.ZipFile(source) as original:
            entries = [(info.filename, original.read(info)) for info in original.infolist()]
        entries = mutate(entries)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as changed:
            for name, content in entries:
                changed.writestr(name, content)

    def test_v1_roundtrip_has_sorted_hashed_manifest_and_stages_without_touching_live(self):
        archive = self._archive()
        original_db = (self.live / "aide.db").read_bytes()
        original_note = (self.live / "vault" / "Notes" / "hello.md").read_text("utf-8")

        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(manifest["format"], "alles-recovery")
            self.assertEqual(manifest["format_version"], 1)
            paths = [item["path"] for item in manifest["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertIn("aide.db", paths)
            for item in manifest["files"]:
                self.assertEqual(item["storage"], "data")
                payload = zf.read(f"payload/data/{item['path']}")
                self.assertEqual(item["size"], len(payload))
                self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())

        staged = stage_recovery_archive(archive, self.live)

        self.assertEqual((self.live / "aide.db").read_bytes(), original_db)
        self.assertEqual(
            (self.live / "vault" / "Notes" / "hello.md").read_text("utf-8"), original_note
        )
        self.assertEqual(
            (staged.data_dir / "vault" / "Notes" / "hello.md").read_text("utf-8"), "hello"
        )
        self.assertTrue((staged.root / "stage.json").is_file())

    def test_relative_path_validation_covers_generated_safe_and_unsafe_shapes(self):
        components = ["plain", "two words", "ümlaut", "file.name", "name:note"]
        for first in components:
            for second in components:
                path = f"{first}/{second}"
                with self.subTest(path=path):
                    self.assertEqual(validate_relative_path(path), path)

        invalid = [
            "",
            ".",
            "..",
            "/absolute",
            "../escape",
            "safe/../escape",
            "safe//file",
            "safe/./file",
            "safe\\file",
            "C:/drive",
            "safe/\x00bad",
            "safe/\nbad",
        ]
        for path in invalid:
            with self.subTest(path=repr(path)):
                with self.assertRaises(RecoveryError):
                    validate_relative_path(path)

    def test_hash_mismatch_is_rejected_and_partial_stage_is_removed(self):
        archive = self._archive()
        changed = self.base / "tampered.zip"

        def mutate(entries):
            return [
                (name, b'{"theme":"evil"}' if name == "payload/data/settings.json" else content)
                for name, content in entries
            ]

        self._rewrite_archive(archive, changed, mutate)
        with self.assertRaisesRegex(RecoveryError, "checksum"):
            stage_recovery_archive(changed, self.live)
        self.assertEqual(list((staging_root(self.live) / "staged").glob("*")), [])

    def test_missing_extra_and_duplicate_payload_members_are_rejected(self):
        archive = self._archive()

        cases = {
            "missing": lambda entries: [
                item for item in entries if item[0] != "payload/data/settings.json"
            ],
            "extra": lambda entries: [*entries, ("payload/data/not-in-manifest.txt", b"extra")],
            "duplicate": lambda entries: [
                *entries,
                next(item for item in entries if item[0] == "payload/data/settings.json"),
            ],
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                changed = self.base / f"{label}.zip"
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    self._rewrite_archive(archive, changed, mutate)
                with self.assertRaises(RecoveryError):
                    stage_recovery_archive(changed, self.live)

    def test_resource_limits_reject_file_count_total_size_and_compression_ratio(self):
        archive = self._archive()
        cases = [
            ArchiveLimits(max_files=1),
            ArchiveLimits(max_total_bytes=10),
            ArchiveLimits(max_compression_ratio=1.01, ratio_check_min_bytes=1),
        ]
        for limits in cases:
            with self.subTest(limits=limits):
                with self.assertRaises(RecoveryError):
                    stage_recovery_archive(archive, self.live, limits=limits)

    def test_corrupt_sqlite_and_future_schema_are_rejected(self):
        archive = self._archive()

        def corrupt_db(entries):
            manifest = json.loads(next(data for name, data in entries if name == "manifest.json"))
            payload = b"not sqlite"
            for item in manifest["files"]:
                if item["path"] == "aide.db":
                    old_size = item["size"]
                    item["size"] = len(payload)
                    item["sha256"] = hashlib.sha256(payload).hexdigest()
                    manifest["totals"]["bytes"] += len(payload) - old_size
            return [
                ("manifest.json", json.dumps(manifest).encode())
                if name == "manifest.json"
                else (name, payload)
                if name == "payload/data/aide.db"
                else (name, data)
                for name, data in entries
            ]

        corrupt = self.base / "corrupt.zip"
        self._rewrite_archive(archive, corrupt, corrupt_db)
        with self.assertRaisesRegex(RecoveryError, "SQLite"):
            stage_recovery_archive(corrupt, self.live)

        future_root = self.base / "future-data"
        future_root.mkdir()
        self._make_alles_db(
            future_root / "aide.db", versions=range(1, current_schema_version() + 2)
        )
        future = self.base / "future.zip"
        with self.assertRaisesRegex(RecoveryError, "newer or unknown"):
            create_recovery_archive(future_root, future)
        with zipfile.ZipFile(future, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(future_root / "aide.db", "aide.db")
        with self.assertRaisesRegex(RecoveryError, "newer or unknown"):
            stage_recovery_archive(future, self.live)

    def test_legacy_backup_is_normalized_to_v1_in_staging(self):
        legacy = self.base / "legacy.zip"
        with zipfile.ZipFile(legacy, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.writestr("uploads/old.txt", b"old")

        staged = stage_recovery_archive(legacy, self.live)

        self.assertEqual(staged.manifest["format_version"], 1)
        self.assertEqual(staged.manifest["source_format_version"], 0)
        self.assertEqual((staged.data_dir / "uploads" / "old.txt").read_bytes(), b"old")

    def test_zip_symlink_and_traversal_are_rejected(self):
        for label, info in (
            ("traversal", zipfile.ZipInfo("../escape")),
            ("symlink", zipfile.ZipInfo("linked")),
        ):
            legacy = self.base / f"legacy-{label}.zip"
            if label == "symlink":
                info.create_system = 3
                info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(legacy, "w") as zf:
                zf.write(self.live / "aide.db", "aide.db")
                zf.writestr(info, b"bad")
            with self.subTest(label=label), self.assertRaises(RecoveryError):
                stage_recovery_archive(legacy, self.live)

    def test_portable_name_collisions_and_directory_limits_are_rejected(self):
        collision = self.base / "collision.zip"
        with zipfile.ZipFile(collision, "w") as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.writestr("Folder/item.txt", b"one")
            zf.writestr("folder/ITEM.txt", b"two")
        with self.assertRaisesRegex(RecoveryError, "collide"):
            stage_recovery_archive(collision, self.live)

        too_many = self.base / "too-many-dirs.zip"
        with zipfile.ZipFile(too_many, "w") as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.writestr("one/", b"")
            zf.writestr("two/", b"")
        with self.assertRaises(RecoveryError):
            stage_recovery_archive(too_many, self.live, limits=ArchiveLimits(max_files=2))

    def test_photos_are_opt_in_and_the_manifest_records_that_choice(self):
        (self.live / "photos").mkdir()
        (self.live / "photos" / "private.jpg").write_bytes(b"photo")

        default_archive = self.base / "without-photos.zip"
        default_manifest = create_recovery_archive(self.live, default_archive)
        photo_location = next(
            item for item in default_manifest["locations"] if item["role"] == "photos"
        )
        self.assertFalse(photo_location["included"])
        self.assertNotIn("photos/private.jpg", [item["path"] for item in default_manifest["files"]])

        selected_archive = self.base / "with-photos.zip"
        selected_manifest = create_recovery_archive(
            self.live, selected_archive, include_photos=True
        )
        self.assertIn("photos/private.jpg", [item["path"] for item in selected_manifest["files"]])

    def test_manifest_records_data_classes_and_every_configured_root_policy(self):
        external = self.base / "external"
        roots = {}
        for name in ("vault", "files", "photos", "watch", "agent"):
            root = external / name
            root.mkdir(parents=True)
            (root / f"{name}-only.txt").write_text("external private content", "utf-8")
            roots[name] = root
        (self.live / "settings.json").write_text(
            json.dumps(
                {
                    "vault_dir": str(roots["vault"]),
                    "files_dir": str(roots["files"]),
                    "photos_dir": str(roots["photos"]),
                    "photos_watch_folder": str(roots["watch"]),
                    "agent_allowed_roots": [str(roots["agent"])],
                }
            ),
            "utf-8",
        )

        archive = self.base / "external-policy.zip"
        manifest = create_recovery_archive(self.live, archive, include_photos=True)

        self.assertEqual(manifest["data_classes"], [dict(item) for item in DATA_CLASS_POLICIES])
        self.assertEqual([item["role"] for item in manifest["locations"]], list(LOCATION_ROLES))
        locations = {item["role"]: item for item in manifest["locations"]}
        for role in ("vault", "files", "photos"):
            self.assertFalse(locations[role]["included"])
            self.assertEqual(locations[role]["policy"], "external-not-selected")
        self.assertEqual(locations["photos_watch"]["policy"], "source-only-excluded")
        self.assertEqual(locations["agent_allowed_roots"]["policy"], "workspace-content-excluded")
        self.assertEqual(locations["webdav"]["policy"], "not-implemented")
        self.assertEqual(locations["s3"]["policy"], "not-implemented")
        archived_paths = {item["path"] for item in manifest["files"]}
        for name in ("vault", "files", "photos", "watch", "agent"):
            self.assertNotIn(f"{name}-only.txt", archived_paths)

    def test_old_v1_manifest_without_policy_inventory_still_stages(self):
        archive = self._archive()
        old_v1 = self.base / "old-v1.zip"

        def mutate(entries):
            changed = []
            for name, content in entries:
                if name == "manifest.json":
                    manifest = json.loads(content)
                    manifest.pop("data_classes")
                    manifest["locations"] = manifest["locations"][:4]
                    content = json.dumps(manifest).encode()
                changed.append((name, content))
            return changed

        self._rewrite_archive(archive, old_v1, mutate)
        staged = stage_recovery_archive(old_v1, self.live)
        self.assertNotIn("data_classes", staged.manifest)

    def test_external_database_override_is_refused_instead_of_silently_omitted(self):
        external_db = self.base / "external.db"
        self._make_alles_db(external_db, versions=(1,))
        with (
            patch.dict(os.environ, {"ALLES_DB": str(external_db)}),
            self.assertRaisesRegex(RecoveryError, "outside ALLES_DATA"),
        ):
            create_recovery_archive(self.live, self.base / "unsafe.zip")
        self.assertFalse((self.base / "unsafe.zip").exists())

    def test_database_backed_attachment_ids_cannot_escape_staging(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE vault_attachments (id TEXT)")
            conn.execute("INSERT INTO vault_attachments VALUES ('../escape')")
            conn.commit()
        archive = self._archive()
        with self.assertRaisesRegex(RecoveryError, "invalid vault attachment id"):
            stage_recovery_archive(archive, self.live)
        self.assertFalse((self.base / "escape.enc").exists())

    def test_database_symlink_is_never_followed_during_backup(self):
        outside = self.base / "outside.db"
        self._make_alles_db(outside, versions=(1,))
        (self.live / "aide.db").unlink()
        (self.live / "aide.db").symlink_to(outside)
        with self.assertRaisesRegex(RecoveryError, "aide.db is missing"):
            create_recovery_archive(self.live, self.base / "symlink.zip")

    def test_stage_is_reverified_and_can_be_resealed_after_trusted_migrations(self):
        staged = stage_recovery_archive(self._archive(), self.live)
        self.assertEqual(verify_staged_recovery(self.live, staged.restore_id).state, "staged")
        note = staged.data_dir / "vault" / "Notes" / "hello.md"
        note.write_text("tampered", "utf-8")
        with self.assertRaisesRegex(RecoveryError, "checksum"):
            verify_staged_recovery(self.live, staged.restore_id)
        note.write_text("hello", "utf-8")

        from core.migrations.runner import discover

        with closing(sqlite3.connect(staged.data_dir / "aide.db")) as conn:
            for module in discover():
                conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations VALUES (?, ?, ?)",
                    (module.VERSION, module.NAME, "2026-01-01T00:00:00"),
                )
            conn.commit()
        prepared = refresh_prepared_recovery(self.live, staged.restore_id)
        self.assertEqual(prepared.state, "prepared")
        self.assertEqual(verify_staged_recovery(self.live, staged.restore_id).state, "prepared")

    def test_discard_only_accepts_real_restore_ids(self):
        staged = stage_recovery_archive(self._archive(), self.live)
        with self.assertRaises(RecoveryError):
            discard_staged_recovery(self.live, "../escape")
        self.assertTrue(staged.root.exists())
        discard_staged_recovery(self.live, staged.restore_id)
        self.assertFalse(staged.root.exists())


if __name__ == "__main__":
    unittest.main()
