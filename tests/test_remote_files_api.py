import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import httpx
from fastapi.responses import FileResponse

from core.database import StorageLocation
from routes import files as files_routes
from services import fileversions, internal_paths, storage_backends, webdav_locations
from tests._client import ApiTest
from tests.test_webdav_locations import empty_listing, listing


class RemoteFilesApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add(
            StorageLocation(
                id="dav-files",
                name="remote files",
                kind="webdav",
                access="managed",
                endpoint="https://dav.example.test/dav",
                secret=json.dumps({"username": "me", "password": "secret"}),
                enabled=True,
            )
        )
        db.commit()
        db.close()
        self.remote = {
            "file.txt": b"hello",
            "active.html": b"<script>document.body.dataset.executed = 'yes'</script>",
        }
        self.remote_etags = {
            "file.txt": '"remote"',
            "active.html": '"active"',
        }
        self.remote_revision = 1
        self.requests = []

        def handler(request):
            self.requests.append(request)
            path = request.url.path.removeprefix("/dav/")
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={
                        "Allow": "OPTIONS, PROPFIND, GET, PUT, DELETE, MKCOL, COPY, MOVE",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "PROPFIND":
                body = (
                    listing().replace(b'"child-etag"', self.remote_etags["file.txt"].encode())
                    if "file.txt" in self.remote_etags
                    else empty_listing()
                )
                return httpx.Response(207, content=body)
            if request.method == "GET":
                body = self.remote.get(path)
                if body is None:
                    return httpx.Response(404)
                requested_range = request.headers.get("range")
                if requested_range:
                    start_raw, end_raw = requested_range.removeprefix("bytes=").split("-", 1)
                    start, end = int(start_raw), min(int(end_raw), len(body) - 1)
                    content = body[start : end + 1]
                    return httpx.Response(
                        206,
                        content=content,
                        headers={
                            "Content-Length": str(len(content)),
                            "Content-Range": f"bytes {start}-{end}/{len(body)}",
                            "ETag": self.remote_etags[path],
                        },
                    )
                return httpx.Response(
                    200,
                    content=body,
                    headers={"ETag": self.remote_etags[path]},
                )
            if request.method == "PUT":
                current_etag = self.remote_etags.get(path)
                created = current_etag is None
                if request.headers.get("if-match") not in {None, current_etag}:
                    return httpx.Response(412)
                if request.headers.get("if-none-match") == "*" and path in self.remote:
                    return httpx.Response(412)
                body = request.read()
                self.remote[path] = body
                self.remote_revision += 1
                self.remote_etags[path] = f'"remote-{self.remote_revision}"'
                return httpx.Response(
                    201 if created else 204,
                    headers={"ETag": self.remote_etags[path]},
                )
            if request.method == "MKCOL":
                return httpx.Response(201)
            if request.method == "DELETE":
                current_etag = self.remote_etags.get(path)
                if request.headers.get("if-match") not in {None, current_etag}:
                    return httpx.Response(412)
                self.remote.pop(path, None)
                self.remote_etags.pop(path, None)
                return httpx.Response(204)
            raise AssertionError((request.method, str(request.url)))

        webdav_locations.CLIENT_FACTORY = lambda _row, _credentials: httpx.Client(
            transport=httpx.MockTransport(handler)
        )
        self.resolve_safe = patch(
            "services.net_guard.resolve_safe_url",
            side_effect=lambda url: (urlparse(url), ("192.168.0.2",)),
        )
        self.resolve_safe.start()

    def tearDown(self):
        webdav_locations.CLIENT_FACTORY = None
        self.resolve_safe.stop()
        super().tearDown()

    def test_remote_list_read_raw_upload_and_mkdir(self):
        listed = self.client.get("/api/files/list?location_id=dav-files")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["path"], "file.txt")

        read = self.client.get("/api/files/read?location_id=dav-files&path=file.txt")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["content"], "hello")
        self.assertEqual(read.json()["etag"], '"remote"')

        raw = self.client.get("/api/files/raw?location_id=dav-files&path=file.txt")
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.content, b"hello")

        upload = self.client.post(
            "/api/files/upload",
            data={"location_id": "dav-files", "path": ""},
            files={"file": ("new.txt", b"new bytes", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(self.remote["new.txt"], b"new bytes")
        self.assertEqual(upload.json()["normalized_path"], "new.txt")

        made = self.client.post(
            "/api/files/mkdir",
            json={"location_id": "dav-files", "path": "folder"},
        )
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["normalized_path"], "folder")

    def test_remote_mkdir_rejects_a_read_only_location_before_network_io(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        location.access = "read_only"
        db.commit()
        db.close()
        request_count = len(self.requests)

        response = self.client.post(
            "/api/files/mkdir",
            json={"location_id": "dav-files", "path": "blocked"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("read-only", response.json()["detail"])
        self.assertEqual(len(self.requests), request_count)

    def test_small_remote_text_preview_allows_a_full_200_response(self):
        with patch(
            "services.webdav_locations.read_prefix",
            side_effect=AssertionError("small previews must not require range support"),
        ):
            response = self.client.get(
                "/api/files/read",
                params={"location_id": "dav-files", "path": "file.txt"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["content"], "hello")
        request = next(request for request in self.requests if request.method == "GET")
        self.assertNotIn("range", request.headers)
        self.assertEqual(request.headers["if-match"], '"remote"')

    def test_remote_office_preview_materializes_and_cleans_up_the_file(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        temporary = storage_backends.temporary_path(location, "file.txt")
        db.close()

        response = self.client.get(
            "/api/files/preview",
            params={"location_id": "dav-files", "path": "file.txt"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"kind": "text", "text": "hello"})
        self.assertFalse(temporary.exists())

    def test_missing_remote_paths_keep_the_not_found_http_contract(self):
        cases = (
            ("/api/files/list", "listdir"),
            ("/api/files/read", "read_text"),
            ("/api/files/preview", "download"),
            ("/api/files/raw", "download"),
        )
        for endpoint, operation in cases:
            with (
                self.subTest(endpoint=endpoint),
                patch.object(
                    storage_backends,
                    operation,
                    side_effect=storage_backends.StorageNotFoundError("remote path not found"),
                ),
            ):
                response = self.client.get(
                    endpoint,
                    params={"location_id": "dav-files", "path": "missing.txt"},
                )
            self.assertEqual(response.status_code, 404, response.text)

    def test_dispatcher_preserves_an_existing_target_when_webdav_download_fails(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        target = storage_backends.temporary_path(location, "existing.txt")
        target.write_bytes(b"verified old copy")
        seen = []

        def fail_download(_location, _path, destination, **_kwargs):
            seen.append(destination.read_bytes() if destination.exists() else None)
            raise webdav_locations.WebDAVLocationError("network lost")

        try:
            with patch.object(webdav_locations, "download", side_effect=fail_download):
                with self.assertRaisesRegex(storage_backends.StorageBackendError, "network lost"):
                    storage_backends.download(location, "file.txt", target)
            self.assertEqual(seen, [b"verified old copy"])
            self.assertEqual(target.read_bytes(), b"verified old copy")
        finally:
            storage_backends.remove_temporary(target)
            db.close()

    def test_strict_delete_rejects_a_missing_verified_local_source(self):
        expected = {"kind": "file", "size": 5, "count": 1, "checksum": "abc"}
        verified = {**expected, "type": "file"}
        with tempfile.TemporaryDirectory() as root_text:
            row = SimpleNamespace(
                id="local",
                kind="local",
                access="managed",
                root_path=root_text,
            )
            with self.assertRaisesRegex(
                storage_backends.StorageNotFoundError,
                "source disappeared before delete",
            ):
                storage_backends.delete_tree(
                    row,
                    "gone.txt",
                    expected=expected,
                    verified_meta=verified,
                    missing_ok=False,
                )

    def test_strict_delete_rejects_a_webdav_delete_404(self):
        row = SimpleNamespace(id="dav", kind="webdav", access="managed")
        expected = {"kind": "file", "size": 5, "count": 1, "checksum": "abc"}
        verified = {**expected, "type": "file", "etag": '"verified"'}
        with patch.object(
            webdav_locations,
            "delete",
            side_effect=webdav_locations.WebDAVNotFoundError("status 404"),
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageNotFoundError,
                "source disappeared before delete",
            ):
                storage_backends.delete_tree(
                    row,
                    "gone.txt",
                    expected=expected,
                    verified_meta=verified,
                    missing_ok=False,
                )

    def test_strict_delete_rejects_a_missing_s3_file(self):
        row = SimpleNamespace(id="s3", kind="s3", access="managed")
        expected = {"kind": "file", "size": 5, "count": 1, "checksum": "abc"}
        verified = {**expected, "type": "file", "etag": '"verified"', "version_id": ""}
        with patch.object(
            storage_backends.s3_locations,
            "delete",
            side_effect=storage_backends.s3_locations.S3NotFoundError("missing"),
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageNotFoundError,
                "source disappeared before delete",
            ):
                storage_backends.delete_tree(
                    row,
                    "gone.txt",
                    expected=expected,
                    verified_meta=verified,
                    missing_ok=False,
                )

    def test_strict_delete_rejects_a_missing_s3_manifest_child_before_any_delete(self):
        row = SimpleNamespace(id="s3", kind="s3", access="managed")
        expected = {"kind": "dir", "size": 10, "count": 2, "checksum": "abc"}
        missing = {
            "path": "folder/missing.txt",
            "type": "file",
            "etag": '"missing"',
            "version_id": "",
        }
        present = {
            "path": "folder/present.txt",
            "type": "file",
            "etag": '"present"',
            "version_id": "",
        }
        verified = {
            **expected,
            "type": "dir",
            "manifest": [missing, present],
            "directory_markers": [],
        }
        deleted = []

        def delete(_row, path, **_kwargs):
            if path == missing["path"]:
                raise storage_backends.s3_locations.S3NotFoundError("missing")
            deleted.append(path)

        with (
            patch.object(storage_backends, "listdir", return_value={"items": [present]}),
            patch.object(
                storage_backends.s3_locations,
                "directory_marker_metadata",
                return_value=None,
            ),
            patch.object(storage_backends.s3_locations, "delete", side_effect=delete),
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "source changed; delete stopped",
            ):
                storage_backends.delete_tree(
                    row,
                    "folder",
                    expected=expected,
                    verified_meta=verified,
                    missing_ok=False,
                )

        self.assertEqual(deleted, [])

    def test_strict_delete_rejects_a_missing_verified_s3_directory_marker(self):
        row = SimpleNamespace(id="s3", kind="s3", access="managed")
        expected = {"kind": "dir", "size": 0, "count": 0, "checksum": "abc"}
        marker = {"path": "folder", "etag": '"marker"', "version_id": ""}
        verified = {
            **expected,
            "type": "dir",
            "manifest": [],
            "directory_markers": [marker],
        }
        with (
            patch.object(storage_backends, "listdir", return_value={"items": []}),
            patch.object(
                storage_backends.s3_locations,
                "directory_marker_metadata",
                return_value=marker,
            ),
            patch.object(
                storage_backends.s3_locations,
                "delete",
                side_effect=storage_backends.s3_locations.S3NotFoundError("missing"),
            ),
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageNotFoundError,
                "source disappeared before delete",
            ):
                storage_backends.delete_tree(
                    row,
                    "folder",
                    expected=expected,
                    verified_meta=verified,
                    missing_ok=False,
                )

    def test_unknown_receipt_size_stays_unknown_and_is_bounded(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        operation_id = "11111111-1111-1111-1111-111111111111"
        destination = "folder/owned.txt"
        expected = {"kind": "file", "size": 5, "checksum": "abc"}
        payload = storage_backends._operation_receipt_payload(  # noqa: SLF001
            location,
            destination,
            operation_id,
            expected,
        )
        receipt_path = storage_backends._operation_receipt_path(  # noqa: SLF001
            destination,
            operation_id,
        )
        calls = []

        def download_receipt(_location, path, target, **kwargs):
            self.assertEqual(path, receipt_path)
            self.assertIsNone(kwargs["expected_size"])
            self.assertEqual(kwargs["max_bytes"], 8192)
            target.write_text(json.dumps(payload), encoding="utf-8")
            calls.append(kwargs)
            return {"size": target.stat().st_size, "etag": '"receipt"'}

        try:
            with (
                patch.object(
                    storage_backends,
                    "item",
                    return_value={"type": "file", "size": None, "etag": '"receipt"'},
                ),
                patch.object(storage_backends, "download", side_effect=download_receipt),
            ):
                self.assertEqual(
                    storage_backends._read_operation_receipt(  # noqa: SLF001
                        location,
                        receipt_path,
                    ),
                    payload,
                )
                identity = storage_backends._operation_receipt_identity(  # noqa: SLF001
                    location,
                    destination,
                    operation_id,
                    expected,
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(identity["etag"], '"receipt"')
        finally:
            db.close()

    def test_remote_upload_runs_blocking_storage_work_in_a_thread(self):
        calls = []

        async def run_in_thread(func, *args, **kwargs):
            calls.append(func)
            return func(*args, **kwargs)

        with patch.object(files_routes, "run_in_threadpool", run_in_thread, create=True):
            response = self.client.post(
                "/api/files/upload",
                data={"location_id": "dav-files", "path": ""},
                files={"file": ("threaded.txt", b"threaded bytes", "text/plain")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.remote["threaded.txt"], b"threaded bytes")

    def test_remote_download_preserves_the_storage_filename(self):
        with patch.object(
            storage_backends,
            "download",
            wraps=storage_backends.download,
        ) as remote_download:
            response = self.client.get(
                "/api/files/raw",
                params={"location_id": "dav-files", "path": "file.txt", "download": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('filename="file.txt"', response.headers["content-disposition"])
        self.assertEqual(remote_download.call_args.kwargs["max_bytes"], 512 * 1024 * 1024)

    def test_remote_preview_bounds_materialized_content(self):
        with patch.object(
            storage_backends,
            "download",
            wraps=storage_backends.download,
        ) as remote_download:
            response = self.client.get(
                "/api/files/preview",
                params={"location_id": "dav-files", "path": "file.txt"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(remote_download.call_args.kwargs["max_bytes"], fileversions.CAP_BYTES)

    def test_remote_active_content_is_forced_to_a_sandboxed_attachment(self):
        self.assertTrue(files_routes._is_active_media_type("application/atom+xml"))
        response = self.client.get(
            "/api/files/raw",
            params={"location_id": "dav-files", "path": "active.html"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(
            response.headers["content-security-policy"],
            "sandbox; default-src 'none'",
        )

    def test_remote_raw_response_cleans_transfer_and_sidecars_when_delivery_aborts(self):
        response_type = getattr(files_routes, "TemporaryFileResponse", None)
        self.assertIsNotNone(response_type)
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        target = storage_backends.temporary_path(location, "large.bin")
        target.write_bytes(b"large transfer")
        partial = internal_paths.artifact_sibling(target, "download", suffix=".partial")
        identity = internal_paths.artifact_sibling(target, "download", suffix=".json")
        partial.write_bytes(b"partial")
        identity.write_text("{}", encoding="utf-8")
        db.close()

        async def fail_delivery(_response, _scope, _receive, _send):
            raise RuntimeError("client disconnected")

        response = response_type(str(target), cleanup_path=target)
        with patch.object(FileResponse, "__call__", new=fail_delivery):
            with self.assertRaisesRegex(RuntimeError, "client disconnected"):
                asyncio.run(response({}, None, None))

        self.assertFalse(target.exists())
        self.assertFalse(partial.exists())
        self.assertFalse(identity.exists())

    def test_remote_text_preview_reads_only_the_configured_prefix(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        with (
            patch(
                "services.storage_backends.item",
                return_value={"type": "file", "size": 201, "etag": '"large"'},
            ),
            patch(
                "services.webdav_locations.read_prefix",
                return_value={
                    "content": b"A" * 200,
                    "size": 201,
                    "etag": '"large"',
                },
                create=True,
            ) as read_prefix,
        ):
            result = storage_backends.read_text(location, "large.txt", limit=200)

        self.assertEqual(result["content"], "A" * 200)
        self.assertEqual(result["size"], 201)
        self.assertTrue(result["truncated"])
        read_prefix.assert_called_once_with(
            location,
            "large.txt",
            200,
            expected_etag='"large"',
            expected_size=201,
        )
        db.close()

    def test_unknown_remote_text_size_uses_a_bounded_full_download(self):
        db = self.db()
        location = db.get(StorageLocation, "dav-files")
        calls = []

        def bounded_download(_location, _path, target, **kwargs):
            self.assertIsNone(kwargs["expected_size"])
            self.assertEqual(kwargs["max_bytes"], 8)
            target.write_bytes(b"unknown")
            calls.append(kwargs)
            return {"size": 7, "checksum": "", "etag": '"unknown"'}

        try:
            with (
                patch.object(
                    storage_backends,
                    "item",
                    return_value={"type": "file", "size": None, "etag": '"unknown"'},
                ),
                patch.object(storage_backends, "download", side_effect=bounded_download),
            ):
                result = storage_backends.read_text(location, "unknown.txt", limit=8)

            self.assertEqual(result["content"], "unknown")
            self.assertEqual(result["size"], 7)
            self.assertFalse(result["truncated"])
            self.assertEqual(len(calls), 1)
        finally:
            db.close()

    def test_remote_overwrite_is_versioned_and_can_be_restored(self):
        upload = self.client.post(
            "/api/files/upload",
            data={
                "location_id": "dav-files",
                "path": "",
                "expected_etag": '"remote"',
            },
            files={"file": ("file.txt", b"world", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(self.remote["file.txt"], b"world")

        versions = self.client.get(
            "/api/files/versions",
            params={"location_id": "dav-files", "path": "file.txt"},
        )
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertEqual(len(versions.json()), 1)

        restored = self.client.post(
            "/api/files/versions/restore",
            json={
                "location_id": "dav-files",
                "path": "file.txt",
                "id": versions.json()[0]["id"],
            },
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.remote["file.txt"], b"hello")

    def test_remote_version_can_restore_an_externally_deleted_file(self):
        upload = self.client.post(
            "/api/files/upload",
            data={
                "location_id": "dav-files",
                "path": "",
                "expected_etag": '"remote"',
            },
            files={"file": ("file.txt", b"world", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        version = self.client.get(
            "/api/files/versions",
            params={"location_id": "dav-files", "path": "file.txt"},
        ).json()[0]
        self.remote.pop("file.txt")
        self.remote_etags.pop("file.txt")

        with patch.object(
            storage_backends,
            "item",
            side_effect=storage_backends.StorageNotFoundError("not found"),
        ):
            restored = self.client.post(
                "/api/files/versions/restore",
                json={"location_id": "dav-files", "path": "file.txt", "id": version["id"]},
            )

        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.remote["file.txt"], b"hello")

    def test_remote_version_restore_refuses_an_existing_file_without_a_stable_etag(self):
        with tempfile.TemporaryDirectory(prefix="alles-remote-version-") as tmp:
            source = Path(tmp) / "stored-version.txt"
            source.write_bytes(b"older")
            db = self.db()
            version = fileversions.snapshot(db, "file.txt", source, "dav-files")
            version_id = version.id
            db.close()
        metadata = {"type": "file", "path": "file.txt", "size": 5, "etag": ""}
        with (
            patch.object(storage_backends, "item", return_value=metadata),
            patch.object(storage_backends, "download") as download,
            patch.object(storage_backends, "upload") as upload,
        ):
            restored = self.client.post(
                "/api/files/versions/restore",
                json={"location_id": "dav-files", "path": "file.txt", "id": version_id},
            )

        self.assertEqual(restored.status_code, 409, restored.text)
        self.assertIn("stable ETag", restored.text)
        download.assert_not_called()
        upload.assert_not_called()

    def test_remote_overwrite_without_etag_is_create_only(self):
        upload = self.client.post(
            "/api/files/upload",
            data={"location_id": "dav-files", "path": ""},
            files={"file": ("file.txt", b"stale overwrite", "text/plain")},
        )

        self.assertEqual(upload.status_code, 409, upload.text)
        self.assertEqual(self.remote["file.txt"], b"hello")
        versions = self.client.get(
            "/api/files/versions",
            params={"location_id": "dav-files", "path": "file.txt"},
        )
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertEqual(versions.json(), [])

    def test_remote_overwrite_rejects_a_file_too_large_to_version(self):
        with (
            patch.object(fileversions, "CAP_BYTES", 4),
            patch.object(storage_backends, "upload", wraps=storage_backends.upload) as upload,
        ):
            response = self.client.post(
                "/api/files/upload",
                data={
                    "location_id": "dav-files",
                    "path": "",
                    "expected_etag": '"remote"',
                },
                files={"file": ("file.txt", b"replacement", "text/plain")},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("too large to version", response.text)
        self.assertEqual(self.remote["file.txt"], b"hello")
        upload.assert_not_called()

    def test_unknown_remote_size_is_versioned_before_overwrite_and_restore(self):
        real_item = storage_backends.item

        def item_without_size(location, path):
            result = dict(real_item(location, path))
            if result.get("type") == "file":
                result["size"] = None
            return result

        with patch.object(storage_backends, "item", side_effect=item_without_size):
            upload = self.client.post(
                "/api/files/upload",
                data={
                    "location_id": "dav-files",
                    "path": "",
                    "expected_etag": '"remote"',
                },
                files={"file": ("file.txt", b"world", "text/plain")},
            )
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertEqual(self.remote["file.txt"], b"world")

        versions = self.client.get(
            "/api/files/versions",
            params={"location_id": "dav-files", "path": "file.txt"},
        )
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertEqual(len(versions.json()), 1)

        with patch.object(storage_backends, "item", side_effect=item_without_size):
            restored = self.client.post(
                "/api/files/versions/restore",
                json={
                    "location_id": "dav-files",
                    "path": "file.txt",
                    "id": versions.json()[0]["id"],
                },
            )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.remote["file.txt"], b"hello")

    def test_restore_keeps_the_selected_oldest_version_when_history_is_full(self):
        with tempfile.TemporaryDirectory() as version_root:
            root = Path(version_root)
            source = root / "source.txt"
            versions = root / "versions"
            versions.mkdir()
            with patch.object(fileversions, "versions_dir", return_value=versions):
                db = self.db()
                selected = None
                for index in range(fileversions.KEEP):
                    source.write_bytes(f"version-{index:02d}".encode())
                    saved = fileversions.snapshot(db, "file.txt", source, "dav-files")
                    if index == 0:
                        selected = saved
                self.assertIsNotNone(selected)
                selected_id = selected.id
                db.close()

                restored = self.client.post(
                    "/api/files/versions/restore",
                    json={
                        "location_id": "dav-files",
                        "path": "file.txt",
                        "id": selected_id,
                    },
                )

        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.remote["file.txt"], b"version-00")


if __name__ == "__main__":
    import unittest

    unittest.main()
