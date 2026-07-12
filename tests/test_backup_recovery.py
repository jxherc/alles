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

    @staticmethod
    def _seal_for_root(root: Path, plaintext: str, purpose: str) -> str:
        from services import secretstore

        with (
            patch.object(secretstore, "_KEY_FILE", root / "secret.key"),
            patch.object(secretstore, "_key", None),
            patch.object(secretstore, "_key_path", None),
            patch.object(secretstore, "_keys", {}),
            patch.object(secretstore, "_active_id", ""),
        ):
            return secretstore.seal(plaintext, purpose)

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
        self.assertEqual(locations["webdav"]["policy"], "not-configured")
        self.assertEqual(locations["s3"]["policy"], "not-configured")
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

    def test_new_backup_rejects_plaintext_credentials_without_leaving_output(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE connections (id TEXT, token TEXT)")
            conn.execute("INSERT INTO connections VALUES ('one', 'plaintext-token')")
            conn.commit()
        archive = self.base / "plaintext-credential.zip"
        with self.assertRaisesRegex(RecoveryError, "not encrypted"):
            create_recovery_archive(self.live, archive)
        self.assertFalse(archive.exists())
        self.assertEqual(list(self.base.glob(".plaintext-credential.zip.*.partial")), [])

    def test_new_backup_rejects_unused_corrupt_keyring(self):
        (self.live / "secret.key").write_bytes(b"\xff\xfe\xfd")
        archive = self.base / "corrupt-keyring.zip"
        with self.assertRaisesRegex(RecoveryError, "secret key"):
            create_recovery_archive(self.live, archive)
        self.assertFalse(archive.exists())

    def test_live_key_rotation_after_validation_cannot_change_archive(self):
        from services import backup_recovery

        sealed = self._seal_for_root(
            self.live,
            "rotation-safe-token",
            "connections.token",
        )
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE connections (id TEXT, token TEXT)")
            conn.execute("INSERT INTO connections VALUES ('one', ?)", (sealed,))
            conn.commit()

        replacement_root = self.base / "replacement-key"
        replacement_root.mkdir()
        self._seal_for_root(replacement_root, "replacement", "connections.token")
        original_validate = backup_recovery._validate_database_dependencies

        def rotate_after_validation(data_dir, db_path, **kwargs):
            result = original_validate(data_dir, db_path, **kwargs)
            if kwargs.get("require_sealed"):
                os.replace(replacement_root / "secret.key", self.live / "secret.key")
            return result

        archive = self.base / "rotation-race.zip"
        with patch.object(
            backup_recovery,
            "_validate_database_dependencies",
            side_effect=rotate_after_validation,
        ):
            create_recovery_archive(self.live, archive)

        staged = stage_recovery_archive(archive, self.live)
        self.assertTrue((staged.data_dir / "secret.key").is_file())

    def test_database_snapshot_happens_before_live_dependency_collection(self):
        from services import backup_recovery

        original_collect = backup_recovery._collect_data_tree

        def add_late_attachment(*args, **kwargs):
            collected = original_collect(*args, **kwargs)
            attachment_dir = self.live / "vault_attachments"
            attachment_dir.mkdir()
            (attachment_dir / "late.enc").write_bytes(b"late encrypted blob")
            with closing(sqlite3.connect(self.live / "aide.db")) as conn:
                conn.execute("CREATE TABLE vault_attachments (id TEXT)")
                conn.execute("INSERT INTO vault_attachments VALUES ('late')")
                conn.commit()
            return collected

        archive = self.base / "late-attachment.zip"
        with patch.object(
            backup_recovery,
            "_collect_data_tree",
            side_effect=add_late_attachment,
        ):
            create_recovery_archive(self.live, archive)
        staged = stage_recovery_archive(archive, self.live)
        self.assertFalse((staged.data_dir / "vault_attachments" / "late.enc").exists())

    def test_location_plan_uses_the_frozen_settings_copy(self):
        from services import backup_recovery

        external = self.base / "external-vault"
        external.mkdir()
        original_snapshot = backup_recovery.snapshot_sqlite

        def change_settings_after_snapshot(source, destination):
            original_snapshot(source, destination)
            (self.live / "settings.json").write_text(
                json.dumps({"vault_dir": str(external)}),
                "utf-8",
            )

        archive = self.base / "settings-race.zip"
        with patch.object(
            backup_recovery,
            "snapshot_sqlite",
            side_effect=change_settings_after_snapshot,
        ):
            manifest = create_recovery_archive(self.live, archive)

        vault_location = next(item for item in manifest["locations"] if item["role"] == "vault")
        self.assertFalse(vault_location["included"])
        with zipfile.ZipFile(archive) as zf:
            captured = json.loads(zf.read("payload/data/settings.json"))
        self.assertEqual(captured["vault_dir"], str(external))
        stage_recovery_archive(archive, self.live)

    def test_webdav_policy_and_payload_use_only_the_frozen_config(self):
        from services import backup_recovery

        sealed = self._seal_for_root(
            self.live,
            "webdav-private",
            "backup.webdav.password",
        )
        configured = {
            "url": "https://dav.example.test/backups",
            "username": "owner",
            "password": sealed,
        }
        config_path = self.live / "webdav_backup.json"
        config_path.write_text(json.dumps(configured), "utf-8")
        original_freeze = backup_recovery._freeze_root_dependencies

        def change_live_config_after_freeze(*args, **kwargs):
            frozen = original_freeze(*args, **kwargs)
            config_path.write_text("{}", "utf-8")
            return frozen

        archive = self.base / "frozen-webdav.zip"
        with patch.object(
            backup_recovery,
            "_freeze_root_dependencies",
            side_effect=change_live_config_after_freeze,
        ):
            manifest = create_recovery_archive(self.live, archive)

        webdav = next(item for item in manifest["locations"] if item["role"] == "webdav")
        self.assertFalse(webdav["included"])
        self.assertEqual(webdav["policy"], "configured")
        with zipfile.ZipFile(archive) as zf:
            captured = json.loads(zf.read("payload/data/webdav_backup.json"))
        self.assertEqual(captured, configured)
        staged = stage_recovery_archive(archive, self.live)
        self.assertEqual(
            json.loads((staged.data_dir / "webdav_backup.json").read_text("utf-8")),
            configured,
        )

    def test_s3_policy_and_payload_use_only_the_frozen_config(self):
        from services import backup_recovery

        credentials = json.dumps(
            {
                "access_key_id": "access-private",
                "secret_access_key": "secret-private",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        sealed = self._seal_for_root(
            self.live,
            credentials,
            "backup.s3.credentials",
        )
        configured = {
            "endpoint": "https://objects.example.test",
            "region": "test-1",
            "bucket": "alles-backups",
            "credentials": sealed,
        }
        config_path = self.live / "s3_backup.json"
        config_path.write_text(json.dumps(configured), "utf-8")
        original_freeze = backup_recovery._freeze_root_dependencies

        def change_live_config_after_freeze(*args, **kwargs):
            frozen = original_freeze(*args, **kwargs)
            config_path.write_text("{}", "utf-8")
            return frozen

        archive = self.base / "frozen-s3.zip"
        with patch.object(
            backup_recovery,
            "_freeze_root_dependencies",
            side_effect=change_live_config_after_freeze,
        ):
            manifest = create_recovery_archive(self.live, archive)

        s3 = next(item for item in manifest["locations"] if item["role"] == "s3")
        self.assertFalse(s3["included"])
        self.assertEqual(s3["policy"], "configured")
        with zipfile.ZipFile(archive) as zf:
            captured_raw = zf.read("payload/data/s3_backup.json")
            captured = json.loads(captured_raw)
            self.assertNotIn("access-private", captured_raw.decode())
            self.assertNotIn("secret-private", captured_raw.decode())
        self.assertEqual(captured, configured)
        staged = stage_recovery_archive(archive, self.live)
        self.assertEqual(
            json.loads((staged.data_dir / "s3_backup.json").read_text("utf-8")),
            configured,
        )

    def test_new_backup_rejects_plaintext_and_wrong_purpose_s3_credentials(self):
        for failure in ("plaintext", "wrong-purpose"):
            with self.subTest(failure=failure):
                credentials = '{"secret_access_key":"private"}'
                if failure == "wrong-purpose":
                    credentials = self._seal_for_root(
                        self.live,
                        credentials,
                        "backup.webdav.password",
                    )
                (self.live / "s3_backup.json").write_text(
                    json.dumps(
                        {
                            "endpoint": "https://objects.example.test",
                            "region": "test-1",
                            "bucket": "alles-backups",
                            "credentials": credentials,
                        }
                    ),
                    "utf-8",
                )
                archive = self.base / f"s3-{failure}.zip"
                expected = "not encrypted" if failure == "plaintext" else "could not be decrypted"
                with self.assertRaisesRegex(RecoveryError, expected):
                    create_recovery_archive(self.live, archive)
                self.assertFalse(archive.exists())

    def test_expected_recovery_key_is_bound_to_the_frozen_copy(self):
        from services import backup_recovery
        from services.recovery_crypto import (
            load_or_create_recovery_key,
            recovery_key_document,
        )

        expected = load_or_create_recovery_key(self.live)
        original_snapshot = backup_recovery.snapshot_sqlite

        def replace_key_after_snapshot(source, destination):
            original_snapshot(source, destination)
            (self.live / "recovery.key").write_bytes(recovery_key_document(os.urandom(32)))

        archive = self.base / "recovery-key-race.zip"
        with (
            patch.object(
                backup_recovery,
                "snapshot_sqlite",
                side_effect=replace_key_after_snapshot,
            ),
            self.assertRaisesRegex(RecoveryError, "recovery key changed"),
        ):
            create_recovery_archive(
                self.live,
                archive,
                expected_recovery_key=expected,
            )
        self.assertFalse(archive.exists())

    def test_vault_rekey_waits_until_attachment_snapshot_is_coherent(self):
        import threading

        from services import backup_recovery
        from services.crypto import decrypt_bytes, encrypt_bytes, make_verifier
        from services.recovery_consistency import recovery_consistency_lock

        payload = b"passwords attachment recovery"
        old_verifier = make_verifier("old-master")
        new_verifier = make_verifier("new-master")
        attachment_dir = self.live / "vault_attachments"
        attachment_dir.mkdir()
        attachment = attachment_dir / "one.enc"
        attachment.write_bytes(encrypt_bytes("old-master", payload))
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE vaults (id TEXT, verifier TEXT)")
            conn.execute("INSERT INTO vaults VALUES ('default', ?)", (old_verifier,))
            conn.execute("CREATE TABLE vault_attachments (id TEXT)")
            conn.execute("INSERT INTO vault_attachments VALUES ('one')")
            conn.commit()

        begin_rekey = threading.Event()
        rekey_started = threading.Event()
        rekey_finished = threading.Event()

        def rekey():
            begin_rekey.wait(2)
            rekey_started.set()
            with recovery_consistency_lock:
                attachment.write_bytes(encrypt_bytes("new-master", payload))
                with closing(sqlite3.connect(self.live / "aide.db")) as conn:
                    conn.execute(
                        "UPDATE vaults SET verifier = ? WHERE id = 'default'",
                        (new_verifier,),
                    )
                    conn.commit()
            rekey_finished.set()

        worker = threading.Thread(target=rekey)
        worker.start()
        original_freeze = backup_recovery._freeze_backup_source
        blocked = []

        def freeze_and_release_rekey(source, destination, **kwargs):
            if source.name == "one.enc" and source.parent.name == "vault_attachments":
                begin_rekey.set()
                self.assertTrue(rekey_started.wait(1))
                blocked.append(not rekey_finished.wait(0.1))
            return original_freeze(source, destination, **kwargs)

        archive = self.base / "vault-rekey-race.zip"
        with patch.object(
            backup_recovery,
            "_freeze_backup_source",
            side_effect=freeze_and_release_rekey,
        ):
            create_recovery_archive(self.live, archive)
        worker.join(5)
        self.assertEqual(blocked, [True])
        self.assertFalse(worker.is_alive())

        staged = stage_recovery_archive(archive, self.live)
        with closing(sqlite3.connect(staged.data_dir / "aide.db")) as conn:
            self.assertEqual(
                conn.execute("SELECT verifier FROM vaults WHERE id = 'default'").fetchone()[0],
                old_verifier,
            )
        self.assertEqual(
            decrypt_bytes(
                "old-master",
                (staged.data_dir / "vault_attachments" / "one.enc").read_bytes(),
            ),
            payload,
        )
        self.assertEqual(decrypt_bytes("new-master", attachment.read_bytes()), payload)

    def test_legacy_plaintext_credential_archive_can_still_be_staged(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE connections (id TEXT, token TEXT)")
            conn.execute("INSERT INTO connections VALUES ('one', 'legacy-token')")
            conn.commit()
        archive = self.base / "legacy-plaintext.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.write(self.live / "settings.json", "settings.json")

        staged = stage_recovery_archive(archive, self.live)
        with closing(sqlite3.connect(staged.data_dir / "aide.db")) as conn:
            self.assertEqual(
                conn.execute("SELECT token FROM connections WHERE id = 'one'").fetchone()[0],
                "legacy-token",
            )

    def test_legacy_plaintext_webdav_config_can_still_be_staged(self):
        config = {
            "url": "https://dav.example.test/backups",
            "username": "owner",
            "password": "legacy-webdav-password",
        }
        config_path = self.live / "webdav_backup.json"
        config_path.write_text(json.dumps(config), "utf-8")
        archive = self.base / "legacy-webdav.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.write(config_path, "webdav_backup.json")

        staged = stage_recovery_archive(archive, self.live)
        self.assertEqual(
            json.loads((staged.data_dir / "webdav_backup.json").read_text("utf-8")),
            config,
        )
        webdav = next(item for item in staged.manifest["locations"] if item["role"] == "webdav")
        self.assertEqual(webdav["policy"], "configured")

    def test_legacy_plaintext_s3_config_can_still_be_staged(self):
        config = {
            "endpoint": "https://objects.example.test",
            "region": "test-1",
            "bucket": "alles-backups",
            "credentials": '{"secret_access_key":"legacy-private"}',
        }
        config_path = self.live / "s3_backup.json"
        config_path.write_text(json.dumps(config), "utf-8")
        archive = self.base / "legacy-s3.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.live / "aide.db", "aide.db")
            zf.write(config_path, "s3_backup.json")

        staged = stage_recovery_archive(archive, self.live)
        self.assertEqual(
            json.loads((staged.data_dir / "s3_backup.json").read_text("utf-8")),
            config,
        )
        s3 = next(item for item in staged.manifest["locations"] if item["role"] == "s3")
        self.assertEqual(s3["policy"], "configured")

    def test_database_backed_attachment_ids_cannot_escape_staging(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE vault_attachments (id TEXT)")
            conn.execute("INSERT INTO vault_attachments VALUES ('../escape')")
            conn.commit()
        archive = self.base / "invalid-attachment.zip"
        with self.assertRaisesRegex(RecoveryError, "invalid vault attachment id"):
            create_recovery_archive(self.live, archive)
        self.assertFalse(archive.exists())

        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.live / "aide.db", "aide.db")
        with self.assertRaisesRegex(RecoveryError, "invalid vault attachment id"):
            stage_recovery_archive(archive, self.live)
        self.assertFalse((self.base / "escape.enc").exists())

    def test_symlinked_push_key_is_rejected_before_backup_publish(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE push_subscriptions (id TEXT)")
            conn.execute("INSERT INTO push_subscriptions VALUES ('one')")
            conn.commit()
        outside = self.base / "outside-vapid.pem"
        outside.write_text("synthetic", "utf-8")
        (self.live / "vapid.pem").symlink_to(outside)
        archive = self.base / "symlinked-vapid.zip"
        with self.assertRaisesRegex(RecoveryError, "vapid.pem|link"):
            create_recovery_archive(self.live, archive)
        self.assertFalse(archive.exists())

    def test_symlinked_vault_attachment_is_rejected_before_backup_publish(self):
        with closing(sqlite3.connect(self.live / "aide.db")) as conn:
            conn.execute("CREATE TABLE vault_attachments (id TEXT)")
            conn.execute("INSERT INTO vault_attachments VALUES ('one')")
            conn.commit()
        attachment_dir = self.live / "vault_attachments"
        attachment_dir.mkdir()
        outside = self.base / "outside.enc"
        outside.write_bytes(b"synthetic")
        (attachment_dir / "one.enc").symlink_to(outside)
        archive = self.base / "symlinked-attachment.zip"
        with self.assertRaisesRegex(RecoveryError, "vault attachment|link"):
            create_recovery_archive(self.live, archive)
        self.assertFalse(archive.exists())

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
