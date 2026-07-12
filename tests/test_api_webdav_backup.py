import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import mock

import routes.backup as backup_routes
from services import secretstore, webdav_backup
from services.backup_recovery import staging_root
from services.recovery_crypto import MAGIC, recovery_key_path
from tests._client import ApiTest


class WebDAVBackupApiTest(ApiTest):
    VERIFIED_AT = "2026-07-12T12:34:56Z"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.data = self.base / "data"
        self.data.mkdir()
        self._make_db(self.data / "aide.db")
        (self.data / "settings.json").write_text("{}", "utf-8")

        self._old_data = backup_routes.DATA_DIR
        self._old_config = webdav_backup.CONFIG_PATH
        self._old_env = os.environ.get("ALLES_DATA")
        self._secret_state = (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            dict(secretstore._keys),
            secretstore._active_id,
        )
        backup_routes.DATA_DIR = self.data
        webdav_backup.CONFIG_PATH = self.data / webdav_backup.CONFIG_NAME
        os.environ["ALLES_DATA"] = str(self.data)
        secretstore._KEY_FILE = self.data / "secret.key"
        secretstore._key = None
        secretstore._key_path = None
        secretstore._keys = {}
        secretstore._active_id = ""

    def tearDown(self):
        backup_routes.DATA_DIR = self._old_data
        webdav_backup.CONFIG_PATH = self._old_config
        if self._old_env is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._old_env
        (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            secretstore._keys,
            secretstore._active_id,
        ) = self._secret_state
        self._tmp.cleanup()
        super().tearDown()

    @staticmethod
    def _make_db(path: Path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            connection.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            connection.execute(
                "INSERT INTO schema_migrations VALUES (1, 'baseline', '2026-01-01T00:00:00')"
            )
            connection.commit()

    def _configure(self, password="webdav-private"):
        with mock.patch.object(
            webdav_backup,
            "test_connection",
            return_value={"ok": True, "verified_at": self.VERIFIED_AT},
        ):
            response = self.client.put(
                "/api/backup/webdav",
                json={
                    "url": "https://dav.example.test/backups",
                    "username": "owner",
                    "password": password,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_config_is_sealed_masked_reusable_and_removable(self):
        response = self._configure()
        self.assertNotIn("webdav-private", response.text)
        self.assertTrue(response.json()["configured"])
        self.assertEqual(response.json()["last_verified_at"], self.VERIFIED_AT)

        raw = json.loads(webdav_backup.CONFIG_PATH.read_text("utf-8"))
        self.assertTrue(raw["password"].startswith("enc2:"))
        self.assertNotIn("webdav-private", webdav_backup.CONFIG_PATH.read_text("utf-8"))

        status = self.client.get("/api/backup/webdav")
        self.assertEqual(status.status_code, 200)
        self.assertNotIn("webdav-private", status.text)
        self.assertNotIn("password", status.json())

        with mock.patch.object(
            webdav_backup,
            "test_connection",
            return_value={"ok": True, "verified_at": self.VERIFIED_AT},
        ) as test:
            kept = self.client.put(
                "/api/backup/webdav",
                json={
                    "url": "https://dav.example.test/backups/",
                    "username": "owner",
                    "password": "",
                },
            )
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(test.call_args.args[0]["password"], "webdav-private")

        removed = self.client.delete("/api/backup/webdav")
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.json()["configured"])
        self.assertFalse(webdav_backup.CONFIG_PATH.exists())

    def test_corrupt_config_is_safe_and_can_be_removed(self):
        webdav_backup.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "url": "https://dav.example.test/backups/",
                    "username": "owner",
                    "password": "enc2:missing:private-ciphertext",
                }
            ),
            "utf-8",
        )
        status = self.client.get("/api/backup/webdav")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["error"], "webdav backup configuration could not be loaded")
        self.assertNotIn("private-ciphertext", status.text)

        removed = self.client.delete("/api/backup/webdav")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(removed.json()["configured"])
        self.assertFalse(webdav_backup.CONFIG_PATH.exists())

    def test_run_releases_route_lock_when_temp_setup_fails(self):
        with mock.patch.object(
            backup_routes.tempfile, "mkdtemp", side_effect=OSError("disk-private")
        ):
            failed = self.client.post("/api/backup/webdav/run")
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["code"], "backup_creation_failed")
        self.assertNotIn("disk-private", failed.text)

        def upload(path):
            payload = Path(path).read_bytes()
            return {
                "ok": True,
                "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "status_warning": "",
            }

        with mock.patch.object(webdav_backup, "upload_artifact", side_effect=upload):
            retried = self.client.post("/api/backup/webdav/run")
        self.assertEqual(retried.status_code, 200, retried.text)

    def test_verified_upload_warning_is_returned_as_success(self):
        result = {
            "ok": True,
            "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
            "size": 123,
            "sha256": "1" * 64,
            "status_warning": (
                "backup uploaded and verified, but local webdav status could not be saved"
            ),
        }
        with (
            mock.patch.object(backup_routes, "_create_encrypted_backup", return_value=None),
            mock.patch.object(webdav_backup, "upload_artifact", return_value=result),
        ):
            response = self.client.post("/api/backup/webdav/run")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status_warning"], result["status_warning"])

    def test_run_uploads_only_an_encrypted_artifact_and_cleans_temp(self):
        self._configure()
        captured = {}

        def upload(path):
            payload = Path(path).read_bytes()
            captured["payload"] = payload
            return {
                "ok": True,
                "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        with mock.patch.object(webdav_backup, "upload_artifact", side_effect=upload):
            response = self.client.post("/api/backup/webdav/run")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(captured["payload"].startswith(MAGIC))
        self.assertNotIn(b"webdav-private", captured["payload"])
        self.assertNotIn(recovery_key_path(self.data).read_bytes(), captured["payload"])
        self.assertEqual(list((staging_root(self.data) / "exports").glob("*")), [])

    def test_list_maps_only_service_validated_backup_fields(self):
        with mock.patch.object(
            webdav_backup,
            "list_artifacts",
            return_value=[
                {
                    "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                    "size": 123,
                    "modified": "Sun, 12 Jul 2026 12:00:00 GMT",
                    "etag": '"private-server-value"',
                }
            ],
        ):
            response = self.client.get("/api/backup/webdav/backups")

        self.assertEqual(
            response.json(),
            {
                "backups": [
                    {
                        "filename": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                        "bytes": 123,
                        "modified_at": "Sun, 12 Jul 2026 12:00:00 GMT",
                    }
                ]
            },
        )
        self.assertNotIn("etag", response.text)

    def test_remote_restore_uses_the_existing_staging_flow_and_separate_key(self):
        encrypted = self.client.get("/api/backup").content
        exported_key = self.client.get("/api/backup/recovery-key").content
        name = "alles-backup-20260712T120000Z-0123456789ab.alles-backup"

        def download(_name, destination, **_kwargs):
            Path(destination).write_bytes(encrypted)
            return {"ok": True, "name": name, "size": len(encrypted), "sha256": "0" * 64}

        with (
            mock.patch.object(
                webdav_backup,
                "list_artifacts",
                return_value=[{"name": name, "size": len(encrypted)}],
            ),
            mock.patch.object(webdav_backup, "download_artifact", side_effect=download),
        ):
            response = self.client.post(
                "/api/backup/webdav/restore",
                data={"filename": name},
                files={"recovery_key": ("alles-recovery-key.txt", exported_key, "text/plain")},
            )

        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["status"], "staged")
        self.assertTrue(body["apply_command"].startswith("alles restore apply "))
        staged = staging_root(self.data) / "staged" / body["restore_id"] / "data"
        self.assertTrue((staged / "aide.db").is_file())
        self.assertTrue((self.data / "aide.db").is_file())

        original_unlink = Path.unlink

        def fail_final_incoming_cleanup(path, *args, **kwargs):
            if path.parent.name == "incoming" and path.name.endswith(".alles-backup"):
                raise OSError("cleanup-private")
            return original_unlink(path, *args, **kwargs)

        with (
            mock.patch.object(
                webdav_backup,
                "list_artifacts",
                return_value=[{"name": name, "size": len(encrypted)}],
            ),
            mock.patch.object(webdav_backup, "download_artifact", side_effect=download),
            mock.patch.object(Path, "unlink", new=fail_final_incoming_cleanup),
        ):
            cleanup_response = self.client.post(
                "/api/backup/webdav/restore",
                data={"filename": name},
                files={"recovery_key": ("alles-recovery-key.txt", exported_key, "text/plain")},
            )
        self.assertEqual(cleanup_response.status_code, 202, cleanup_response.text)
        self.assertNotIn("cleanup-private", cleanup_response.text)

    def test_cross_site_webdav_backup_routes_fail_before_network_or_writes(self):
        headers = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        requests = (
            self.client.get("/api/backup/webdav", headers=headers),
            self.client.put(
                "/api/backup/webdav",
                headers=headers,
                json={"url": "https://dav.example", "username": "owner", "password": "secret"},
            ),
            self.client.delete("/api/backup/webdav", headers=headers),
            self.client.post("/api/backup/webdav/run", headers=headers),
            self.client.get("/api/backup/webdav/backups", headers=headers),
            self.client.post(
                "/api/backup/webdav/restore",
                headers=headers,
                data={"filename": "alles-backup-20260712T120000Z-0123456789ab.alles-backup"},
            ),
        )
        self.assertTrue(all(response.status_code == 403 for response in requests))


if __name__ == "__main__":
    import unittest

    unittest.main()
