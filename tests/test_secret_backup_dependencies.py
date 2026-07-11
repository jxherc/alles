import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.backup_recovery import RecoveryError, _validate_database_dependencies


class SecretBackupDependencyTest(unittest.TestCase):
    def test_mcp_enc2_credentials_require_secret_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "aide.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE mcp_servers (id TEXT, env TEXT)")
                connection.execute(
                    "INSERT INTO mcp_servers VALUES ('one','enc2:0123456789abcdef:value')"
                )
            with self.assertRaisesRegex(RecoveryError, "missing secret.key"):
                _validate_database_dependencies(root, database)
            (root / "secret.key").write_text("present", "utf-8")
            _validate_database_dependencies(root, database)

    def test_encrypted_connector_config_requires_secret_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "aide.db"
            sqlite3.connect(database).close()
            (root / "caldav.json").write_text('{"password":"enc2:0123456789abcdef:value"}', "utf-8")
            with self.assertRaisesRegex(RecoveryError, "missing secret.key"):
                _validate_database_dependencies(root, database)


if __name__ == "__main__":
    unittest.main()
