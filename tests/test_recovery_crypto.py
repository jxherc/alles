import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import cli
from services.backup_recovery import (
    RecoveryError,
    create_recovery_archive,
    staging_root,
    verify_staged_recovery,
)
from services.recovery_crypto import (
    decrypt_recovery_container,
    encrypt_recovery_archive,
    is_encrypted_recovery,
    load_or_create_recovery_key,
    parse_recovery_key,
    recovery_key_document,
    recovery_key_path,
)


class RecoveryCryptoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / "data"
        self.data.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_recovery_key_is_stable_exportable_and_private(self):
        first = load_or_create_recovery_key(self.data)
        second = load_or_create_recovery_key(self.data)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertEqual(parse_recovery_key(recovery_key_document(first)), first)
        self.assertEqual(recovery_key_path(self.data).read_bytes(), recovery_key_document(first))
        if os.name != "nt":
            self.assertEqual(recovery_key_path(self.data).stat().st_mode & 0o777, 0o600)

    def test_streaming_encryption_roundtrip_preserves_large_archive_bytes(self):
        source = self.base / "plain.zip"
        source.write_bytes(os.urandom(2 * 1024 * 1024 + 137))
        encrypted = self.base / "backup.alles-backup"
        restored = self.base / "restored.zip"
        key = load_or_create_recovery_key(self.data)

        encrypt_recovery_archive(source, encrypted, key)
        self.assertTrue(is_encrypted_recovery(encrypted))
        self.assertNotIn(source.read_bytes()[:64], encrypted.read_bytes())
        decrypt_recovery_container(encrypted, restored, key)

        self.assertEqual(restored.read_bytes(), source.read_bytes())

    def test_wrong_key_tamper_and_truncation_fail_without_output(self):
        source = self.base / "plain.zip"
        source.write_bytes(b"private backup bytes" * 100)
        encrypted = self.base / "backup.alles-backup"
        key = load_or_create_recovery_key(self.data)
        encrypt_recovery_archive(source, encrypted, key)

        wrong_output = self.base / "wrong.zip"
        with self.assertRaises(RecoveryError):
            decrypt_recovery_container(encrypted, wrong_output, os.urandom(32))
        self.assertFalse(wrong_output.exists())

        tampered = self.base / "tampered.alles-backup"
        content = bytearray(encrypted.read_bytes())
        content[len(content) // 2] ^= 0x01
        tampered.write_bytes(content)
        tampered_output = self.base / "tampered.zip"
        with self.assertRaisesRegex(RecoveryError, "authentication"):
            decrypt_recovery_container(tampered, tampered_output, key)
        self.assertFalse(tampered_output.exists())

        truncated = self.base / "truncated.alles-backup"
        truncated.write_bytes(encrypted.read_bytes()[:-8])
        truncated_output = self.base / "truncated.zip"
        with self.assertRaises(RecoveryError):
            decrypt_recovery_container(truncated, truncated_output, key)
        self.assertFalse(truncated_output.exists())

    def test_key_document_rejects_malformed_or_short_keys(self):
        for value in (b"", b"not-a-key", b"ALLES-RECOVERY-KEY-V1\nshort\n"):
            with self.subTest(value=value), self.assertRaises(RecoveryError):
                parse_recovery_key(value)

    def test_cli_can_stage_encrypted_backup_using_only_the_exported_key(self):
        with closing(sqlite3.connect(self.data / "aide.db")) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.commit()
        (self.data / "vault").mkdir()
        (self.data / "files").mkdir()
        key = load_or_create_recovery_key(self.data)
        plain = self.base / "portable.zip"
        encrypted = self.base / "portable.alles-backup"
        create_recovery_archive(self.data, plain)
        encrypt_recovery_archive(plain, encrypted, key)
        exported_key = self.base / "exported-key.txt"
        exported_key.write_bytes(recovery_key_document(key))
        clean_data = self.base / "clean-install-data"

        with (
            mock.patch.object(cli, "_runtime_dir", return_value=clean_data),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_restore(("stage", str(encrypted), "--key", str(exported_key)))

        self.assertTrue(result)
        stages = list((staging_root(clean_data) / "staged").iterdir())
        self.assertEqual(len(stages), 1)
        verify_staged_recovery(clean_data, stages[0].name)


if __name__ == "__main__":
    unittest.main()
