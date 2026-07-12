import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

from core.credential_inventory import (
    CONFIG_CREDENTIAL_FIELDS,
    DATABASE_CREDENTIAL_FIELDS,
    SETTING_CREDENTIAL_KEYS,
)
from services import secretstore
from services.backup_recovery import (
    RecoveryError,
    _validate_database_dependencies,
)


@contextmanager
def _isolated_secret_store(root: Path):
    original = (
        secretstore._KEY_FILE,
        secretstore._key,
        secretstore._key_path,
        dict(secretstore._keys),
        secretstore._active_id,
    )
    secretstore._KEY_FILE = root / "secret.key"
    secretstore._key = None
    secretstore._key_path = None
    secretstore._keys = {}
    secretstore._active_id = ""
    try:
        yield
    finally:
        (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            secretstore._keys,
            secretstore._active_id,
        ) = original


class SecretBackupDependencyTest(unittest.TestCase):
    @staticmethod
    def _database(root: Path, values=()) -> Path:
        database = root / "aide.db"
        grouped: dict[str, list[tuple[str, str]]] = {}
        for table, column, value in values:
            grouped.setdefault(table, []).append((column, value))
        with closing(sqlite3.connect(database)) as connection:
            for table, fields in grouped.items():
                columns = ",".join(f"{column} TEXT" for column, _ in fields)
                connection.execute(f"CREATE TABLE {table} (id TEXT,{columns})")
                names = ",".join(["id", *(column for column, _ in fields)])
                placeholders = ",".join("?" for _ in range(len(fields) + 1))
                connection.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
                    ["one", *(value for _, value in fields)],
                )
            connection.commit()
        return database

    def test_every_known_credential_authenticates_with_its_exact_purpose(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with _isolated_secret_store(root):
                database_values = [
                    (table, column, secretstore.seal(f"{table}-{column}", purpose))
                    for table, column, purpose in DATABASE_CREDENTIAL_FIELDS
                ]
                settings = {
                    key: secretstore.seal(f"settings-{key}", f"settings.{key}")
                    for key in SETTING_CREDENTIAL_KEYS
                }
                (root / "settings.json").write_text(json.dumps(settings), "utf-8")
                for name, key, purpose in CONFIG_CREDENTIAL_FIELDS:
                    sealed = secretstore.seal(f"{name}-password", purpose)
                    (root / name).write_text(json.dumps({key: sealed}), "utf-8")
                (root / "vapid.pem").write_text("synthetic-test-key", "utf-8")
                database = self._database(root, database_values)

            keyring_before = (root / "secret.key").read_bytes()
            _validate_database_dependencies(root, database, require_sealed=True)
            self.assertEqual((root / "secret.key").read_bytes(), keyring_before)

    def test_creation_rejects_plaintext_but_legacy_restore_can_stage_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = self._database(
                root,
                [("connections", "token", "legacy-plaintext-token")],
            )
            with self.assertRaisesRegex(RecoveryError, "not encrypted"):
                _validate_database_dependencies(root, database, require_sealed=True)
            _validate_database_dependencies(root, database, require_sealed=False)

    def test_encrypted_credentials_reject_missing_or_symlinked_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = self._database(
                root,
                [("connections", "token", "enc2:0123456789abcdef:value")],
            )
            with self.assertRaisesRegex(RecoveryError, "missing secret.key"):
                _validate_database_dependencies(root, database)

            outside = root / "outside.key"
            outside.write_text("not-a-key", "utf-8")
            (root / "secret.key").symlink_to(outside)
            with self.assertRaisesRegex(RecoveryError, "secret.key.*link"):
                _validate_database_dependencies(root, database)

    def test_symlinked_credential_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = self._database(root)
            outside = root / "outside-settings.json"
            outside.write_text('{"openai_api_key":"plaintext"}', "utf-8")
            (root / "settings.json").symlink_to(outside)
            with self.assertRaisesRegex(RecoveryError, "credential config.*link"):
                _validate_database_dependencies(root, database, require_sealed=True)

    def test_corrupt_or_wrong_keyring_is_rejected(self):
        for failure in ("corrupt", "wrong"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with _isolated_secret_store(root):
                    sealed = secretstore.seal("private-token", "connections.token")
                    database = self._database(root, [("connections", "token", sealed)])
                    if failure == "corrupt":
                        (root / "secret.key").write_text("not-a-key", "utf-8")
                    else:
                        other = root / "other"
                        other.mkdir()
                        with _isolated_secret_store(other):
                            secretstore.seal("different", "connections.token")
                        os.replace(other / "secret.key", root / "secret.key")

                with self.assertRaisesRegex(RecoveryError, "secret.key|unavailable key"):
                    _validate_database_dependencies(root, database)

    def test_creation_validates_an_existing_keyring_without_credentials(self):
        for bad_key in (b"not-a-key", b"\xff\xfe\xfd"):
            with self.subTest(bad_key=bad_key), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                database = self._database(root)
                (root / "secret.key").write_bytes(bad_key)
                with self.assertRaisesRegex(RecoveryError, "secret key|secret.key"):
                    _validate_database_dependencies(root, database, require_sealed=True)

    def test_tampered_ciphertext_and_wrong_purpose_are_rejected(self):
        for failure in ("tampered", "wrong-purpose"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with _isolated_secret_store(root):
                    purpose = "wrong.field" if failure == "wrong-purpose" else "connections.token"
                    sealed = secretstore.seal("private-token", purpose)
                    if failure == "tampered":
                        sealed = sealed[:-1] + ("A" if sealed[-1] != "A" else "B")
                    database = self._database(root, [("connections", "token", sealed)])

                with self.assertRaisesRegex(RecoveryError, "could not be decrypted|invalid"):
                    _validate_database_dependencies(root, database)

    def test_webdav_password_is_bound_to_its_exact_purpose(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with _isolated_secret_store(root):
                sealed = secretstore.seal("webdav-private", "caldav.password")
                (root / "webdav_backup.json").write_text(
                    json.dumps(
                        {
                            "url": "https://dav.example.test/backups",
                            "username": "owner",
                            "password": sealed,
                        }
                    ),
                    "utf-8",
                )
                database = self._database(root)

            with self.assertRaisesRegex(RecoveryError, "could not be decrypted"):
                _validate_database_dependencies(root, database, require_sealed=True)


if __name__ == "__main__":
    unittest.main()
