import base64
import hashlib
import io
import json
import logging
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cli
import core.settings as settings
from core.database import Connection
from routes.connections import list_conns
from routes.settings import _public_settings
from services import secretstore, webdav_backup
from services.backup_recovery import create_recovery_archive, stage_recovery_archive
from services.recovery_crypto import (
    decrypt_recovery_container,
    encrypt_recovery_archive,
    load_or_create_recovery_key,
    parse_recovery_key,
    recovery_key_document,
)


@contextmanager
def _active_data_root(root: Path):
    secret_state = (
        secretstore._KEY_FILE,
        secretstore._key,
        secretstore._key_path,
        dict(secretstore._keys),
        secretstore._active_id,
    )
    settings_state = (
        settings._SETTINGS_FILE,
        settings._SETTINGS_CACHE,
        settings._SETTINGS_CACHE_SIG,
    )
    webdav_path = webdav_backup.CONFIG_PATH
    secretstore._KEY_FILE = root / "secret.key"
    secretstore._key = None
    secretstore._key_path = None
    secretstore._keys = {}
    secretstore._active_id = ""
    settings._SETTINGS_FILE = root / "settings.json"
    settings._SETTINGS_CACHE = None
    settings._SETTINGS_CACHE_SIG = None
    webdav_backup.CONFIG_PATH = root / webdav_backup.CONFIG_NAME
    try:
        yield
    finally:
        (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            secretstore._keys,
            secretstore._active_id,
        ) = secret_state
        (
            settings._SETTINGS_FILE,
            settings._SETTINGS_CACHE,
            settings._SETTINGS_CACHE_SIG,
        ) = settings_state
        webdav_backup.CONFIG_PATH = webdav_path


class _FakeWebDAVServer:
    def __init__(self, collection_url: str, username: str, password: str):
        self.collection_url = collection_url
        self.collection_path = urlsplit(collection_url).path
        self.authorization = "Basic " + base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        self.temporary: dict[str, bytes] = {}
        self.artifacts: dict[str, bytes] = {}
        self.events: list[dict] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self, config: dict) -> httpx.Client:
        return httpx.Client(
            auth=(config["username"], config["password"]),
            transport=self.transport,
            follow_redirects=False,
        )

    @staticmethod
    def _response(request: httpx.Request, status: int, *, body=b"", headers=None):
        return httpx.Response(
            status,
            request=request,
            stream=httpx.ByteStream(body),
            headers=headers or {},
        )

    def _listing(self) -> bytes:
        rows = []
        for name, content in sorted(self.artifacts.items()):
            checksum = hashlib.sha256(content).hexdigest()
            rows.append(
                "<d:response>"
                f"<d:href>{self.collection_path}{name}</d:href>"
                "<d:propstat><d:prop>"
                f"<d:getcontentlength>{len(content)}</d:getcontentlength>"
                "<d:getlastmodified>Sun, 12 Jul 2026 05:00:00 GMT</d:getlastmodified>"
                f'<d:getetag>"{checksum}"</d:getetag>'
                "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
                "</d:response>"
            )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:multistatus xmlns:d="DAV:">' + "".join(rows) + "</d:multistatus>"
        ).encode("utf-8")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization", "") != self.authorization:
            return self._response(request, 401)
        method = request.method.upper()
        name = request.url.path.rsplit("/", 1)[-1]
        if method == "PUT":
            content = request.read()
            if request.headers.get("if-none-match") != "*" or name in self.temporary:
                return self._response(request, 412)
            self.temporary[name] = content
            self.events.append({"method": method, "name": name})
            return self._response(request, 201)
        if method == "MOVE":
            destination = request.headers.get("destination", "")
            destination_name = urlsplit(destination).path.rsplit("/", 1)[-1]
            if (
                request.headers.get("overwrite") != "F"
                or name not in self.temporary
                or destination_name in self.artifacts
            ):
                return self._response(request, 412)
            self.artifacts[destination_name] = self.temporary.pop(name)
            self.events.append({"method": method, "name": name, "destination": destination_name})
            return self._response(request, 201)
        if method == "GET":
            content = self.artifacts.get(name)
            if content is None:
                return self._response(request, 404)
            self.events.append({"method": method, "name": name})
            return self._response(
                request,
                200,
                body=content,
                headers={"Content-Length": str(len(content))},
            )
        if method == "PROPFIND":
            document = self._listing()
            self.events.append({"method": method, "depth": request.headers.get("depth", "")})
            return self._response(
                request,
                207,
                body=document,
                headers={"Content-Length": str(len(document))},
            )
        if method == "DELETE":
            self.temporary.pop(name, None)
            self.events.append({"method": method, "name": name})
            return self._response(request, 204)
        return self._response(request, 405)


class WebDAVRecoveryGateTest(unittest.TestCase):
    @staticmethod
    def _assert_absent(blobs, secrets) -> None:
        for blob in blobs:
            raw = blob.encode("utf-8") if isinstance(blob, str) else bytes(blob)
            for secret in secrets:
                if secret.encode("utf-8") in raw:
                    raise AssertionError("a plaintext recovery-gate secret leaked")

    def test_remote_artifact_recovers_every_credential_after_source_deletion(self):
        connector_secret = "gate-connector-4dd9286535f14e46a2c43acd"
        settings_secret = "gate-settings-694973b31abc4e9dafcb4f26"
        webdav_secret = "gate-webdav-1038dbbc993d4e15918ff6c0"
        secrets = (connector_secret, settings_secret, webdav_secret)
        held_webdav = {
            "url": "https://dav.example.test/backups/",
            "username": "backup-owner",
            "password": webdav_secret,
        }
        remote = _FakeWebDAVServer(
            held_webdav["url"],
            held_webdav["username"],
            held_webdav["password"],
        )

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source_install = base / "source-install"
            source = source_install / "data"
            source_work = source_install / "work"
            clean = base / "clean-install" / "data"
            restore_work = base / "restore-work"
            key_store = base / "owner-key-store"
            for path in (source, source_work, clean, restore_work, key_store):
                path.mkdir(parents=True)
            for path in (source / "vault", source / "files"):
                path.mkdir()
            self.assertTrue(cli._run_recovery_probe(source, passes=1))

            exported_key = key_store / "alles-recovery-key.txt"
            plaintext = source_work / "recovery.zip"
            encrypted = source_work / "remote.alles-backup"
            stdout = io.StringIO()
            stderr = io.StringIO()
            logs = io.StringIO()
            handler = logging.StreamHandler(logs)
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            try:
                with (
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    mock.patch.object(
                        webdav_backup,
                        "_new_client",
                        side_effect=remote.client,
                    ),
                    mock.patch("services.net_guard.assert_safe_url", return_value=None),
                ):
                    with _active_data_root(source):
                        source_engine = create_engine(f"sqlite:///{source / 'aide.db'}")
                        SourceSession = sessionmaker(bind=source_engine)
                        source_db = SourceSession()
                        source_db.add(
                            Connection(
                                id="recovery-gate-connection",
                                service="github",
                                token=connector_secret,
                                meta=json.dumps({"owner": "recovery-gate"}),
                            )
                        )
                        source_db.commit()
                        connection_output = list_conns(db=source_db)
                        source_db.close()
                        source_engine.dispose()

                        settings.save_settings({"openai_api_key": settings_secret})
                        save_output = webdav_backup.save_config(held_webdav)
                        status_output = webdav_backup.status()
                        settings_output = _public_settings(settings.load_settings())

                        with closing(sqlite3.connect(source / "aide.db")) as raw_db:
                            stored_connector = raw_db.execute(
                                "SELECT token FROM connections WHERE id = ?",
                                ("recovery-gate-connection",),
                            ).fetchone()[0]
                        stored_settings = json.loads((source / "settings.json").read_text("utf-8"))[
                            "openai_api_key"
                        ]
                        stored_webdav = json.loads(
                            (source / webdav_backup.CONFIG_NAME).read_text("utf-8")
                        )["password"]
                        for stored in (stored_connector, stored_settings, stored_webdav):
                            self.assertTrue(stored.startswith("enc2:"))

                        api_like = json.dumps(
                            {
                                "connections": connection_output,
                                "settings": settings_output,
                                "webdav_save": save_output,
                                "webdav_status": status_output,
                            },
                            sort_keys=True,
                        )
                        self._assert_absent([api_like], secrets)
                        self.assertNotIn("password", status_output)

                        recovery_key = load_or_create_recovery_key(source)
                        exported_key.write_bytes(recovery_key_document(recovery_key))
                        create_recovery_archive(
                            source,
                            plaintext,
                            expected_recovery_key=recovery_key,
                        )
                        with zipfile.ZipFile(plaintext) as archive:
                            self._assert_absent(
                                [archive.read(name) for name in archive.namelist()],
                                secrets,
                            )
                        encrypt_recovery_archive(plaintext, encrypted, recovery_key)
                        upload = webdav_backup.upload_artifact(encrypted)

                    raw_source_files = [
                        path.read_bytes() for path in source.glob("aide.db*") if path.is_file()
                    ]
                    raw_source_files.extend(
                        [
                            (source / "settings.json").read_bytes(),
                            (source / webdav_backup.CONFIG_NAME).read_bytes(),
                        ]
                    )
                    self._assert_absent(raw_source_files, secrets)
                    self._assert_absent(
                        [
                            encrypted.read_bytes(),
                            remote.artifacts[upload["name"]],
                            exported_key.read_bytes(),
                        ],
                        secrets,
                    )
                    self.assertEqual(
                        [event["method"] for event in remote.events],
                        ["PUT", "MOVE", "GET"],
                    )
                    self.assertTrue(remote.events[0]["name"].startswith(".alles-upload-"))
                    self.assertEqual(remote.events[1]["destination"], upload["name"])
                    self.assertEqual(remote.events[2]["name"], upload["name"])
                    self.assertEqual(remote.temporary, {})

                    del recovery_key
                    shutil.rmtree(source_install)
                    self.assertFalse(source.exists())

                    with _active_data_root(clean):
                        clean_status = webdav_backup.save_config(dict(held_webdav))
                        self.assertTrue(clean_status["configured"])
                        listed = webdav_backup.list_artifacts()
                        self.assertEqual([item["name"] for item in listed], [upload["name"]])
                        selected = listed[0]
                        downloaded = restore_work / upload["name"]
                        webdav_backup.download_artifact(
                            upload["name"],
                            downloaded,
                            expected_size=selected["size"],
                            expected_sha256=upload["sha256"],
                        )

                    decrypted = restore_work / "recovery.zip"
                    separate_key = parse_recovery_key(exported_key.read_bytes())
                    decrypt_recovery_container(downloaded, decrypted, separate_key)
                    staged = stage_recovery_archive(decrypted, clean)
                    self.assertFalse(source.exists())

                    with _active_data_root(staged.data_dir):
                        staged_engine = create_engine(f"sqlite:///{staged.data_dir / 'aide.db'}")
                        StagedSession = sessionmaker(bind=staged_engine)
                        staged_db = StagedSession()
                        restored_connection = staged_db.get(
                            Connection,
                            "recovery-gate-connection",
                        )
                        self.assertIsNotNone(restored_connection)
                        self.assertEqual(restored_connection.token, connector_secret)
                        staged_db.close()
                        staged_engine.dispose()
                        self.assertEqual(
                            settings.load_settings()["openai_api_key"],
                            settings_secret,
                        )
                        self.assertEqual(
                            webdav_backup.load_config()["password"],
                            webdav_secret,
                        )

                    with closing(sqlite3.connect(staged.data_dir / "aide.db")) as raw_db:
                        staged_connector = raw_db.execute(
                            "SELECT token FROM connections WHERE id = ?",
                            ("recovery-gate-connection",),
                        ).fetchone()[0]
                    staged_settings = json.loads(
                        (staged.data_dir / "settings.json").read_text("utf-8")
                    )["openai_api_key"]
                    staged_webdav = json.loads(
                        (staged.data_dir / webdav_backup.CONFIG_NAME).read_text("utf-8")
                    )["password"]
                    for stored in (staged_connector, staged_settings, staged_webdav):
                        self.assertTrue(stored.startswith("enc2:"))
            finally:
                root_logger.removeHandler(handler)
                handler.close()

            self._assert_absent(
                [stdout.getvalue(), stderr.getvalue(), logs.getvalue(), json.dumps(remote.events)],
                secrets,
            )


if __name__ == "__main__":
    unittest.main()
