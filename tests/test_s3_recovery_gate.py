import hashlib
import hmac
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
from urllib.parse import parse_qsl, quote, quote_from_bytes, unquote, unquote_to_bytes

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cli
import core.settings as settings
from core.database import Connection
from routes.connections import list_conns
from routes.settings import _public_settings
from services import s3_backup, secretstore
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
    s3_path = s3_backup.CONFIG_PATH
    secretstore._KEY_FILE = root / "secret.key"
    secretstore._key = None
    secretstore._key_path = None
    secretstore._keys = {}
    secretstore._active_id = ""
    settings._SETTINGS_FILE = root / "settings.json"
    settings._SETTINGS_CACHE = None
    settings._SETTINGS_CACHE_SIG = None
    s3_backup.CONFIG_PATH = root / s3_backup.CONFIG_NAME
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
        s3_backup.CONFIG_PATH = s3_path


class _FakeSignedS3:
    def __init__(self, *, bucket: str, region: str, access_key: str, secret_key: str):
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.events: list[dict] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self, _config: dict) -> httpx.Client:
        return httpx.Client(
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def _response(request: httpx.Request, status: int, *, body=b"", headers=None):
        return httpx.Response(
            status,
            request=request,
            stream=httpx.ByteStream(body),
            headers=headers or {},
        )

    @staticmethod
    def _canonical_query(query: str) -> str:
        pairs = parse_qsl(query, keep_blank_values=True)
        encoded = sorted(
            (quote(key, safe="-_.~"), quote(value, safe="-_.~")) for key, value in pairs
        )
        return "&".join(f"{key}={value}" for key, value in encoded)

    def _assert_signed(self, request: httpx.Request) -> None:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("AWS4-HMAC-SHA256 "):
            raise AssertionError("S3 request was not signed")
        parts = {}
        for item in authorization.removeprefix("AWS4-HMAC-SHA256 ").split(","):
            key, value = item.strip().split("=", 1)
            parts[key] = value
        credential = parts["Credential"].split("/")
        if credential[0] != self.access_key:
            raise AssertionError("S3 request used the wrong access key")
        date_stamp, region, service, terminal = credential[1:]
        if (region, service, terminal) != (self.region, "s3", "aws4_request"):
            raise AssertionError("S3 request used the wrong signing scope")
        signed_headers = parts["SignedHeaders"].split(";")
        required = {"host", "x-amz-content-sha256", "x-amz-date"}
        if not required.issubset(signed_headers):
            raise AssertionError("S3 request omitted required signed headers")
        canonical_headers = "".join(
            f"{name}:{' '.join(request.headers[name].strip().split())}\n" for name in signed_headers
        )
        raw_path = request.url.raw_path.split(b"?", 1)[0]
        canonical_uri = quote_from_bytes(unquote_to_bytes(raw_path.decode()), safe="/-_.~")
        canonical_request = "\n".join(
            (
                request.method,
                canonical_uri,
                self._canonical_query(request.url.query.decode()),
                canonical_headers,
                ";".join(signed_headers),
                request.headers["x-amz-content-sha256"],
            )
        )
        scope = "/".join(credential[1:])
        string_to_sign = "\n".join(
            (
                "AWS4-HMAC-SHA256",
                request.headers["x-amz-date"],
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            )
        )
        date_key = hmac.new(
            b"AWS4" + self.secret_key.encode(), date_stamp.encode(), hashlib.sha256
        ).digest()
        region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        signing_key = hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()
        expected = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(parts["Signature"], expected):
            raise AssertionError("S3 request signature did not verify")

    def _key(self, request: httpx.Request) -> str:
        prefix = f"/{self.bucket}/"
        if not request.url.path.startswith(prefix):
            raise AssertionError("unexpected S3 object path")
        return unquote(request.url.path[len(prefix) :])

    def _listing(self) -> bytes:
        rows = []
        for key, content in sorted(self.objects.items()):
            rows.append(
                "<Contents>"
                f"<Key>{quote(key, safe='')}</Key>"
                "<LastModified>2026-07-12T05:00:00Z</LastModified>"
                f"<ETag>{self.etags[key]}</ETag>"
                f"<Size>{len(content)}</Size>"
                "</Contents>"
            )
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<ListBucketResult>"
            "<EncodingType>url</EncodingType><IsTruncated>false</IsTruncated>"
            + "".join(rows)
            + "</ListBucketResult>"
        ).encode()

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self._assert_signed(request)
        method = request.method.upper()
        query = dict(parse_qsl(request.url.query.decode(), keep_blank_values=True))
        if method == "GET" and query.get("list-type") == "2":
            self.events.append({"method": "LIST"})
            document = self._listing()
            return self._response(
                request,
                200,
                body=document,
                headers={"Content-Length": str(len(document))},
            )

        key = self._key(request)
        if method == "PUT" and request.headers.get("x-amz-copy-source"):
            source_path = unquote(request.headers["x-amz-copy-source"])
            source_prefix = f"/{self.bucket}/"
            source = source_path.removeprefix(source_prefix)
            if (
                request.headers.get("if-none-match") != "*"
                or key in self.objects
                or source not in self.objects
                or request.headers.get("x-amz-copy-source-if-match") != self.etags[source]
            ):
                return self._response(request, 412)
            self.objects[key] = self.objects[source]
            self.etags[key] = self.etags[source]
            self.events.append({"method": "COPY", "source": source, "key": key})
            document = (
                "<CopyObjectResult>"
                f"<ETag>{self.etags[key]}</ETag>"
                "<LastModified>2026-07-12T05:00:00Z</LastModified>"
                "</CopyObjectResult>"
            ).encode()
            return self._response(
                request,
                200,
                body=document,
                headers={"Content-Length": str(len(document))},
            )
        if method == "PUT":
            content = request.read()
            if request.headers.get("if-none-match") != "*" or key in self.objects:
                return self._response(request, 412)
            if hashlib.sha256(content).hexdigest() != request.headers["x-amz-content-sha256"]:
                raise AssertionError("S3 payload checksum did not match")
            etag = f'"{hashlib.sha256(content).hexdigest()}"'
            self.objects[key] = content
            self.etags[key] = etag
            self.events.append({"method": "PUT", "key": key})
            return self._response(request, 200, headers={"ETag": etag})
        if method == "GET":
            content = self.objects.get(key)
            if content is None:
                return self._response(request, 404)
            self.events.append({"method": "GET", "key": key})
            return self._response(
                request,
                200,
                body=content,
                headers={"Content-Length": str(len(content)), "ETag": self.etags[key]},
            )
        if method == "DELETE":
            self.objects.pop(key, None)
            self.etags.pop(key, None)
            self.events.append({"method": "DELETE", "key": key})
            return self._response(request, 204)
        return self._response(request, 405)


class S3RecoveryGateTest(unittest.TestCase):
    @staticmethod
    def _assert_absent(blobs, secrets) -> None:
        for blob in blobs:
            raw = blob.encode() if isinstance(blob, str) else bytes(blob)
            for secret in secrets:
                if secret.encode() in raw:
                    raise AssertionError("a plaintext S3 recovery-gate secret leaked")

    def test_remote_artifact_recovers_every_credential_after_source_deletion(self):
        connector_secret = "gate-connector-244319b88bb54f7c97026082"
        settings_secret = "gate-settings-74014daa276f43d0b6f7b1dd"
        access_key = "gate-access-35e32b4701634a84"
        secret_key = "gate-s3-secret-9c4a7e0435244023a73541a0"
        secrets = (connector_secret, settings_secret, access_key, secret_key)
        public_s3 = {
            "endpoint": "https://objects.example.test",
            "region": "test-1",
            "bucket": "alles-backups",
            "prefix": "private/alles",
            "addressing_style": "path",
        }
        remote = _FakeSignedS3(
            bucket=public_s3["bucket"],
            region=public_s3["region"],
            access_key=access_key,
            secret_key=secret_key,
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
                    mock.patch.object(s3_backup, "_new_client", side_effect=remote.client),
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
                        candidate = s3_backup.config_candidate(
                            public_s3,
                            access_key_id=access_key,
                            secret_access_key=secret_key,
                        )
                        verified = s3_backup.test_connection(candidate)
                        save_output = s3_backup.save_config(
                            candidate,
                            verified_at=verified["verified_at"],
                        )
                        status_output = s3_backup.status()
                        settings_output = _public_settings(settings.load_settings())
                        remote.events.clear()

                        with closing(sqlite3.connect(source / "aide.db")) as raw_db:
                            stored_connector = raw_db.execute(
                                "SELECT token FROM connections WHERE id = ?",
                                ("recovery-gate-connection",),
                            ).fetchone()[0]
                        stored_settings = json.loads((source / "settings.json").read_text())[
                            "openai_api_key"
                        ]
                        stored_s3 = json.loads((source / s3_backup.CONFIG_NAME).read_text())[
                            "credentials"
                        ]
                        for stored in (stored_connector, stored_settings, stored_s3):
                            self.assertTrue(stored.startswith("enc2:"))

                        api_like = json.dumps(
                            {
                                "connections": connection_output,
                                "settings": settings_output,
                                "s3_save": save_output,
                                "s3_status": status_output,
                            },
                            sort_keys=True,
                        )
                        self._assert_absent([api_like], secrets)
                        self.assertNotIn("credentials", status_output)

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
                        upload = s3_backup.upload_artifact(encrypted)

                    raw_source_files = [
                        path.read_bytes() for path in source.glob("aide.db*") if path.is_file()
                    ]
                    raw_source_files.extend(
                        [
                            (source / "settings.json").read_bytes(),
                            (source / s3_backup.CONFIG_NAME).read_bytes(),
                        ]
                    )
                    final_key = f"{public_s3['prefix']}/{upload['name']}"
                    self._assert_absent(raw_source_files, secrets)
                    self._assert_absent(
                        [
                            encrypted.read_bytes(),
                            remote.objects[final_key],
                            exported_key.read_bytes(),
                        ],
                        secrets,
                    )
                    self.assertEqual(
                        [event["method"] for event in remote.events],
                        ["PUT", "COPY", "GET", "DELETE"],
                    )
                    self.assertIn("/.alles-upload-", f"/{remote.events[0]['key']}")
                    self.assertEqual(remote.events[1]["key"], final_key)
                    self.assertEqual(remote.events[2]["key"], final_key)
                    self.assertEqual(remote.events[3]["key"], remote.events[0]["key"])
                    self.assertFalse(
                        any(".partial" in key or ".probe" in key for key in remote.objects)
                    )

                    del recovery_key
                    shutil.rmtree(source_install)
                    self.assertFalse(source.exists())

                    with _active_data_root(clean):
                        clean_candidate = s3_backup.config_candidate(
                            public_s3,
                            access_key_id=access_key,
                            secret_access_key=secret_key,
                        )
                        clean_verified = s3_backup.test_connection(clean_candidate)
                        clean_status = s3_backup.save_config(
                            clean_candidate,
                            verified_at=clean_verified["verified_at"],
                        )
                        self.assertTrue(clean_status["configured"])
                        listed = s3_backup.list_artifacts()
                        self.assertEqual([item["name"] for item in listed], [upload["name"]])
                        selected = listed[0]
                        downloaded = restore_work / upload["name"]
                        s3_backup.download_artifact(
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
                        restored_credentials = json.loads(s3_backup.load_config()["credentials"])
                        self.assertEqual(restored_credentials["access_key_id"], access_key)
                        self.assertEqual(restored_credentials["secret_access_key"], secret_key)

                    with closing(sqlite3.connect(staged.data_dir / "aide.db")) as raw_db:
                        staged_connector = raw_db.execute(
                            "SELECT token FROM connections WHERE id = ?",
                            ("recovery-gate-connection",),
                        ).fetchone()[0]
                    staged_settings = json.loads((staged.data_dir / "settings.json").read_text())[
                        "openai_api_key"
                    ]
                    staged_s3 = json.loads((staged.data_dir / s3_backup.CONFIG_NAME).read_text())[
                        "credentials"
                    ]
                    for stored in (staged_connector, staged_settings, staged_s3):
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
