import hashlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx
from sqlalchemy import create_engine

from services import secretstore, webdav_backup
from services.recovery_crypto import encrypt_recovery_archive


class WebDAVBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_config_path = webdav_backup.CONFIG_PATH
        webdav_backup.CONFIG_PATH = self.root / "webdav_backup.json"
        self.original_secret_state = (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            dict(secretstore._keys),
            secretstore._active_id,
        )
        secretstore._KEY_FILE = self.root / "secret.key"
        secretstore._key = None
        secretstore._key_path = None
        secretstore._keys = {}
        secretstore._active_id = ""
        self.config = {
            "url": "https://dav.example.test/backups",
            "username": "owner",
            "password": "correct horse battery staple",
        }
        plain = self.root / "plain.zip"
        plain.write_bytes(b"synthetic portable archive" * 100)
        self.artifact = self.root / "source.alles-backup"
        encrypt_recovery_archive(plain, self.artifact, os.urandom(32))
        self.payload = self.artifact.read_bytes()

    def tearDown(self):
        webdav_backup.CONFIG_PATH = self.original_config_path
        (
            secretstore._KEY_FILE,
            secretstore._key,
            secretstore._key_path,
            secretstore._keys,
            secretstore._active_id,
        ) = self.original_secret_state
        self.temp.cleanup()

    @contextmanager
    def remote(self, handler, *, guard=None):
        def client(config):
            return httpx.Client(
                transport=httpx.MockTransport(handler),
                auth=(config["username"], config["password"]),
                timeout=webdav_backup.REQUEST_TIMEOUT,
                follow_redirects=False,
                trust_env=False,
            )

        guard_mock = guard or mock.Mock()
        with (
            mock.patch.object(webdav_backup, "_new_client", client),
            mock.patch("services.net_guard.assert_safe_url", guard_mock),
        ):
            yield guard_mock

    @staticmethod
    def artifact_name(suffix="abcdef012345"):
        return f"alles-backup-20260712T010203Z-{suffix}.alles-backup"

    def test_url_normalization_is_https_only_and_rejects_ambiguous_paths(self):
        self.assertEqual(
            webdav_backup.normalize_collection_url("https://Example.COM:443/a%20b"),
            "https://example.com/a%20b/",
        )
        self.assertEqual(
            webdav_backup.normalize_collection_url("https://[2001:db8::1]:8443/backups/"),
            "https://[2001:db8::1]:8443/backups/",
        )
        rejected = (
            "http://example.com/backups",
            "https://owner:secret@example.com/backups",
            "https://example.com/backups?token=secret",
            "https://example.com/backups#fragment",
            "https://example.com/a/../backups",
            "https://example.com/a/%2e%2e/backups",
            "https://example.com/a/%2fetc",
            "https://example.com/a/%5cetc",
            "https://example.com/a/%252e%252e",
            "https://example.com/a//b",
            "https://example.com/a\nb",
            "https://example.com:0/backups",
            "https://bad_host.example/backups",
            " https://example.com/backups",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(webdav_backup.WebDAVError):
                webdav_backup.normalize_collection_url(value)

    def test_client_disables_environment_redirects_and_keeps_tls_verification(self):
        with mock.patch.object(webdav_backup.httpx, "Client") as constructor:
            webdav_backup._new_client(self.config)
        kwargs = constructor.call_args.kwargs
        self.assertFalse(kwargs["trust_env"])
        self.assertFalse(kwargs["follow_redirects"])
        self.assertTrue(kwargs["verify"])
        self.assertIsInstance(kwargs["timeout"], httpx.Timeout)

    def test_config_is_encrypted_masked_and_preserves_metadata_on_blank_password(self):
        result = webdav_backup.save_config(self.config)
        stored = json.loads(webdav_backup.CONFIG_PATH.read_text("utf-8"))
        self.assertTrue(stored["password"].startswith("enc2:"))
        self.assertNotIn(self.config["password"], webdav_backup.CONFIG_PATH.read_text("utf-8"))
        self.assertNotIn("password", result)
        self.assertTrue(result["password_set"])
        self.assertEqual(result["version"], 1)

        loaded = webdav_backup.load_config()
        loaded.update(
            {
                "last_backup_at": "2026-07-12T01:02:03Z",
                "last_verified_at": "2026-07-12T01:02:03Z",
                "last_filename": self.artifact_name(),
                "last_bytes": len(self.payload),
                "last_sha256": hashlib.sha256(self.payload).hexdigest(),
            }
        )
        webdav_backup.save_secret_config(
            webdav_backup.CONFIG_PATH,
            loaded,
            webdav_backup.PASSWORD_PURPOSE,
        )
        masked = webdav_backup.save_config(
            {
                "url": "https://dav.example.test/backups/",
                "username": "owner",
                "password": "",
            }
        )
        self.assertEqual(webdav_backup.load_config()["password"], self.config["password"])
        self.assertEqual(masked["last_filename"], self.artifact_name())
        self.assertEqual(masked["last_sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertNotIn(self.config["password"], repr(masked))

    def test_plaintext_config_migrates_on_first_load_and_delete_removes_it(self):
        webdav_backup.CONFIG_PATH.write_text(json.dumps(self.config), "utf-8")
        masked = webdav_backup.status()
        self.assertTrue(masked["configured"])
        self.assertNotIn("password", masked)
        stored = json.loads(webdav_backup.CONFIG_PATH.read_text("utf-8"))
        self.assertTrue(stored["password"].startswith("enc2:"))
        self.assertEqual(webdav_backup.load_config()["password"], self.config["password"])

        deleted = webdav_backup.delete_config()
        self.assertFalse(deleted["configured"])
        self.assertFalse(webdav_backup.CONFIG_PATH.exists())

    def test_startup_migrates_plaintext_config_before_direct_backup(self):
        from core import database
        from routes import backup as backup_routes
        from services.recovery_crypto import is_encrypted_recovery

        webdav_backup.CONFIG_PATH.write_text(json.dumps(self.config), "utf-8")
        old_path, old_engine = database.DB_PATH, database.engine
        database.DB_PATH = str(self.root / "aide.db")
        database.engine = create_engine(f"sqlite:///{database.DB_PATH}")
        database.SessionLocal.configure(bind=database.engine)
        try:
            with (
                mock.patch("core.settings.migrate_setting_secrets", return_value=0),
                mock.patch("services.caldav_sync.migrate_cfg_secrets", return_value=0),
                mock.patch("services.carddav_sync.migrate_cfg_secrets", return_value=0),
            ):
                database.init_db()
            stored = json.loads(webdav_backup.CONFIG_PATH.read_text("utf-8"))
            self.assertTrue(stored["password"].startswith("enc2:"))
            self.assertEqual(webdav_backup.load_config()["password"], self.config["password"])

            with tempfile.TemporaryDirectory() as output_dir:
                artifact = Path(output_dir) / "startup.alles-backup"
                backup_routes._create_encrypted_backup(self.root, artifact)
                self.assertTrue(is_encrypted_recovery(artifact))
        finally:
            database.engine.dispose()
            database.DB_PATH, database.engine = old_path, old_engine
            database.SessionLocal.configure(bind=old_engine)

    def test_config_rejects_reserved_ciphertext_input_and_linked_storage(self):
        with self.assertRaisesRegex(webdav_backup.WebDAVError, "reserved"):
            webdav_backup.save_config({**self.config, "password": "enc2:fake:ciphertext"})
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(self.config), "utf-8")
        try:
            webdav_backup.CONFIG_PATH.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        masked = webdav_backup.status()
        self.assertFalse(masked["configured"])
        self.assertEqual(outside.read_text("utf-8"), json.dumps(self.config))
        webdav_backup.delete_config()
        self.assertFalse(webdav_backup.CONFIG_PATH.exists())
        self.assertTrue(outside.exists())

    def test_corrupt_config_status_is_safe_and_does_not_expose_ciphertext(self):
        webdav_backup.CONFIG_PATH.write_text(
            json.dumps({**self.config, "password": "enc2:missing:private-ciphertext"}),
            "utf-8",
        )
        masked = webdav_backup.status()
        self.assertFalse(masked["configured"])
        self.assertEqual(masked["error"], "webdav backup configuration could not be loaded")
        self.assertNotIn("private-ciphertext", repr(masked))

    def test_connection_uses_depth_zero_and_checks_net_guard(self):
        seen = []

        def handler(request):
            seen.append(request)
            self.assertEqual(request.method, "PROPFIND")
            self.assertEqual(request.headers["Depth"], "0")
            self.assertTrue(request.headers["Authorization"].startswith("Basic "))
            request.read()
            return httpx.Response(207, content=b"ignored")

        with self.remote(handler) as guard:
            result = webdav_backup.test_connection(self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 1)
        guard.assert_called_once_with("https://dav.example.test/backups/")

    def test_redirect_and_remote_body_are_not_exposed_in_errors(self):
        private_body = b"password=remote-secret"

        def redirect(_request):
            return httpx.Response(302, headers={"Location": "https://evil.test/steal"})

        with (
            self.remote(redirect),
            self.assertRaisesRegex(
                webdav_backup.WebDAVError, "redirects are not allowed"
            ) as raised,
        ):
            webdav_backup.test_connection(self.config)
        self.assertNotIn("evil.test", str(raised.exception))

        def failure(_request):
            return httpx.Response(500, content=private_body)

        with self.remote(failure), self.assertRaises(webdav_backup.WebDAVError) as raised:
            webdav_backup.test_connection(self.config)
        self.assertNotIn("remote-secret", str(raised.exception))
        self.assertNotIn(self.config["password"], str(raised.exception))

    def test_job_lock_fails_fast_without_starting_a_request(self):
        handler = mock.Mock()
        self.assertTrue(webdav_backup._JOB_LOCK.acquire(blocking=False))
        try:
            with self.remote(handler), self.assertRaises(webdav_backup.WebDAVBusyError):
                webdav_backup.test_connection(self.config)
            with self.assertRaises(webdav_backup.WebDAVBusyError):
                webdav_backup.save_config(self.config)
            with self.assertRaises(webdav_backup.WebDAVBusyError):
                webdav_backup.delete_config()
        finally:
            webdav_backup._JOB_LOCK.release()
        handler.assert_not_called()

    def test_upload_uses_unique_temp_move_and_streamed_get_verification(self):
        remote = {}
        calls = []

        def handler(request):
            calls.append((request.method, request.url, dict(request.headers)))
            path = request.url.path
            if request.method == "PUT":
                self.assertRegex(path.rsplit("/", 1)[-1], webdav_backup._TEMP_NAME)
                self.assertEqual(request.headers["If-None-Match"], "*")
                remote[path] = request.read()
                return httpx.Response(201)
            if request.method == "MOVE":
                self.assertEqual(request.headers["Overwrite"], "F")
                destination = httpx.URL(request.headers["Destination"])
                self.assertEqual(destination.host, request.url.host)
                self.assertRegex(destination.path.rsplit("/", 1)[-1], webdav_backup._ARTIFACT_NAME)
                remote[destination.path] = remote.pop(path)
                return httpx.Response(201)
            if request.method == "GET":
                self.assertEqual(request.headers["Accept-Encoding"], "identity")
                body = remote[path]
                return httpx.Response(200, content=body, headers={"Content-Length": str(len(body))})
            if request.method == "DELETE":
                remote.pop(path, None)
                return httpx.Response(204)
            self.fail(request.method)

        webdav_backup.save_config(self.config)
        with self.remote(handler) as guard:
            result = webdav_backup.upload_artifact(self.artifact)
        self.assertEqual([call[0] for call in calls], ["PUT", "MOVE", "GET"])
        self.assertEqual(result["size"], len(self.payload))
        self.assertEqual(result["sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(remote[f"/backups/{result['name']}"], self.payload)
        self.assertEqual(guard.call_count, 4)
        masked = webdav_backup.status()
        self.assertEqual(masked["last_filename"], result["name"])
        self.assertEqual(masked["last_bytes"], len(self.payload))
        self.assertEqual(masked["last_sha256"], result["sha256"])
        self.assertTrue(masked["last_backup_at"].endswith("Z"))

    def test_verified_upload_survives_local_status_write_failure(self):
        remote = {}

        def handler(request):
            path = request.url.path
            if request.method == "PUT":
                remote[path] = request.read()
                return httpx.Response(201)
            if request.method == "MOVE":
                destination = httpx.URL(request.headers["Destination"]).path
                remote[destination] = remote.pop(path)
                return httpx.Response(201)
            if request.method == "GET":
                return httpx.Response(200, content=remote[path])
            if request.method == "DELETE":
                remote.pop(path, None)
                return httpx.Response(204)
            self.fail(request.method)

        webdav_backup.save_config(self.config)
        with (
            self.remote(handler),
            mock.patch.object(webdav_backup, "_record_status", side_effect=OSError("disk-private")),
        ):
            result = webdav_backup.upload_artifact(self.artifact)

        self.assertTrue(result["ok"])
        self.assertTrue(result["completed_at"].endswith("Z"))
        self.assertIn("local webdav status could not be saved", result["status_warning"])
        self.assertNotIn("disk-private", repr(result))
        self.assertEqual(remote[f"/backups/{result['name']}"], self.payload)

        with (
            self.remote(handler),
            mock.patch.object(webdav_backup, "_record_status", return_value=False),
        ):
            changed = webdav_backup.upload_artifact(self.artifact)
        self.assertIn("local webdav status could not be saved", changed["status_warning"])

    def test_lost_move_response_is_reconciled_by_exact_readback(self):
        remote = {}
        calls = []

        def handler(request):
            path = request.url.path
            calls.append(request.method)
            if request.method == "PUT":
                remote[path] = request.read()
                return httpx.Response(201)
            if request.method == "MOVE":
                destination = httpx.URL(request.headers["Destination"]).path
                remote[destination] = remote.pop(path)
                raise httpx.ReadTimeout("response was lost", request=request)
            if request.method == "GET":
                return httpx.Response(200, content=remote[path])
            if request.method == "DELETE":
                remote.pop(path, None)
                return httpx.Response(204)
            self.fail(request.method)

        with self.remote(handler):
            result = webdav_backup.upload_artifact(self.artifact, config=self.config)

        self.assertEqual(calls, ["PUT", "MOVE", "GET"])
        self.assertEqual(remote[f"/backups/{result['name']}"], self.payload)
        self.assertEqual(result["sha256"], hashlib.sha256(self.payload).hexdigest())

    def test_upload_rejects_plaintext_and_links_before_network(self):
        plaintext = self.root / "plain.alles-backup"
        plaintext.write_bytes(b"not encrypted")
        handler = mock.Mock()
        with (
            self.remote(handler),
            self.assertRaisesRegex(webdav_backup.WebDAVError, "encrypted backup"),
        ):
            webdav_backup.upload_artifact(plaintext, config=self.config)
        handler.assert_not_called()

        link = self.root / "link.alles-backup"
        try:
            link.symlink_to(self.artifact)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "link"):
            webdav_backup.upload_artifact(link, config=self.config)
        handler.assert_not_called()

    def test_failed_put_cleans_only_the_generated_temporary_name(self):
        calls = []

        def handler(request):
            calls.append((request.method, request.url.path))
            if request.method == "PUT":
                request.read()
                return httpx.Response(412, content=b"private conflict body")
            if request.method == "DELETE":
                return httpx.Response(204)
            self.fail(request.method)

        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "conflicted"):
            webdav_backup.upload_artifact(self.artifact, config=self.config)
        self.assertEqual([method for method, _path in calls], ["PUT", "DELETE"])
        self.assertRegex(calls[1][1].rsplit("/", 1)[-1], webdav_backup._TEMP_NAME)

    def test_failed_verification_removes_the_generated_final_backup(self):
        remote = {}
        deleted = []

        def handler(request):
            path = request.url.path
            if request.method == "PUT":
                remote[path] = request.read()
                return httpx.Response(201)
            if request.method == "MOVE":
                destination = httpx.URL(request.headers["Destination"]).path
                remote[destination] = remote.pop(path)
                return httpx.Response(201)
            if request.method == "GET":
                changed = bytearray(remote[path])
                changed[-1] ^= 1
                return httpx.Response(200, content=bytes(changed))
            if request.method == "DELETE":
                deleted.append(path)
                remote.pop(path, None)
                return httpx.Response(204)
            self.fail(request.method)

        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "checksum"):
            webdav_backup.upload_artifact(self.artifact, config=self.config)
        self.assertEqual(len(deleted), 1)
        self.assertRegex(deleted[0].rsplit("/", 1)[-1], webdav_backup._ARTIFACT_NAME)
        self.assertEqual(remote, {})

    def test_listing_is_bounded_and_accepts_only_direct_generated_children(self):
        first = self.artifact_name("111111111111")
        second = self.artifact_name("222222222222")
        xml = f"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response><d:href>/backups/</d:href></d:response>
          <d:response><d:href>/backups/{first}</d:href><d:propstat><d:prop>
            <d:getcontentlength>{len(self.payload)}</d:getcontentlength>
            <d:getlastmodified>Sun, 12 Jul 2026 01:02:03 GMT</d:getlastmodified>
            <d:getetag>\"one\"</d:getetag>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
          <d:response><d:href>https://dav.example.test/backups/{second}</d:href></d:response>
          <d:response><d:href>/backups/nested/{first}</d:href></d:response>
          <d:response><d:href>https://evil.test/backups/{first}</d:href></d:response>
          <d:response><d:href>/backups/.alles-upload-{"a" * 32}.partial</d:href></d:response>
          <d:response><d:href>/backups/not-alles.zip</d:href></d:response>
          <d:response><d:href>../backups/{first}</d:href></d:response>
        </d:multistatus>""".encode()

        def handler(request):
            self.assertEqual(request.method, "PROPFIND")
            self.assertEqual(request.headers["Depth"], "1")
            request.read()
            return httpx.Response(207, content=xml)

        with self.remote(handler):
            results = webdav_backup.list_artifacts(config=self.config)
        self.assertEqual([item["name"] for item in results], [second, first])
        first_item = next(item for item in results if item["name"] == first)
        self.assertEqual(first_item["size"], len(self.payload))
        self.assertEqual(first_item["etag"], '"one"')

        def oversized(_request):
            return httpx.Response(
                207,
                content=b"x",
                headers={"Content-Length": str(webdav_backup.MAX_LISTING_BYTES + 1)},
            )

        with self.remote(oversized), self.assertRaisesRegex(webdav_backup.WebDAVError, "too large"):
            webdav_backup.list_artifacts(config=self.config)

    def test_listing_rejects_entities_and_does_not_echo_xml(self):
        document = b'<!DOCTYPE x [<!ENTITY private "remote-secret">]><x>&private;</x>'

        def handler(_request):
            return httpx.Response(207, content=document)

        with self.remote(handler), self.assertRaises(webdav_backup.WebDAVError) as raised:
            webdav_backup.list_artifacts(config=self.config)
        self.assertNotIn("remote-secret", str(raised.exception))

    def test_listing_rejects_invalid_encoding_and_impossible_generated_date(self):
        impossible = "alles-backup-20269999T999999Z-abcdef012345.alles-backup"
        xml = (
            '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/backups/'
            + impossible
            + "</d:href></d:response></d:multistatus>"
        ).encode()

        def impossible_date(_request):
            return httpx.Response(207, content=xml)

        with self.remote(impossible_date):
            self.assertEqual(webdav_backup.list_artifacts(config=self.config), [])

        def invalid_encoding(_request):
            return httpx.Response(207, content=b"\xff\xfe<\x00x\x00/\x00>\x00")

        with (
            self.remote(invalid_encoding),
            self.assertRaisesRegex(webdav_backup.WebDAVError, "encoding"),
        ):
            webdav_backup.list_artifacts(config=self.config)

    def test_download_streams_to_atomic_file_and_checks_size_and_hash(self):
        name = self.artifact_name()
        destination = self.root / "downloaded.alles-backup"
        destination.write_bytes(b"old file")
        checksum = hashlib.sha256(self.payload).hexdigest()

        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, f"/backups/{name}")
            return httpx.Response(200, content=self.payload)

        with self.remote(handler):
            result = webdav_backup.download_artifact(
                name,
                destination,
                config=self.config,
                expected_size=len(self.payload),
                expected_sha256=checksum,
            )
        self.assertEqual(destination.read_bytes(), self.payload)
        self.assertEqual(result["size"], len(self.payload))
        self.assertEqual(result["sha256"], checksum)
        self.assertEqual(list(self.root.glob(f".{destination.name}.*.partial")), [])
        if os.name != "nt":
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_download_failure_preserves_existing_output_and_removes_partial(self):
        name = self.artifact_name()
        destination = self.root / "existing.alles-backup"
        destination.write_bytes(b"keep me")

        def handler(_request):
            return httpx.Response(200, content=self.payload)

        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "checksum"):
            webdav_backup.download_artifact(
                name,
                destination,
                config=self.config,
                expected_sha256="0" * 64,
            )
        self.assertEqual(destination.read_bytes(), b"keep me")
        self.assertEqual(list(self.root.glob(f".{destination.name}.*.partial")), [])

        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "size"):
            webdav_backup.download_artifact(
                name,
                destination,
                config=self.config,
                maximum=len(self.payload) - 1,
            )
        self.assertEqual(destination.read_bytes(), b"keep me")

    def test_download_rejects_untrusted_filename_and_destination_link(self):
        handler = mock.Mock()
        with self.remote(handler), self.assertRaises(webdav_backup.WebDAVError):
            webdav_backup.download_artifact(
                "../secret.alles-backup",
                self.root / "out",
                config=self.config,
            )
        handler.assert_not_called()

        target = self.root / "target"
        target.write_bytes(b"keep")
        link = self.root / "output-link"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "link"):
            webdav_backup.download_artifact(
                self.artifact_name(),
                link,
                config=self.config,
            )
        self.assertEqual(target.read_bytes(), b"keep")
        handler.assert_not_called()

    def test_caller_cannot_raise_the_global_transfer_bound(self):
        with self.assertRaisesRegex(webdav_backup.WebDAVError, "limit"):
            webdav_backup.upload_artifact(
                self.artifact,
                config=self.config,
                maximum=webdav_backup.MAX_ARTIFACT_BYTES + 1,
            )
        with self.assertRaisesRegex(webdav_backup.WebDAVError, "limit"):
            webdav_backup.download_artifact(
                self.artifact_name(),
                self.root / "out",
                config=self.config,
                maximum=webdav_backup.MAX_ARTIFACT_BYTES + 1,
            )

    def test_oversized_content_length_integer_fails_safely(self):
        def handler(_request):
            return httpx.Response(200, content=self.payload, headers={"Content-Length": "9" * 100})

        with self.remote(handler), self.assertRaisesRegex(webdav_backup.WebDAVError, "length"):
            webdav_backup.download_artifact(
                self.artifact_name(),
                self.root / "out",
                config=self.config,
            )


if __name__ == "__main__":
    unittest.main()
