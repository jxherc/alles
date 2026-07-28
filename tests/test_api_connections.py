import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

from sqlalchemy import text

import core.settings as settings
from core.database import Connection, McpServer
from services import caldav_sync, carddav_sync, s3_backup, secretstore
from services.config_secrets import load_secret_config, save_secret_config
from tests._client import ApiTest


class ConnectionsApiTest(ApiTest):
    @staticmethod
    def _reload_configured_secretstore():
        secretstore._key = None
        secretstore._key_path = None
        secretstore._keys = {}
        secretstore._active_id = ""
        secretstore._load_keyring()

    def setUp(self):
        super().setUp()
        self._secret_state = (
            secretstore._key,
            secretstore._key_path,
            dict(secretstore._keys),
            secretstore._active_id,
        )
        self._reload_configured_secretstore()
        self.addCleanup(self._restore_secretstore)

    def _restore_secretstore(self):
        (
            secretstore._key,
            secretstore._key_path,
            secretstore._keys,
            secretstore._active_id,
        ) = self._secret_state

    def test_startup_migrates_plaintext_s3_credentials(self):
        from core import database

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "s3_backup.json"
            credentials = json.dumps(
                {
                    "access_key_id": "access-private",
                    "secret_access_key": "secret-private",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            config_path.write_text(
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
            original_secret_state = (
                secretstore._key,
                secretstore._key_path,
                dict(secretstore._keys),
                secretstore._active_id,
            )
            try:
                with (
                    mock.patch.object(secretstore, "_KEY_FILE", root / "secret.key"),
                    mock.patch.object(s3_backup, "CONFIG_PATH", config_path),
                    mock.patch("core.settings.migrate_setting_secrets", return_value=0),
                    mock.patch("services.caldav_sync.migrate_cfg_secrets", return_value=0),
                    mock.patch("services.carddav_sync.migrate_cfg_secrets", return_value=0),
                    mock.patch("services.webdav_backup.migrate_config", return_value=0),
                ):
                    secretstore._key = None
                    secretstore._key_path = None
                    secretstore._keys = {}
                    secretstore._active_id = ""
                    database.init_db()
                    stored = json.loads(config_path.read_text("utf-8"))
                    self.assertTrue(stored["credentials"].startswith("enc2:"))
                    self.assertNotIn("access-private", config_path.read_text("utf-8"))
                    self.assertNotIn("secret-private", config_path.read_text("utf-8"))
                    self.assertEqual(s3_backup.load_config()["credentials"], credentials)
            finally:
                (
                    secretstore._key,
                    secretstore._key_path,
                    secretstore._keys,
                    secretstore._active_id,
                ) = original_secret_state

    def test_tokens_and_sensitive_metadata_are_encrypted_and_masked(self):
        response = self.client.post(
            "/api/connections",
            json={
                "service": "github",
                "token": "github-super-secret-token",
                "meta": {
                    "username": "octocat",
                    "client_secret": "meta-secret",
                    "base_url": "https://user:pass@example.test/api?token=query-secret",
                },
            },
        )
        self.assertEqual(response.status_code, 200)

        listed = self.client.get("/api/connections").json()[0]
        self.assertNotIn("github-super-secret-token", str(listed))
        self.assertEqual(listed["meta"]["client_secret"], "***")
        self.assertNotIn("pass", listed["meta"]["base_url"])
        self.assertNotIn("query-secret", listed["meta"]["base_url"])

        with self.eng.connect() as connection:
            token, meta = connection.execute(
                text("SELECT token, meta FROM connections WHERE service = 'github'")
            ).one()
        self.assertTrue(token.startswith("enc2:"))
        self.assertTrue(meta.startswith("enc2:"))
        self.assertNotIn("github-super-secret-token", token)
        self.assertNotIn("meta-secret", meta)

    def test_rotation_reseals_every_store_and_retires_old_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            patches = (
                mock.patch.object(secretstore, "_KEY_FILE", root / "secret.key"),
                mock.patch.object(settings, "_SETTINGS_FILE", root / "settings.json"),
                mock.patch.object(caldav_sync, "CFG_PATH", root / "caldav.json"),
                mock.patch.object(carddav_sync, "_cfg_path", lambda: root / "carddav.json"),
            )
            for patch in patches:
                patch.start()
            self.addCleanup(lambda: [patch.stop() for patch in reversed(patches)])
            secretstore._key = None
            secretstore._key_path = None
            secretstore._keys = {}
            secretstore._active_id = ""

            db = self.db()
            db.add(
                Connection(service="github", token="connection-private", meta='{"token":"meta"}')
            )
            db.add(
                McpServer(
                    name="remote",
                    transport="sse",
                    url="https://example.test/mcp?token=private",
                    args='["--token","private"]',
                    env='{"GITHUB_TOKEN":"private"}',
                    headers='{"Authorization":"Bearer private"}',
                )
            )
            db.commit()
            db.close()
            settings.save_settings({"openai_api_key": "settings-private"})
            caldav_sync.save_cfg(
                {"url": "https://dav", "username": "me", "password": "cal-private"}
            )
            carddav_sync.save_cfg(
                {"url": "https://dav", "username": "me", "password": "card-private"}
            )
            webdav_path = root / "webdav_backup.json"
            save_secret_config(
                webdav_path,
                {
                    "url": "https://dav.example.test/backups",
                    "username": "me",
                    "password": "webdav-private",
                },
                "backup.webdav.password",
            )
            s3_path = root / "s3_backup.json"
            s3_credentials = json.dumps(
                {
                    "access_key_id": "access-private",
                    "secret_access_key": "secret-private",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            save_secret_config(
                s3_path,
                {
                    "endpoint": "https://objects.example.test",
                    "region": "test-1",
                    "bucket": "alles-backups",
                    "credentials": s3_credentials,
                },
                "backup.s3.credentials",
                field="credentials",
            )
            old_id = secretstore.active_key_id()

            response = self.client.post("/api/connections/rotate-key")
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertNotEqual(body["active_key"], old_id)
            keyring = json.loads((root / "secret.key").read_text("utf-8"))
            self.assertEqual(set(keyring["keys"]), {body["active_key"]})
            self.assertEqual(settings.load_settings()["openai_api_key"], "settings-private")
            self.assertEqual(caldav_sync.load_cfg()["password"], "cal-private")
            self.assertEqual(carddav_sync.load_cfg()["password"], "card-private")
            self.assertEqual(
                load_secret_config(webdav_path, "backup.webdav.password")["password"],
                "webdav-private",
            )
            self.assertEqual(
                load_secret_config(
                    s3_path,
                    "backup.s3.credentials",
                    field="credentials",
                )["credentials"],
                s3_credentials,
            )
            with self.eng.connect() as connection:
                stored = connection.execute(text("SELECT token,meta FROM connections")).one()
                mcp = connection.execute(text("SELECT args,url,env,headers FROM mcp_servers")).one()
            prefix = f"enc2:{body['active_key']}:"
            self.assertTrue(all(value.startswith(prefix) for value in (*stored, *mcp)))
            webdav_raw = json.loads(webdav_path.read_text("utf-8"))["password"]
            self.assertTrue(webdav_raw.startswith(prefix))
            s3_raw = json.loads(s3_path.read_text("utf-8"))
            self.assertTrue(s3_raw["credentials"].startswith(prefix))
            self.assertNotIn("access-private", s3_path.read_text("utf-8"))
            self.assertNotIn("secret-private", s3_path.read_text("utf-8"))

    def test_config_secret_helper_seals_only_the_declared_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "s3_backup.json"
            with mock.patch.object(secretstore, "_KEY_FILE", root / "secret.key"):
                secretstore._key = None
                secretstore._key_path = None
                secretstore._keys = {}
                secretstore._active_id = ""
                with self.assertRaisesRegex(ValueError, "must be a string"):
                    save_secret_config(
                        path,
                        {
                            "endpoint": "https://objects.example.test",
                            "credentials": {
                                "access_key_id": "access-private",
                                "secret_access_key": "secret-private",
                            },
                        },
                        "backup.s3.credentials",
                        field="credentials",
                    )
                self.assertFalse(path.exists())
                save_secret_config(
                    path,
                    {
                        "endpoint": "https://objects.example.test",
                        "credentials": '{"secret_access_key":"private"}',
                        "label": "visible",
                    },
                    "backup.s3.credentials",
                    field="credentials",
                )
                stored = json.loads(path.read_text("utf-8"))
                loaded = load_secret_config(
                    path,
                    "backup.s3.credentials",
                    field="credentials",
                )

            self.assertTrue(stored["credentials"].startswith("enc2:"))
            self.assertEqual(stored["label"], "visible")
            self.assertEqual(loaded["credentials"], '{"secret_access_key":"private"}')
            self.assertEqual(loaded["label"], stored["label"])

    def test_rotation_waits_for_an_inflight_credential_commit(self):
        from services.secret_rotation import rotate_all_credentials

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                mock.patch.object(secretstore, "_KEY_FILE", root / "secret.key"),
                mock.patch.object(settings, "_SETTINGS_FILE", root / "settings.json"),
            ):
                secretstore._key = None
                secretstore._key_path = None
                secretstore._keys = {}
                secretstore._active_id = ""
                late = self.db()
                late.add(Connection(service="late", token="late-commit-private", meta=""))
                late.flush()

                started = threading.Event()
                finished = threading.Event()
                result = {}

                def rotate():
                    started.set()
                    result.update(rotate_all_credentials())
                    finished.set()

                worker = threading.Thread(target=rotate)
                worker.start()
                self.assertTrue(started.wait(1))
                was_blocked = not finished.wait(0.1)
                late.commit()
                late.close()
                worker.join(5)
                readable = self.db()
                try:
                    readable_token = (
                        readable.query(Connection).filter(Connection.service == "late").one().token
                    )
                finally:
                    readable.close()

            self.assertTrue(was_blocked)
            self.assertFalse(worker.is_alive())
            self.assertGreaterEqual(result["retired_keys"], 1)
            self.assertEqual(readable_token, "late-commit-private")


if __name__ == "__main__":
    import unittest

    unittest.main()
