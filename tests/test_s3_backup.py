import hashlib
import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

import httpx

from services import s3_backup, secretstore
from services.recovery_crypto import encrypt_recovery_archive


class S3BackupTest(unittest.TestCase):
    COPY_RESULT = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<CopyObjectResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        b"<LastModified>2026-07-12T01:02:03Z</LastModified>"
        b'<ETag>"copied"</ETag></CopyObjectResult>'
    )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_config_path = s3_backup.CONFIG_PATH
        s3_backup.CONFIG_PATH = self.root / s3_backup.CONFIG_NAME
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
        self.credentials = json.dumps(
            {
                "access_key_id": "backup-owner",
                "secret_access_key": "s3-private/secret+value",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        self.config = {
            "endpoint": "https://objects.example.test",
            "region": "us-east-1",
            "bucket": "alles-backups",
            "prefix": "private/alles",
            "addressing_style": "path",
            "credentials": self.credentials,
        }
        plain = self.root / "plain.zip"
        plain.write_bytes(b"synthetic portable archive" * 100)
        self.artifact = self.root / "source.alles-backup"
        encrypt_recovery_archive(plain, self.artifact, os.urandom(32))
        self.payload = self.artifact.read_bytes()

    def tearDown(self):
        s3_backup.CONFIG_PATH = self.original_config_path
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
        def client(_config):
            return httpx.Client(
                transport=httpx.MockTransport(handler),
                timeout=s3_backup.REQUEST_TIMEOUT,
                follow_redirects=False,
                trust_env=False,
                verify=True,
            )

        guard_mock = guard or mock.Mock()
        with (
            mock.patch.object(s3_backup, "_new_client", client),
            mock.patch("services.net_guard.assert_safe_url", guard_mock),
        ):
            yield guard_mock

    @staticmethod
    def artifact_name(suffix="abcdef012345"):
        return f"alles-backup-20260712T010203Z-{suffix}.alles-backup"

    def assert_signed(self, request):
        authorization = request.headers["Authorization"]
        self.assertTrue(authorization.startswith("AWS4-HMAC-SHA256 Credential=backup-owner/"))
        self.assertIn("Signature=", authorization)
        self.assertNotIn("s3-private", authorization)
        self.assertRegex(request.headers["X-Amz-Date"], r"^[0-9]{8}T[0-9]{6}Z$")
        self.assertRegex(request.headers["X-Amz-Content-Sha256"], r"^[0-9a-f]{64}$")

    def test_endpoint_and_destination_validation_is_strict(self):
        self.assertEqual(
            s3_backup.normalize_endpoint("https://Example.COM:443/"),
            "https://example.com",
        )
        self.assertEqual(
            s3_backup.normalize_endpoint("https://[2001:db8::1]:8443"),
            "https://[2001:db8::1]:8443",
        )
        rejected = (
            "http://objects.example.test",
            "https://owner:secret@objects.example.test",
            "https://objects.example.test/path",
            "https://objects.example.test?token=secret",
            "https://objects.example.test#private",
            "https://objects.example.test:0",
            "https://bad_host.example.test",
            " https://objects.example.test",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(s3_backup.S3Error):
                s3_backup.normalize_endpoint(value)

        bad_fields = (
            {"bucket": "192.168.1.1"},
            {"bucket": "Bad_Bucket"},
            {"region": "us east 1"},
            {"prefix": "../private"},
            {"prefix": "private//alles"},
            {"prefix": "private%2Falles"},
            {"addressing_style": "auto"},
        )
        for change in bad_fields:
            with self.subTest(change=change), self.assertRaises(s3_backup.S3Error):
                s3_backup._validated_config({**self.config, **change})

        virtual = s3_backup._validated_config(
            {**self.config, "prefix": "", "addressing_style": "virtual"}
        )
        self.assertEqual(
            s3_backup._object_url(virtual, self.artifact_name()),
            f"https://alles-backups.objects.example.test/{self.artifact_name()}",
        )
        with self.assertRaisesRegex(s3_backup.S3Error, "dns-safe"):
            s3_backup._validated_config(
                {**self.config, "bucket": "alles.backups", "addressing_style": "virtual"}
            )

    def test_config_is_sealed_masked_migrated_and_deleted(self):
        masked = s3_backup.save_config(self.config)
        raw_text = s3_backup.CONFIG_PATH.read_text("utf-8")
        raw = json.loads(raw_text)
        self.assertTrue(raw["credentials"].startswith("enc2:"))
        self.assertNotIn("backup-owner", raw_text)
        self.assertNotIn("s3-private", raw_text)
        self.assertNotIn("credentials", masked)
        self.assertTrue(masked["credentials_set"])
        self.assertEqual(s3_backup.load_config()["credentials"], self.credentials)
        self.assertNotIn("credentials", s3_backup.status())

        reused = s3_backup.config_candidate(
            {
                key: self.config[key]
                for key in (
                    "endpoint",
                    "region",
                    "bucket",
                    "prefix",
                    "addressing_style",
                )
            },
            current=s3_backup.load_config(),
        )
        self.assertEqual(reused["credentials"], self.credentials)
        with self.assertRaisesRegex(s3_backup.S3Error, "credentials are required"):
            s3_backup.config_candidate(
                {**reused, "prefix": "different"},
                current=s3_backup.load_config(),
            )
        with self.assertRaisesRegex(s3_backup.S3Error, "provided together"):
            s3_backup.config_candidate(reused, access_key_id="replacement")

        s3_backup.delete_config()
        s3_backup.CONFIG_PATH.write_text(
            json.dumps({**self.config, "credentials": self.credentials}), "utf-8"
        )
        status = s3_backup.status()
        self.assertTrue(status["configured"])
        migrated = json.loads(s3_backup.CONFIG_PATH.read_text("utf-8"))
        self.assertTrue(migrated["credentials"].startswith("enc2:"))
        self.assertEqual(s3_backup.load_config()["credentials"], self.credentials)
        self.assertFalse(s3_backup.delete_config()["configured"])
        self.assertFalse(s3_backup.CONFIG_PATH.exists())

    def test_config_rejects_noncanonical_credentials_and_linked_storage(self):
        bad_credentials = (
            "not-json",
            json.dumps({"access_key_id": "only-one-field"}),
            '{"access_key_id":"a","access_key_id":"b","secret_access_key":"c"}',
            json.dumps(
                {"secret_access_key": "secret", "access_key_id": "key"},
                separators=(",", ": "),
                sort_keys=True,
            ),
        )
        for value in bad_credentials:
            with self.subTest(value=value), self.assertRaises(s3_backup.S3Error):
                s3_backup.save_config({**self.config, "credentials": value})

        outside = self.root / "outside.json"
        outside.write_text(json.dumps(self.config), "utf-8")
        try:
            s3_backup.CONFIG_PATH.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        masked = s3_backup.status()
        self.assertFalse(masked["configured"])
        self.assertEqual(masked["error"], "s3 backup configuration could not be loaded")
        s3_backup.delete_config()
        self.assertTrue(outside.exists())
        self.assertFalse(s3_backup.CONFIG_PATH.exists())

    def test_client_disables_environment_redirects_and_keeps_tls_verification(self):
        with mock.patch.object(s3_backup.httpx, "Client") as constructor:
            s3_backup._new_client(self.config)
        kwargs = constructor.call_args.kwargs
        self.assertFalse(kwargs["trust_env"])
        self.assertFalse(kwargs["follow_redirects"])
        self.assertTrue(kwargs["verify"])
        self.assertIsInstance(kwargs["timeout"], httpx.Timeout)

    def test_signer_matches_official_aws_s3_vectors(self):
        credentials = {
            "access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        }
        moment = datetime(2013, 5, 24, tzinfo=UTC)
        object_headers = s3_backup._sign_request(
            "GET",
            "https://examplebucket.s3.amazonaws.com/test.txt",
            {"Range": "bytes=0-9"},
            s3_backup._EMPTY_SHA256,
            credentials,
            "us-east-1",
            now=moment,
        )
        self.assertEqual(
            object_headers["Authorization"],
            "AWS4-HMAC-SHA256 "
            "Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
            "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
            "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        )
        listing_headers = s3_backup._sign_request(
            "GET",
            "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J",
            {},
            s3_backup._EMPTY_SHA256,
            credentials,
            "us-east-1",
            now=moment,
        )
        self.assertEqual(
            listing_headers["Authorization"],
            "AWS4-HMAC-SHA256 "
            "Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
            "SignedHeaders=host;x-amz-content-sha256;x-amz-date,"
            "Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
        )

    def test_connection_proves_conditions_readback_and_cleans_both_objects(self):
        objects = {}
        seen = []
        copy_count = 0

        def handler(request):
            nonlocal copy_count
            seen.append(request)
            self.assert_signed(request)
            path = unquote(request.url.path)
            if request.method == "PUT" and "x-amz-copy-source" not in request.headers:
                self.assertEqual(request.headers["If-None-Match"], "*")
                objects[path] = request.read()
                return httpx.Response(200, headers={"ETag": '"source-etag"'})
            if request.method == "PUT":
                copy_count += 1
                signed = request.headers["Authorization"]
                self.assertIn("if-none-match", signed)
                self.assertIn("x-amz-copy-source", signed)
                self.assertIn("x-amz-copy-source-if-match", signed)
                self.assertEqual(request.headers["If-None-Match"], "*")
                self.assertEqual(request.headers["x-amz-copy-source-if-match"], '"source-etag"')
                if path in objects:
                    return httpx.Response(412)
                source = unquote(request.headers["x-amz-copy-source"])
                objects[path] = objects[source]
                return httpx.Response(200, content=self.COPY_RESULT)
            if request.method == "GET":
                return httpx.Response(200, content=objects[path])
            if request.method == "DELETE":
                objects.pop(path, None)
                return httpx.Response(204)
            raise AssertionError(request)

        with self.remote(handler) as guard:
            result = s3_backup.test_connection(self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(copy_count, 2)
        self.assertEqual(objects, {})
        self.assertEqual(len(seen), 6)
        self.assertEqual(guard.call_count, len(seen))

    def test_connection_rejects_server_without_destination_protection(self):
        objects = {}

        def handler(request):
            path = unquote(request.url.path)
            if request.method == "PUT" and "x-amz-copy-source" not in request.headers:
                objects[path] = request.read()
                return httpx.Response(200, headers={"ETag": '"source"'})
            if request.method == "PUT":
                source = unquote(request.headers["x-amz-copy-source"])
                objects[path] = objects[source]
                return httpx.Response(200, content=self.COPY_RESULT)
            if request.method == "GET":
                return httpx.Response(200, content=objects[path])
            if request.method == "DELETE":
                objects.pop(path, None)
                return httpx.Response(204)
            raise AssertionError(request)

        with self.remote(handler), self.assertRaisesRegex(s3_backup.S3Error, "overwrite"):
            s3_backup.test_connection(self.config)
        self.assertEqual(objects, {})

    def test_upload_uses_conditional_copy_full_verification_and_temp_cleanup(self):
        objects = {}
        copied_headers = None
        deleted = []

        def handler(request):
            nonlocal copied_headers
            self.assert_signed(request)
            path = unquote(request.url.path)
            if request.method == "PUT" and "x-amz-copy-source" not in request.headers:
                self.assertTrue(path.rsplit("/", 1)[-1].startswith(".alles-upload-"))
                self.assertEqual(request.headers["If-None-Match"], "*")
                self.assertEqual(
                    request.headers["X-Amz-Content-Sha256"],
                    hashlib.sha256(self.payload).hexdigest(),
                )
                objects[path] = request.read()
                return httpx.Response(200, headers={"ETag": '"opaque-source-id"'})
            if request.method == "PUT":
                copied_headers = dict(request.headers)
                source = unquote(request.headers["x-amz-copy-source"])
                objects[path] = objects[source]
                return httpx.Response(200, content=self.COPY_RESULT)
            if request.method == "GET":
                return httpx.Response(200, content=objects[path])
            if request.method == "DELETE":
                deleted.append(path)
                objects.pop(path, None)
                return httpx.Response(204)
            raise AssertionError(request)

        with self.remote(handler):
            result = s3_backup.upload_artifact(self.artifact, config=self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(result["size"], len(self.payload))
        self.assertEqual(result["sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(result["status_warning"], "")
        self.assertEqual(copied_headers["if-none-match"], "*")
        self.assertEqual(copied_headers["x-amz-copy-source-if-match"], '"opaque-source-id"')
        self.assertEqual(len(objects), 1)
        final_path, final_body = next(iter(objects.items()))
        self.assertEqual(final_path.rsplit("/", 1)[-1], result["name"])
        self.assertEqual(final_body, self.payload)
        self.assertEqual(len(deleted), 1)
        self.assertIn(".alles-upload-", deleted[0])

    def test_embedded_copy_error_is_rejected_and_temp_is_removed(self):
        objects = {}
        deleted = []

        def handler(request):
            path = unquote(request.url.path)
            if request.method == "PUT" and "x-amz-copy-source" not in request.headers:
                objects[path] = request.read()
                return httpx.Response(200, headers={"ETag": '"source"'})
            if request.method == "PUT":
                return httpx.Response(
                    200,
                    content=b"<Error><Code>InternalError</Code><Message>private</Message></Error>",
                )
            if request.method == "DELETE":
                deleted.append(path)
                objects.pop(path, None)
                return httpx.Response(204)
            raise AssertionError(request)

        with self.remote(handler), self.assertRaisesRegex(s3_backup.S3Error, "copy failed"):
            s3_backup.upload_artifact(self.artifact, config=self.config)
        self.assertEqual(objects, {})
        self.assertEqual(len(deleted), 1)

    def test_lost_copy_response_is_reconciled_by_exact_get(self):
        objects = {}
        copy_attempts = 0

        class BrokenCopyResponse(httpx.SyncByteStream):
            def __iter__(self):
                yield b"<CopyObjectResult>"
                raise httpx.ReadError("response lost")

        def handler(request):
            nonlocal copy_attempts
            path = unquote(request.url.path)
            if request.method == "PUT" and "x-amz-copy-source" not in request.headers:
                objects[path] = request.read()
                return httpx.Response(200, headers={"ETag": '"source"'})
            if request.method == "PUT":
                copy_attempts += 1
                source = unquote(request.headers["x-amz-copy-source"])
                objects[path] = objects[source]
                return httpx.Response(200, stream=BrokenCopyResponse())
            if request.method == "GET":
                return httpx.Response(200, content=objects[path])
            if request.method == "DELETE":
                objects.pop(path, None)
                return httpx.Response(204)
            raise AssertionError(request)

        with self.remote(handler):
            result = s3_backup.upload_artifact(self.artifact, config=self.config)
        self.assertEqual(copy_attempts, 1)
        self.assertIn("interrupted", result["status_warning"])
        self.assertEqual(list(objects.values()), [self.payload])

    def test_listing_is_bounded_paginated_and_filters_non_direct_keys(self):
        first = self.artifact_name("111111111111")
        second = self.artifact_name("222222222222")
        token = "next+/=token"
        seen_queries = []

        def page(contents, truncated, next_token=""):
            token_xml = (
                f"<NextContinuationToken>{next_token}</NextContinuationToken>" if next_token else ""
            )
            rows = "".join(
                "<Contents>"
                f"<Key>{key}</Key><LastModified>2026-07-12T01:02:03Z</LastModified>"
                f'<ETag>"opaque-{index}"</ETag><Size>{len(self.payload)}</Size>'
                "</Contents>"
                for index, key in enumerate(contents)
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                "<EncodingType>url</EncodingType>"
                f"<IsTruncated>{str(truncated).lower()}</IsTruncated>{token_xml}{rows}"
                "</ListBucketResult>"
            ).encode()

        def handler(request):
            self.assert_signed(request)
            seen_queries.append(dict(request.url.params))
            current = request.url.params.get("continuation-token", "")
            if not current:
                return httpx.Response(
                    200,
                    content=page(
                        (
                            f"private%2Falles%2F{first}",
                            f"private%2Falles%2Fnested%2F{second}",
                            f"private%2Falles%2F..%2F{second}",
                            f"other%2F{second}",
                        ),
                        True,
                        token,
                    ),
                )
            self.assertEqual(current, token)
            return httpx.Response(
                200,
                content=page((f"private%2Falles%2F{second}",), False),
            )

        with self.remote(handler) as guard:
            items = s3_backup.list_artifacts(config=self.config)
        self.assertEqual([item["name"] for item in items], [second, first])
        self.assertEqual(items[0]["size"], len(self.payload))
        self.assertEqual(len(seen_queries), 2)
        self.assertEqual(seen_queries[0]["encoding-type"], "url")
        self.assertEqual(seen_queries[0]["prefix"], "private/alles/alles-backup-")
        self.assertEqual(seen_queries[1]["continuation-token"], token)
        self.assertEqual(guard.call_count, 2)

    def test_listing_rejects_token_loops_entities_and_oversized_pages(self):
        loop = (
            b"<ListBucketResult><EncodingType>url</EncodingType>"
            b"<IsTruncated>true</IsTruncated>"
            b"<NextContinuationToken>same</NextContinuationToken></ListBucketResult>"
        )
        with self.subTest("token loop"):
            with self.remote(lambda _request: httpx.Response(200, content=loop)):
                with self.assertRaisesRegex(s3_backup.S3Error, "repeated"):
                    s3_backup.list_artifacts(config=self.config)

        entity = b'<!DOCTYPE x [<!ENTITY y "secret">]><ListBucketResult>&y;</ListBucketResult>'
        with self.subTest("entity"):
            with self.remote(lambda _request: httpx.Response(200, content=entity)):
                with self.assertRaisesRegex(s3_backup.S3Error, "unsafe"):
                    s3_backup.list_artifacts(config=self.config)

        with self.subTest("declared bound"):
            response = lambda _request: httpx.Response(  # noqa: E731
                200,
                headers={"Content-Length": str(s3_backup.MAX_LISTING_BYTES + 1)},
                content=b"",
            )
            with self.remote(response):
                with self.assertRaisesRegex(s3_backup.S3Error, "too large"):
                    s3_backup.list_artifacts(config=self.config)

    def test_download_is_private_bounded_validated_and_checksum_checked(self):
        name = self.artifact_name()
        output = self.root / "restore" / name

        def handler(request):
            self.assert_signed(request)
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            self.assertTrue(str(request.url).endswith(name))
            return httpx.Response(200, content=self.payload)

        with self.remote(handler):
            result = s3_backup.download_artifact(
                name,
                output,
                config=self.config,
                expected_size=len(self.payload),
                expected_sha256=hashlib.sha256(self.payload).hexdigest(),
            )
        self.assertEqual(output.read_bytes(), self.payload)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result["sha256"], hashlib.sha256(self.payload).hexdigest())

        wrong = self.root / "wrong.alles-backup"
        with self.remote(handler), self.assertRaisesRegex(s3_backup.S3Error, "checksum"):
            s3_backup.download_artifact(
                name,
                wrong,
                config=self.config,
                expected_sha256="0" * 64,
            )
        self.assertFalse(wrong.exists())
        self.assertEqual(list(self.root.glob(".wrong.alles-backup.*.partial")), [])

        too_large = lambda _request: httpx.Response(  # noqa: E731
            200,
            headers={"Content-Length": str(s3_backup.MAX_ARTIFACT_BYTES + 1)},
            content=b"",
        )
        bounded = self.root / "bounded.alles-backup"
        with self.remote(too_large), self.assertRaisesRegex(s3_backup.S3Error, "size"):
            s3_backup.download_artifact(name, bounded, config=self.config)
        self.assertFalse(bounded.exists())

    def test_transfer_limits_links_and_invalid_remote_container_fail_closed(self):
        with self.assertRaisesRegex(s3_backup.S3Error, "size limit"):
            s3_backup.upload_artifact(
                self.artifact,
                config=self.config,
                maximum=s3_backup.MAX_ARTIFACT_BYTES + 1,
            )

        sparse = self.root / "oversize.alles-backup"
        with sparse.open("wb") as handle:
            handle.truncate(s3_backup.MAX_ARTIFACT_BYTES + 1)
        with self.assertRaisesRegex(s3_backup.S3Error, "size is invalid"):
            s3_backup.upload_artifact(sparse, config=self.config)

        linked = self.root / "linked.alles-backup"
        try:
            linked.symlink_to(self.artifact)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaisesRegex(s3_backup.S3Error, "cannot be a link"):
                s3_backup.upload_artifact(linked, config=self.config)

        name = self.artifact_name()
        invalid = self.root / "invalid.alles-backup"
        with self.remote(lambda _request: httpx.Response(200, content=b"not encrypted")):
            with self.assertRaisesRegex(s3_backup.S3Error, "valid encrypted"):
                s3_backup.download_artifact(name, invalid, config=self.config)
        self.assertFalse(invalid.exists())

    def test_ssrf_redirects_and_remote_bodies_are_fail_closed(self):
        guard = mock.Mock(side_effect=ValueError("blocked-private-address"))
        handler = mock.Mock()
        with self.remote(handler, guard=guard):
            with self.assertRaisesRegex(s3_backup.S3Error, "address is blocked") as caught:
                s3_backup.list_artifacts(config=self.config)
        self.assertNotIn("blocked-private-address", str(caught.exception))
        handler.assert_not_called()

        private = "credential=remote-private-value"
        with self.remote(
            lambda _request: httpx.Response(
                307,
                headers={"Location": "https://elsewhere.example.test/private"},
                text=private,
            )
        ):
            with self.assertRaisesRegex(s3_backup.S3Error, "redirects") as caught:
                s3_backup.list_artifacts(config=self.config)
        self.assertNotIn(private, str(caught.exception))

        with self.remote(lambda _request: httpx.Response(500, text=private)):
            with self.assertRaisesRegex(s3_backup.S3Error, "status 500") as caught:
                s3_backup.list_artifacts(config=self.config)
        self.assertNotIn(private, str(caught.exception))

    def test_shared_lock_and_status_compare_prevent_config_races(self):
        ready = threading.Event()
        release = threading.Event()

        def hold_lock():
            with s3_backup._LOCK:
                ready.set()
                release.wait(5)

        thread = threading.Thread(target=hold_lock)
        thread.start()
        self.assertTrue(ready.wait(2))
        try:
            with self.assertRaises(s3_backup.S3BusyError):
                s3_backup.test_connection(self.config)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())

        s3_backup.save_config(self.config)
        old = s3_backup.load_config()
        changed = {
            **self.config,
            "endpoint": "https://new.example.test",
            "credentials": s3_backup._credentials_json("replacement", "new-private"),
        }
        s3_backup.save_config(changed)
        self.assertFalse(s3_backup._record_status(old, last_filename=self.artifact_name()))
        current = s3_backup.load_config()
        self.assertEqual(current["endpoint"], "https://new.example.test")
        self.assertEqual(current["last_filename"], "")


if __name__ == "__main__":
    unittest.main()
