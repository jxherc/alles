import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from services import s3_locations

LIST_V2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><KeyCount>2</KeyCount><MaxKeys>1000</MaxKeys>
  <Contents><Key>root/note.txt</Key><LastModified>2026-07-15T10:00:00Z</LastModified>
    <ETag>\"note-etag\"</ETag><Size>5</Size></Contents>
  <CommonPrefixes><Prefix>root/folder/</Prefix></CommonPrefixes>
</ListBucketResult>"""

LIST_V2_PAGE_ONE = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><KeyCount>1</KeyCount><MaxKeys>1</MaxKeys>
  <NextContinuationToken>page-2-proof</NextContinuationToken>
  <Contents><Key>root/first.txt</Key><ETag>"first"</ETag><Size>1</Size></Contents>
</ListBucketResult>"""

LIST_V2_PAGE_TWO = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><KeyCount>1</KeyCount><MaxKeys>1</MaxKeys>
  <Contents><Key>root/second.txt</Key><ETag>"second"</ETag><Size>1</Size></Contents>
</ListBucketResult>"""

LIST_VERSIONS = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><MaxKeys>1000</MaxKeys>
  <Version><Key>root/note.txt</Key><VersionId>v-2</VersionId><IsLatest>true</IsLatest>
    <LastModified>2026-07-15T10:00:00Z</LastModified><ETag>\"note-etag\"</ETag><Size>5</Size></Version>
  <CommonPrefixes><Prefix>root/folder/</Prefix></CommonPrefixes>
</ListVersionsResult>"""

LIST_VERSIONS_WITH_GHOST_DIRECTORY = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><MaxKeys>1000</MaxKeys>
  <Version><Key>root/note.txt</Key><VersionId>null</VersionId><IsLatest>true</IsLatest>
    <LastModified>2026-07-15T10:00:00Z</LastModified><ETag>"note-etag"</ETag><Size>5</Size></Version>
  <CommonPrefixes><Prefix>root/deleted-folder/</Prefix></CommonPrefixes>
</ListVersionsResult>"""

VERSIONING_ENABLED = b"""<?xml version="1.0" encoding="UTF-8"?>
<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Status>Enabled</Status>
</VersioningConfiguration>"""

VERSIONING_UNCONFIGURED = b"""<?xml version="1.0" encoding="UTF-8"?>
<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/" />"""

LIST_VERSIONS_PAGE_ONE = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><MaxKeys>1</MaxKeys>
  <NextKeyMarker>root/note.txt</NextKeyMarker><NextVersionIdMarker>version-older</NextVersionIdMarker>
  <Version><Key>root/note.txt</Key><VersionId>version-latest</VersionId><IsLatest>true</IsLatest>
    <LastModified>2026-07-15T10:00:00Z</LastModified><ETag>"note-etag"</ETag><Size>5</Size></Version>
</ListVersionsResult>"""

LIST_VERSIONS_PAGE_TWO = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><MaxKeys>1</MaxKeys>
  <Version><Key>root/note.txt</Key><VersionId>version-older</VersionId><IsLatest>false</IsLatest>
    <LastModified>2026-07-14T10:00:00Z</LastModified><ETag>"older-etag"</ETag><Size>5</Size></Version>
</ListVersionsResult>"""

LIST_UNKNOWN_AND_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>files</Name><Prefix>root/</Prefix><KeyCount>2</KeyCount><MaxKeys>1000</MaxKeys>
  <Contents><Key>root/unknown.bin</Key><ETag>"unknown"</ETag></Contents>
  <Contents><Key>root/empty.bin</Key><ETag>"empty"</ETag><Size>0</Size></Contents>
</ListBucketResult>"""


class S3LocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.row = SimpleNamespace(
            id="s3-1",
            endpoint="https://s3.example.test",
            bucket="files",
            prefix="root",
            access="managed",
            config=json.dumps({"region": "us-east-1", "addressing_style": "path"}),
            secret=json.dumps(
                {"access_key_id": "test-key", "secret_access_key": "test-secret"},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        self.safe = patch("services.net_guard.assert_safe_url", return_value=None)
        self.safe.start()

    def tearDown(self):
        s3_locations.CLIENT_FACTORY = None
        self.safe.stop()
        self.tmp.cleanup()

    def client(self, handler):
        s3_locations.CLIENT_FACTORY = lambda _config: httpx.Client(
            transport=httpx.MockTransport(handler)
        )

    def test_capabilities_and_versioned_listing(self):
        def handler(request):
            query = request.url.query.decode()
            if "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_ENABLED)
            if "versions=" in query:
                return httpx.Response(200, content=LIST_VERSIONS)
            return httpx.Response(200, content=LIST_V2)

        self.client(handler)
        capability = s3_locations.capabilities(self.row)
        self.assertTrue(capability["ok"])
        self.assertTrue(capability["supports_versions"])
        self.assertTrue(capability["non_atomic_move"])

        result = s3_locations.listdir(self.row)
        self.assertTrue(result["version_ids"])
        self.assertEqual([item["type"] for item in result["items"]], ["dir", "file"])
        note = result["items"][1]
        self.assertEqual(note["path"], "note.txt")
        self.assertEqual(note["etag"], '"note-etag"')
        self.assertEqual(note["version_id"], "v-2")

    def test_listing_fails_closed_when_enabled_version_history_is_unavailable(self):
        def handler(request):
            if "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_ENABLED)
            if "versions=" in request.url.query.decode():
                return httpx.Response(501)
            return httpx.Response(200, content=LIST_V2)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "status 501"):
            s3_locations.listdir(self.row)

    def test_listing_survives_missing_bucket_versioning_permission(self):
        version_listing_requested = False

        def handler(request):
            nonlocal version_listing_requested
            if "versioning" in request.url.params:
                return httpx.Response(403)
            if "versions=" in request.url.query.decode():
                version_listing_requested = True
            return httpx.Response(200, content=LIST_V2)

        self.client(handler)
        result = s3_locations.listdir(self.row)

        self.assertFalse(result["version_ids"])
        self.assertEqual([item["path"] for item in result["items"]], ["folder", "note.txt"])
        self.assertFalse(version_listing_requested)

    def test_successful_version_listing_does_not_enable_unversioned_bucket(self):
        version_listing_requested = False

        def handler(request):
            nonlocal version_listing_requested
            if "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_UNCONFIGURED)
            if "versions=" in request.url.query.decode():
                version_listing_requested = True
                return httpx.Response(200, content=LIST_VERSIONS_WITH_GHOST_DIRECTORY)
            return httpx.Response(200, content=LIST_V2)

        self.client(handler)
        self.assertFalse(s3_locations.capabilities(self.row)["supports_versions"])
        result = s3_locations.listdir(self.row)

        self.assertFalse(result["version_ids"])
        self.assertFalse(version_listing_requested)

    def test_version_history_does_not_create_ghost_directories_or_null_versions(self):
        live_without_folder = LIST_V2.replace(
            b"  <CommonPrefixes><Prefix>root/folder/</Prefix></CommonPrefixes>\n", b""
        )

        def handler(request):
            if "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_ENABLED)
            if "versions=" in request.url.query.decode():
                return httpx.Response(200, content=LIST_VERSIONS_WITH_GHOST_DIRECTORY)
            return httpx.Response(200, content=live_without_folder)

        self.client(handler)
        result = s3_locations.listdir(self.row)

        self.assertEqual([item["path"] for item in result["items"]], ["note.txt"])
        self.assertEqual(result["items"][0]["version_id"], "")

    def test_null_version_header_uses_the_unversioned_delete_path(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "GET" and "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_UNCONFIGURED)
            if request.method == "HEAD" and len(requests) == 1:
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "null",
                    },
                )
            if request.method == "DELETE":
                self.assertIsNone(request.url.params.get("versionId"))
                return httpx.Response(204)
            if request.method == "HEAD":
                return httpx.Response(404)
            raise AssertionError(request.method)

        self.client(handler)
        s3_locations.delete(self.row, "note.txt", expected_etag='"same"')

        self.assertEqual(
            [request.method for request in requests], ["HEAD", "GET", "DELETE", "HEAD"]
        )

    def test_versioning_state_distinguishes_enabled_suspended_and_unversioned(self):
        documents = {
            "enabled": b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>',
            "suspended": b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Suspended</Status></VersioningConfiguration>',
            "unversioned": b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"/>',
        }
        for expected, document in documents.items():
            requests = []

            def handler(request, payload=document):
                requests.append(request)
                return httpx.Response(200, content=payload)

            self.client(handler)
            self.assertEqual(s3_locations.versioning_state(self.row), expected)
            self.assertEqual(requests[0].method, "GET")
            self.assertIn("versioning=", requests[0].url.query.decode())

    def test_mkdir_refuses_versioned_bucket_before_creating_a_marker(self):
        requests = []

        def handler(request):
            requests.append(request)
            if "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_ENABLED)
            raise AssertionError("folder marker must not be created")

        self.client(handler)
        with self.assertRaisesRegex(
            s3_locations.S3LocationError,
            "folder creation is unavailable",
        ):
            s3_locations.mkdir(self.row, "folder")

        self.assertEqual([request.method for request in requests], ["GET"])

    def test_listing_distinguishes_an_unknown_size_from_a_real_zero(self):
        config = s3_locations._config(self.row)

        items, token = s3_locations._parse_page(
            config,
            LIST_UNKNOWN_AND_EMPTY,
            "",
            versions=False,
        )

        self.assertEqual(token, "")
        by_path = {item["path"]: item for item in items}
        self.assertIsNone(by_path["unknown.bin"]["size"])
        self.assertEqual(by_path["empty.bin"]["size"], 0)

    def test_list_objects_v2_uses_the_continuation_token_contract(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, content=LIST_V2_PAGE_ONE)
            self.assertEqual(request.url.params.get("continuation-token"), "page-2-proof")
            self.assertIsNone(request.url.params.get("continuation-marker"))
            return httpx.Response(200, content=LIST_V2_PAGE_TWO)

        self.client(handler)
        items = s3_locations._list(s3_locations._config(self.row), "", versions=False)

        self.assertEqual(len(requests), 2)
        self.assertEqual([item["path"] for item in items], ["first.txt", "second.txt"])

    def test_version_listing_sends_both_pagination_markers(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, content=LIST_VERSIONS_PAGE_ONE)
            self.assertEqual(request.url.params.get("key-marker"), "root/note.txt")
            self.assertEqual(request.url.params.get("version-id-marker"), "version-older")
            return httpx.Response(200, content=LIST_VERSIONS_PAGE_TWO)

        self.client(handler)
        result = s3_locations._list(s3_locations._config(self.row), "", versions=True)

        self.assertEqual(len(requests), 2)
        note = next(item for item in result if item["path"] == "note.txt")
        self.assertEqual(note["version_id"], "version-latest")

    def test_directory_marker_metadata_returns_its_head_verified_version(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                headers={
                    "Content-Length": "0",
                    "ETag": '"marker"',
                    "x-amz-version-id": "marker-version",
                },
            )

        self.client(handler)
        result = s3_locations.directory_marker_metadata(self.row, "folder")

        self.assertEqual(requests[0].method, "HEAD")
        self.assertTrue(requests[0].url.path.endswith("/root/folder/"))
        self.assertEqual(result["etag"], '"marker"')
        self.assertEqual(result["version_id"], "marker-version")

    def test_directory_marker_metadata_accepts_an_absent_optional_marker(self):
        self.client(lambda _request: httpx.Response(404))

        self.assertIsNone(s3_locations.directory_marker_metadata(self.row, "folder"))

    def test_resume_uses_range_only_after_head_proves_support(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "11",
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.headers.get("range"), "bytes=5-")
                return httpx.Response(
                    206,
                    content=b" world",
                    headers={
                        "Content-Range": "bytes 5-10/11",
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "note.txt"
        partial, identity = s3_locations._partial_paths(target)
        partial.write_bytes(b"hello")
        identity.write_text(
            json.dumps(
                {"etag": '"v1"', "version_id": "version-1", "size": 11},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        result = s3_locations.download(self.row, "note.txt", target, resume=True)
        self.assertEqual(target.read_bytes(), b"hello world")
        self.assertEqual(result["version_id"], "version-1")
        self.assertEqual([request.method for request in requests], ["HEAD", "GET"])

    def test_resume_rejects_a_partial_response_without_content_range(self):
        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "11",
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.headers.get("range"), "bytes=5-")
                return httpx.Response(
                    206,
                    content=b" world",
                    headers={
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "note.txt"
        partial, identity = s3_locations._partial_paths(target)
        partial.write_bytes(b"hello")
        identity.write_text(
            json.dumps(
                {"etag": '"v1"', "version_id": "version-1", "size": 11},
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            s3_locations.S3LocationError,
            "download range",
        ):
            s3_locations.download(self.row, "note.txt", target, resume=True)
        self.assertFalse(partial.exists())
        self.assertFalse(identity.exists())

    def test_resume_discards_a_partial_from_an_older_object_version(self):
        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"new"',
                        "x-amz-version-id": "version-new",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                self.assertIsNone(request.headers.get("range"))
                return httpx.Response(
                    200,
                    content=b"fresh",
                    headers={
                        "ETag": '"new"',
                        "x-amz-version-id": "version-new",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "note.txt"
        partial, identity = s3_locations._partial_paths(target)
        partial.write_bytes(b"stale")
        identity.write_text(
            json.dumps({"etag": '"old"', "version_id": "version-old", "size": 5}),
            encoding="utf-8",
        )
        s3_locations.download(self.row, "note.txt", target, resume=True)
        self.assertEqual(target.read_bytes(), b"fresh")

    def test_download_publish_failure_preserves_an_existing_target(self):
        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"fresh"',
                        "x-amz-version-id": "version-fresh",
                    },
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=b"fresh",
                    headers={
                        "ETag": '"fresh"',
                        "x-amz-version-id": "version-fresh",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "note.txt"
        target.write_bytes(b"verified old copy")

        with patch("services.s3_locations.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                s3_locations.download(self.row, "note.txt", target)

        self.assertEqual(target.read_bytes(), b"verified old copy")

    def test_download_gets_and_verifies_the_exact_head_version(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-1",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.url.params.get("versionId"), "version-1")
                return httpx.Response(
                    200,
                    content=b"newer",
                    headers={
                        "ETag": '"same"',
                        "x-amz-version-id": "version-2",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "note.txt"
        target.write_bytes(b"verified old copy")

        with self.assertRaisesRegex(s3_locations.S3LocationError, "remote file changed"):
            s3_locations.download(self.row, "note.txt", target)

        self.assertEqual(target.read_bytes(), b"verified old copy")
        self.assertEqual([request.method for request in requests], ["HEAD", "GET"])

    def test_download_heads_the_listed_version_before_reading_it(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.params.get("versionId"), "version-listed")
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"listed"',
                        "x-amz-version-id": "version-listed",
                    },
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=b"exact",
                    headers={
                        "ETag": '"listed"',
                        "x-amz-version-id": "version-listed",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "listed.txt"
        result = s3_locations.download(
            self.row,
            "listed.txt",
            target,
            expected_etag='"listed"',
            expected_size=5,
            expected_version_id="version-listed",
        )

        self.assertEqual(target.read_bytes(), b"exact")
        self.assertEqual(result["version_id"], "version-listed")
        self.assertEqual([request.method for request in requests], ["HEAD", "GET"])

    def test_download_rejects_a_globally_oversized_object_before_get(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(s3_locations.MAX_FILE_BYTES + 1),
                        "ETag": '"large"',
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "large.bin"
        target.write_bytes(b"verified old copy")

        with self.assertRaisesRegex(s3_locations.S3LocationError, "too large"):
            s3_locations.download(self.row, "large.bin", target)

        self.assertEqual(target.read_bytes(), b"verified old copy")
        self.assertEqual([request.method for request in requests], ["HEAD"])

    def test_text_prefix_uses_the_listed_object_identity_and_exact_version(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                self.assertEqual(request.url.params.get("versionId"), "version-1")
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "11",
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.url.params.get("versionId"), "version-1")
                self.assertEqual(request.headers.get("range"), "bytes=0-4")
                self.assertEqual(request.headers.get("if-match"), '"v1"')
                return httpx.Response(
                    206,
                    content=b"hello",
                    headers={
                        "Content-Length": "5",
                        "Content-Range": "bytes 0-4/11",
                        "ETag": '"v1"',
                        "x-amz-version-id": "version-1",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        result = s3_locations.read_prefix(
            self.row,
            "note.txt",
            5,
            expected_etag='"v1"',
            expected_size=11,
            expected_version_id="version-1",
        )

        self.assertEqual(result["content"], b"hello")
        self.assertEqual(result["size"], 11)
        self.assertEqual(result["etag"], '"v1"')
        self.assertEqual(result["version_id"], "version-1")
        self.assertEqual([request.method for request in requests], ["HEAD", "GET"])

    def test_text_prefix_accepts_a_bounded_full_response_for_a_small_object(self):
        payload = b"hello"

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"v1"',
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.headers.get("range"), "bytes=0-4")
                return httpx.Response(
                    200,
                    content=payload,
                    headers={"Content-Length": str(len(payload)), "ETag": '"v1"'},
                )
            raise AssertionError(request.method)

        self.client(handler)
        result = s3_locations.read_prefix(
            self.row,
            "small.txt",
            64,
            expected_etag='"v1"',
            expected_size=len(payload),
        )

        self.assertEqual(result["content"], payload)

    def test_text_prefix_accepts_an_empty_object_without_a_range_request(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "0",
                        "ETag": '"empty"',
                        "x-amz-version-id": "empty-version",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        result = s3_locations.read_prefix(
            self.row,
            "empty.txt",
            64,
            expected_etag='"empty"',
            expected_size=0,
            expected_version_id="empty-version",
        )

        self.assertEqual(result["content"], b"")
        self.assertEqual(result["size"], 0)
        self.assertEqual([request.method for request in requests], ["HEAD"])

    def test_text_prefix_rejects_stale_listed_identity_before_get(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "11",
                        "ETag": '"new"',
                        "x-amz-version-id": "version-2",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "changed"):
            s3_locations.read_prefix(
                self.row,
                "note.txt",
                5,
                expected_etag='"old"',
                expected_size=11,
                expected_version_id="version-1",
            )
        self.assertEqual([request.method for request in requests], ["HEAD"])

    def test_upload_is_conditional_and_read_back_verified(self):
        payload = b"verified upload"
        puts = []

        def handler(request):
            if request.method == "PUT":
                puts.append(request)
                return httpx.Response(
                    200,
                    headers={"ETag": '"uploaded"', "x-amz-version-id": "version-2"},
                )
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "version-2",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=payload,
                    headers={
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "version-2",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("buffered upload")):
            result = s3_locations.upload(self.row, "source.txt", source)
        self.assertEqual(puts[0].headers.get("if-none-match"), "*")
        self.assertEqual(result["version_id"], "version-2")

    def test_upload_never_claims_a_version_seen_only_during_readback(self):
        payload = b"same upload bytes"

        def handler(request):
            if request.method == "PUT":
                return httpx.Response(200, headers={"ETag": '"uploaded"'})
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "concurrent-version",
                    },
                )
            if request.method == "GET":
                if "versioning" in request.url.params:
                    return httpx.Response(200, content=VERSIONING_ENABLED)
                return httpx.Response(
                    200,
                    content=payload,
                    headers={
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "concurrent-version",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)

        with self.assertRaisesRegex(s3_locations.S3LocationError, "preserved for reconciliation"):
            s3_locations.upload(self.row, "source.txt", source)

    def test_failed_unversioned_upload_verification_preserves_ambiguous_object(self):
        payload = b"expected upload"
        visible = False
        deletes = []

        def handler(request):
            nonlocal visible
            if request.method == "PUT":
                visible = True
                return httpx.Response(200, headers={"ETag": '"uploaded"'})
            if request.method == "HEAD":
                if not visible:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"uploaded"',
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET" and "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_UNCONFIGURED)
            if request.method == "GET":
                return httpx.Response(
                    200, content=b"corrupt readback", headers={"ETag": '"uploaded"'}
                )
            if request.method == "DELETE":
                deletes.append(request)
                self.assertEqual(request.headers.get("if-match"), '"uploaded"')
                visible = False
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)

        with self.assertRaisesRegex(s3_locations.S3LocationError, "preserved for reconciliation"):
            s3_locations.upload(self.row, "source.txt", source)

        self.assertEqual(deletes, [])
        self.assertTrue(visible)

    def test_upload_verifies_the_exact_version_returned_by_put(self):
        payload = b"same upload bytes"

        def handler(request):
            if request.method == "PUT":
                return httpx.Response(
                    200,
                    headers={
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "created-version",
                    },
                )
            if request.method == "HEAD":
                self.assertEqual(request.url.params.get("versionId"), "created-version")
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "created-version",
                    },
                )
            if request.method == "GET":
                self.assertEqual(request.url.params.get("versionId"), "created-version")
                return httpx.Response(
                    200,
                    content=payload,
                    headers={
                        "ETag": '"uploaded"',
                        "x-amz-version-id": "created-version",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)

        result = s3_locations.upload(self.row, "source.txt", source)

        self.assertEqual(result["version_id"], "created-version")

    def test_direct_upload_accepts_a_max_length_name_without_claiming_operation_ownership(self):
        payload = b"verified long name"
        remote_name = f"{'s' * 251}.txt"

        def handler(request):
            if request.method == "PUT":
                return httpx.Response(200, headers={"ETag": '"uploaded"'})
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(payload)),
                        "ETag": '"uploaded"',
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=payload,
                    headers={"ETag": '"uploaded"'},
                )
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)

        with patch("services.s3_locations.data_dir", return_value=self.root):
            result = s3_locations.upload(self.row, remote_name, source)

        self.assertEqual(result["size"], len(payload))
        self.assertEqual(result["version_id"], "")

    def test_stale_upload_preserves_incoming_copy_while_remote_remains_untouched(self):
        remote = b"remote wins"
        gets = []

        def handler(request):
            if request.method == "PUT":
                self.assertEqual(request.headers.get("if-match"), '"old"')
                return httpx.Response(412)
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": str(len(remote)),
                        "ETag": '"new"',
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "GET":
                gets.append(request)
                return httpx.Response(200, content=remote)
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(b"local change")
        with patch("services.s3_locations.data_dir", return_value=self.root):
            with self.assertRaises(s3_locations.S3ConflictError) as caught:
                s3_locations.upload(self.row, "source.txt", source, expected_etag='"old"')
        self.assertEqual(caught.exception.conflict_path.read_bytes(), b"local change")
        self.assertEqual(gets, [])

    def test_upload_rejects_wildcard_etag_before_sending(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise AssertionError("wildcard ETag must be rejected before network I/O")

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(b"local change")

        with self.assertRaisesRegex(s3_locations.S3LocationError, "identifier is invalid"):
            s3_locations.upload(self.row, "source.txt", source, expected_etag="*")

        self.assertEqual(requests, [])

    def test_versioned_delete_fails_before_creating_a_delete_marker(self):
        deleted = []
        visible = True

        def handler(request):
            nonlocal visible
            if request.method == "HEAD":
                if not visible:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                self.assertIsNone(request.url.params.get("versionId"))
                deleted.append(request)
                visible = False
                return httpx.Response(
                    204,
                    headers={
                        "x-amz-delete-marker": "true",
                        "x-amz-version-id": "delete-marker-4",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "versioned"):
            s3_locations.delete(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(deleted, [])

    def test_versioned_delete_does_not_attempt_a_conditional_delete(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(412)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "versioned"):
            s3_locations.delete(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(deleted, [])

    def test_versioned_directory_marker_is_preserved_when_delete_is_not_atomic(self):
        deleted = []
        visible = True

        def handler(request):
            nonlocal visible
            if request.method == "HEAD":
                if not visible:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "0",
                        "ETag": '"folder"',
                        "x-amz-version-id": "folder-version-1",
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                visible = False
                return httpx.Response(
                    204,
                    headers={
                        "x-amz-delete-marker": "true",
                        "x-amz-version-id": "folder-delete-marker-2",
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaises(s3_locations.S3VersionedDeleteRefused) as caught:
            s3_locations.delete_directory_marker(self.row, "folder")
        self.assertEqual(caught.exception.metadata["version_id"], "folder-version-1")
        self.assertEqual(deleted, [])

    def test_nonempty_slash_object_is_not_deleted_as_a_directory_marker(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={"Content-Length": "7", "ETag": '"not-a-marker"'},
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "not empty"):
            s3_locations.delete_directory_marker(self.row, "folder")
        self.assertEqual(deleted, [])

    def test_versioned_delete_cannot_hide_a_same_etag_newer_version(self):
        deleted = []
        visible_version = "version-3"

        def handler(request):
            nonlocal visible_version
            if request.method == "HEAD":
                if not visible_version:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"' if visible_version == "version-3" else '"older"',
                        "x-amz-version-id": visible_version,
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                if request.url.params.get("versionId"):
                    visible_version = "version-2"
                else:
                    visible_version = ""
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "versioned"):
            s3_locations.delete(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(deleted, [])

    def test_versioned_delete_without_an_exact_version_fails_closed(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "versioned"):
            s3_locations.delete(self.row, "note.txt", expected_etag='"same"')
        self.assertEqual(deleted, [])

    def test_owned_version_delete_requires_both_identity_fields(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise AssertionError("invalid owned-version identity reached s3")

        self.client(handler)
        cases = [
            {"expected_etag": "", "version_id": "version-3"},
            {"expected_etag": '"same"', "version_id": ""},
            {"expected_etag": '"same"', "version_id": "   "},
            {"expected_etag": '"same"', "version_id": "null"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(s3_locations.S3LocationError):
                    s3_locations.delete_owned_version(self.row, "note.txt", **kwargs)
        self.assertEqual(requests, [])

    def test_owned_version_delete_rejects_an_identity_mismatch_before_delete(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                self.assertEqual(request.url.params.get("versionId"), "version-3")
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"different"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "changed"):
            s3_locations.delete_owned_version(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(deleted, [])

    def test_owned_version_delete_rejects_a_mismatched_version_header(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                self.assertEqual(request.url.params.get("versionId"), "version-3")
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-other",
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "changed"):
            s3_locations.delete_owned_version(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(deleted, [])

    def test_owned_version_delete_removes_only_the_exact_version(self):
        requests = []
        owned_exists = True
        current_version = "version-4"

        def handler(request):
            nonlocal owned_exists
            requests.append(request)
            requested_version = request.url.params.get("versionId")
            if request.method == "HEAD" and requested_version == "version-3":
                if not owned_exists:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                self.assertEqual(requested_version, "version-3")
                owned_exists = False
                return httpx.Response(204)
            if request.method == "HEAD" and requested_version is None:
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"newer"',
                        "x-amz-version-id": current_version,
                    },
                )
            raise AssertionError(f"{request.method} {request.url}")

        self.client(handler)
        s3_locations.delete_owned_version(
            self.row,
            "note.txt",
            expected_etag='"same"',
            version_id="version-3",
        )

        current = s3_locations._head(self.row, "note.txt")
        self.assertEqual(current["version_id"], "version-4")
        owned_requests = requests[:-1]
        self.assertEqual(
            [(request.method, request.url.params.get("versionId")) for request in owned_requests],
            [("HEAD", "version-3"), ("DELETE", "version-3"), ("HEAD", "version-3")],
        )
        self.assertFalse(owned_exists)

    def test_owned_version_delete_fails_when_the_exact_version_remains(self):
        head_count = 0

        def handler(request):
            nonlocal head_count
            self.assertEqual(request.url.params.get("versionId"), "version-3")
            if request.method == "HEAD":
                head_count += 1
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"same"',
                        "x-amz-version-id": "version-3",
                    },
                )
            if request.method == "DELETE":
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "could not be verified"):
            s3_locations.delete_owned_version(
                self.row,
                "note.txt",
                expected_etag='"same"',
                version_id="version-3",
            )
        self.assertEqual(head_count, 2)

    def test_delete_fails_closed_when_the_current_object_changes(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Length": "5",
                        "ETag": '"new"',
                    },
                )
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(412)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaises(s3_locations.S3LocationError):
            s3_locations.delete(
                self.row,
                "note.txt",
                expected_etag='"old"',
            )
        self.assertEqual(deleted, [])

    def test_unversioned_delete_uses_if_match_and_verifies_absence(self):
        deleted = []
        deleted_once = False

        def handler(request):
            nonlocal deleted_once
            if request.method == "GET" and "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_UNCONFIGURED)
            if request.method == "HEAD":
                if deleted_once:
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    headers={"Content-Length": "5", "ETag": '"same"'},
                )
            if request.method == "DELETE":
                deleted.append(request)
                deleted_once = True
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        s3_locations.delete(self.row, "note.txt", expected_etag='"same"')
        self.assertEqual(deleted[0].headers.get("if-match"), '"same"')

    def test_delete_fails_closed_when_versioning_state_cannot_be_proven(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={"Content-Length": "5", "ETag": '"same"'},
                )
            if request.method == "GET" and "versioning" in request.url.params:
                return httpx.Response(403)
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(s3_locations.S3LocationError, "permission"):
            s3_locations.delete(self.row, "note.txt", expected_etag='"same"')
        self.assertEqual(deleted, [])

    def test_delete_refuses_enabled_bucket_when_head_omits_version_identity(self):
        deleted = []

        def handler(request):
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={"Content-Length": "5", "ETag": '"same"'},
                )
            if request.method == "GET" and "versioning" in request.url.params:
                return httpx.Response(200, content=VERSIONING_ENABLED)
            if request.method == "DELETE":
                deleted.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaises(s3_locations.S3VersionedDeleteRefused):
            s3_locations.delete(self.row, "note.txt", expected_etag='"same"')
        self.assertEqual(deleted, [])

    def test_quota_redirect_unsafe_xml_and_timeout_fail_closed(self):
        cases = [
            httpx.Response(507),
            httpx.Response(302, headers={"Location": "https://other.test"}),
            httpx.Response(200, content=b'<!DOCTYPE x [<!ENTITY y "z">]><x/>'),
            httpx.ReadTimeout("slow"),
        ]
        for result in cases:
            with self.subTest(result=type(result).__name__):

                def handler(request, result=result):
                    if isinstance(result, Exception):
                        raise result
                    return result

                self.client(handler)
                with self.assertRaises(S3LocationErrorAlias):
                    s3_locations.listdir(self.row)


S3LocationErrorAlias = s3_locations.S3LocationError


if __name__ == "__main__":
    unittest.main()
