import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import mock

import routes.backup as backup_routes
from services import s3_backup, secretstore
from services.backup_recovery import staging_root
from services.recovery_crypto import MAGIC, recovery_key_path
from tests._client import ApiTest


class S3BackupApiTest(ApiTest):
    VERIFIED_AT = "2026-07-12T12:34:56Z"
    COMPLETED_AT = "2026-07-12T12:35:00Z"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.data = self.base / "data"
        self.data.mkdir()
        self._make_db(self.data / "aide.db")
        (self.data / "settings.json").write_text("{}", "utf-8")

        self._old_data = backup_routes.DATA_DIR
        self._old_config = s3_backup.CONFIG_PATH
        self._old_env = os.environ.get("ALLES_DATA")
        self._secret_state = (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            dict(secretstore._keys),
            secretstore._active_id,
        )
        backup_routes.DATA_DIR = self.data
        s3_backup.CONFIG_PATH = self.data / s3_backup.CONFIG_NAME
        os.environ["ALLES_DATA"] = str(self.data)
        secretstore._KEY_FILE = self.data / "secret.key"
        secretstore._key = None
        secretstore._key_path = None
        secretstore._keys = {}
        secretstore._active_id = ""

    def tearDown(self):
        backup_routes.DATA_DIR = self._old_data
        s3_backup.CONFIG_PATH = self._old_config
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

    @staticmethod
    def _body(**overrides):
        body = {
            "endpoint": "https://objects.example.test",
            "region": "us-east-1",
            "bucket": "alles-backups",
            "prefix": "private/alles",
            "addressing_style": "path",
            "access_key_id": "backup-owner",
            "secret_access_key": "s3-private",
        }
        body.update(overrides)
        return body

    def _configure(self):
        with mock.patch.object(
            s3_backup,
            "test_connection",
            return_value={"ok": True, "verified_at": self.VERIFIED_AT},
        ):
            response = self.client.put("/api/backup/s3", json=self._body())
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_config_is_sealed_masked_reusable_and_removable(self):
        response = self._configure()
        self.assertTrue(response.json()["configured"])
        self.assertTrue(response.json()["credentials_set"])
        self.assertEqual(response.json()["last_verified_at"], self.VERIFIED_AT)
        self.assertNotIn("backup-owner", response.text)
        self.assertNotIn("s3-private", response.text)

        raw_text = s3_backup.CONFIG_PATH.read_text("utf-8")
        raw = json.loads(raw_text)
        self.assertTrue(raw["credentials"].startswith("enc2:"))
        self.assertNotIn("backup-owner", raw_text)
        self.assertNotIn("s3-private", raw_text)

        status = self.client.get("/api/backup/s3")
        self.assertEqual(status.status_code, 200)
        self.assertNotIn("credentials", status.json())
        self.assertNotIn("access_key", status.text)
        self.assertNotIn("secret_access", status.text)

        with mock.patch.object(
            s3_backup,
            "test_connection",
            return_value={"ok": True, "verified_at": self.VERIFIED_AT},
        ) as test:
            kept = self.client.put(
                "/api/backup/s3",
                json=self._body(access_key_id="", secret_access_key=""),
            )
        self.assertEqual(kept.status_code, 200, kept.text)
        credentials = json.loads(test.call_args.args[0]["credentials"])
        self.assertEqual(credentials["access_key_id"], "backup-owner")
        self.assertEqual(credentials["secret_access_key"], "s3-private")

        changed = self.client.put(
            "/api/backup/s3",
            json=self._body(prefix="another", access_key_id="", secret_access_key=""),
        )
        self.assertEqual(changed.status_code, 400, changed.text)

        removed = self.client.delete("/api/backup/s3")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(removed.json()["configured"])
        self.assertFalse(s3_backup.CONFIG_PATH.exists())

    def test_corrupt_config_is_safe_and_can_be_removed(self):
        s3_backup.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "endpoint": "https://objects.example.test",
                    "region": "us-east-1",
                    "bucket": "alles-backups",
                    "prefix": "private/alles",
                    "addressing_style": "path",
                    "credentials": "enc2:missing:private-ciphertext",
                }
            ),
            "utf-8",
        )
        status = self.client.get("/api/backup/s3")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["error"], "s3 backup configuration could not be loaded")
        self.assertNotIn("private-ciphertext", status.text)

        removed = self.client.delete("/api/backup/s3")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(removed.json()["configured"])
        self.assertFalse(s3_backup.CONFIG_PATH.exists())

    def test_run_releases_route_lock_when_temp_setup_fails(self):
        with mock.patch.object(
            backup_routes.tempfile, "mkdtemp", side_effect=OSError("disk-private")
        ):
            failed = self.client.post("/api/backup/s3/run")
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
                "completed_at": self.COMPLETED_AT,
                "status_warning": "",
            }

        with mock.patch.object(s3_backup, "upload_artifact", side_effect=upload):
            retried = self.client.post("/api/backup/s3/run")
        self.assertEqual(retried.status_code, 200, retried.text)

    def test_verified_upload_time_and_warning_are_returned_as_success(self):
        result = {
            "ok": True,
            "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
            "size": 123,
            "sha256": "1" * 64,
            "completed_at": self.COMPLETED_AT,
            "status_warning": "backup verified, but local s3 status could not be saved",
        }
        with (
            mock.patch.object(backup_routes, "_create_encrypted_backup", return_value=None),
            mock.patch.object(s3_backup, "upload_artifact", return_value=result),
        ):
            response = self.client.post("/api/backup/s3/run")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["completed_at"], self.COMPLETED_AT)
        self.assertEqual(response.json()["last_backup_at"], self.COMPLETED_AT)
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
                "completed_at": self.COMPLETED_AT,
                "status_warning": "",
            }

        with mock.patch.object(s3_backup, "upload_artifact", side_effect=upload):
            response = self.client.post("/api/backup/s3/run")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(captured["payload"].startswith(MAGIC))
        self.assertNotIn(b"backup-owner", captured["payload"])
        self.assertNotIn(b"s3-private", captured["payload"])
        self.assertNotIn(recovery_key_path(self.data).read_bytes(), captured["payload"])
        self.assertEqual(list((staging_root(self.data) / "exports").glob("*")), [])

    def test_list_maps_only_service_validated_backup_fields(self):
        with mock.patch.object(
            s3_backup,
            "list_artifacts",
            return_value=[
                {
                    "name": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                    "size": 123,
                    "modified": "2026-07-12T12:00:00Z",
                    "etag": '"private-server-value"',
                }
            ],
        ):
            response = self.client.get("/api/backup/s3/backups")

        self.assertEqual(
            response.json(),
            {
                "backups": [
                    {
                        "filename": "alles-backup-20260712T120000Z-0123456789ab.alles-backup",
                        "bytes": 123,
                        "modified_at": "2026-07-12T12:00:00Z",
                    }
                ]
            },
        )
        self.assertNotIn("etag", response.text)

    def test_remote_restore_uses_existing_staging_flow_and_separate_key(self):
        encrypted = self.client.get("/api/backup").content
        exported_key = self.client.get("/api/backup/recovery-key").content
        name = "alles-backup-20260712T120000Z-0123456789ab.alles-backup"

        def download(_name, destination, **_kwargs):
            Path(destination).write_bytes(encrypted)
            return {"ok": True, "name": name, "size": len(encrypted), "sha256": "0" * 64}

        with (
            mock.patch.object(
                s3_backup,
                "list_artifacts",
                return_value=[{"name": name, "size": len(encrypted)}],
            ),
            mock.patch.object(s3_backup, "download_artifact", side_effect=download),
        ):
            response = self.client.post(
                "/api/backup/s3/restore",
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
                s3_backup,
                "list_artifacts",
                return_value=[{"name": name, "size": len(encrypted)}],
            ),
            mock.patch.object(s3_backup, "download_artifact", side_effect=download),
            mock.patch.object(Path, "unlink", new=fail_final_incoming_cleanup),
        ):
            cleanup_response = self.client.post(
                "/api/backup/s3/restore",
                data={"filename": name},
                files={"recovery_key": ("alles-recovery-key.txt", exported_key, "text/plain")},
            )
        self.assertEqual(cleanup_response.status_code, 202, cleanup_response.text)
        self.assertNotIn("cleanup-private", cleanup_response.text)

    def test_cross_site_s3_backup_routes_fail_before_network_or_writes(self):
        headers = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        requests = (
            self.client.get("/api/backup/s3", headers=headers),
            self.client.put("/api/backup/s3", headers=headers, json=self._body()),
            self.client.delete("/api/backup/s3", headers=headers),
            self.client.post("/api/backup/s3/run", headers=headers),
            self.client.get("/api/backup/s3/backups", headers=headers),
            self.client.post(
                "/api/backup/s3/restore",
                headers=headers,
                data={"filename": "alles-backup-20260712T120000Z-0123456789ab.alles-backup"},
            ),
        )
        self.assertTrue(all(response.status_code == 403 for response in requests))


if __name__ == "__main__":
    import unittest

    unittest.main()
