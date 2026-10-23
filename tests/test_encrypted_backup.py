import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import encrypted_backup
from services.backup_recovery import ArchiveLimits


class EncryptedBackupTest(unittest.TestCase):
    def test_failed_encryption_removes_plaintext_and_partial_output(self):
        with tempfile.TemporaryDirectory(prefix="alles-encrypted-backup-") as tmp:
            root = Path(tmp) / "data"
            root.mkdir()
            artifact = Path(tmp) / "backup.alles-backup"
            limits = ArchiveLimits(max_archive_bytes=1024)
            key = b"k" * 32

            def create_archive(_root, plaintext, **_kwargs):
                plaintext.write_bytes(b"private plaintext")

            def fail_encryption(_plaintext, output, _key, **_kwargs):
                output.write_bytes(b"partial encrypted output")
                raise RuntimeError("encryption failed")

            with (
                mock.patch.object(
                    encrypted_backup, "load_or_create_recovery_key", return_value=key
                ),
                mock.patch.object(
                    encrypted_backup, "create_recovery_archive", side_effect=create_archive
                ) as archive_writer,
                mock.patch.object(
                    encrypted_backup, "encrypt_recovery_archive", side_effect=fail_encryption
                ) as encryptor,
            ):
                with self.assertRaisesRegex(RuntimeError, "encryption failed"):
                    encrypted_backup.create_encrypted_backup(
                        root, artifact, include_photos=True, limits=limits
                    )

            self.assertFalse(artifact.exists())
            self.assertEqual(sorted(Path(tmp).iterdir()), [root])
            self.assertEqual(archive_writer.call_args.kwargs["include_photos"], True)
            self.assertIs(archive_writer.call_args.kwargs["limits"], limits)
            self.assertEqual(archive_writer.call_args.kwargs["expected_recovery_key"], key)
            self.assertIs(encryptor.call_args.kwargs["limits"], limits)
