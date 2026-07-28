import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import httpx

from services import webdav_locations


def listing(*, etag='"root-etag"', child="file.txt", child_type="file") -> bytes:
    resource = "<d:collection/>" if child_type == "dir" else ""
    size = "0" if child_type == "dir" else "5"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/dav/</d:href><d:propstat><d:prop>
    <d:resourcetype><d:collection/></d:resourcetype><d:getetag>{etag}</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
  <d:response><d:href>/dav/{child}</d:href><d:propstat><d:prop>
    <d:resourcetype>{resource}</d:resourcetype><d:getcontentlength>{size}</d:getcontentlength>
    <d:getlastmodified>Wed, 15 Jul 2026 10:00:00 GMT</d:getlastmodified>
    <d:getetag>\"child-etag\"</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>""".encode()


def empty_listing(*, etag='"root-etag"') -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/dav/</d:href><d:propstat><d:prop>
    <d:resourcetype><d:collection/></d:resourcetype><d:getetag>{etag}</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>""".encode()


class WebDAVLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.row = SimpleNamespace(
            id="dav-1",
            endpoint="https://dav.example.test/dav",
            access="managed",
            secret=json.dumps({"username": "me", "password": "secret"}),
        )
        self.safe = patch(
            "services.net_guard.resolve_safe_url",
            side_effect=lambda url: (urlparse(url), ("93.184.216.34",)),
        )
        self.safe.start()
        self.data_patch = patch.object(
            webdav_locations, "data_dir", return_value=self.root / "data"
        )
        self.data_patch.start()

    def tearDown(self):
        webdav_locations.CLIENT_FACTORY = None
        self.data_patch.stop()
        self.safe.stop()
        self.tmp.cleanup()

    def client(self, handler):
        webdav_locations.CLIENT_FACTORY = lambda _row, _credentials: httpx.Client(
            transport=httpx.MockTransport(handler)
        )

    def test_transport_connects_to_the_validated_address_with_original_host_and_sni(self):
        observed = {}

        def handler(request):
            observed["url"] = request.url
            observed["host"] = request.headers.get("host")
            observed["sni"] = request.extensions.get("sni_hostname")
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "OPTIONS, PROPFIND"})
            return httpx.Response(207, content=empty_listing())

        self.client(handler)
        webdav_locations.capabilities(self.row)

        self.assertEqual(observed["url"].host, "93.184.216.34")
        self.assertEqual(observed["host"], "dav.example.test")
        self.assertEqual(observed["sni"], b"dav.example.test")

    def test_transport_retries_each_validated_address(self):
        observed = []

        def handler(request):
            observed.append(request.url.host)
            if request.url.host == "2001:db8::1":
                raise httpx.ConnectError("first address unavailable", request=request)
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "OPTIONS, PROPFIND"})
            return httpx.Response(207, content=empty_listing())

        self.safe.stop()
        self.safe = patch(
            "services.net_guard.resolve_safe_url",
            side_effect=lambda url: (urlparse(url), ("2001:db8::1", "93.184.216.34")),
        )
        self.safe.start()
        self.client(handler)

        webdav_locations.capabilities(self.row)

        self.assertIn("2001:db8::1", observed)
        self.assertIn("93.184.216.34", observed)

    def test_explicit_loopback_http_uses_the_narrow_loopback_resolver(self):
        self.row.endpoint = "http://localhost:8765/dav"
        observed = []

        def handler(request):
            observed.append(request.url.host)
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "OPTIONS, PROPFIND"})
            return httpx.Response(207, content=empty_listing())

        with patch(
            "services.net_guard.resolve_loopback_url",
            side_effect=lambda url: (urlparse(url), ("127.0.0.1",)),
        ) as resolve_loopback:
            self.client(handler)
            webdav_locations.capabilities(self.row)

        resolve_loopback.assert_called()
        self.assertEqual(observed, ["127.0.0.1", "127.0.0.1"])

    def test_capabilities_and_listing_normalize_remote_fields(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={
                        "Allow": "OPTIONS, PROPFIND, GET, PUT, DELETE, COPY, MOVE",
                        "DAV": "1, 2",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        result = webdav_locations.capabilities(self.row)
        self.assertTrue(result["ok"])
        self.assertTrue(result["writable"])
        self.assertTrue(result["supports_etag"])
        self.assertTrue(result["supports_ranges"])
        self.assertTrue(result["supports_copy"])
        self.assertTrue(result["supports_move"])

        files = webdav_locations.listdir(self.row)
        self.assertEqual(files["items"][0]["path"], "file.txt")
        self.assertEqual(files["items"][0]["size"], 5)
        self.assertEqual(files["items"][0]["etag"], '"child-etag"')

    def test_listing_distinguishes_unknown_size_from_zero_bytes(self):
        document = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/dav/</d:href><d:propstat><d:prop>
    <d:resourcetype><d:collection/></d:resourcetype>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
  <d:response><d:href>/dav/unknown.bin</d:href><d:propstat><d:prop>
    <d:resourcetype/><d:getetag>"unknown"</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
  <d:response><d:href>/dav/empty.bin</d:href><d:propstat><d:prop>
    <d:resourcetype/><d:getcontentlength>0</d:getcontentlength>
    <d:getetag>"empty"</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>"""

        def handler(request):
            if request.method == "PROPFIND":
                return httpx.Response(207, content=document)
            if request.url.path.endswith("/unknown.bin"):
                return httpx.Response(200, content=b"abc", headers={"ETag": '"unknown"'})
            if request.url.path.endswith("/empty.bin"):
                return httpx.Response(200, content=b"x", headers={"ETag": '"empty"'})
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        items = {item["path"]: item for item in webdav_locations.listdir(self.row)["items"]}

        self.assertIsNone(items["unknown.bin"]["size"])
        self.assertEqual(items["empty.bin"]["size"], 0)

        unknown_target = self.root / "unknown.bin"
        result = webdav_locations.download(
            self.row,
            "unknown.bin",
            unknown_target,
            expected_etag='"unknown"',
            expected_size=items["unknown.bin"]["size"],
        )
        self.assertEqual(result["size"], 3)
        self.assertEqual(unknown_target.read_bytes(), b"abc")

        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "size"):
            webdav_locations.download(
                self.row,
                "empty.bin",
                self.root / "empty.bin",
                expected_etag='"empty"',
                expected_size=items["empty.bin"]["size"],
            )

    def test_location_prefix_scopes_every_webdav_request(self):
        self.row.prefix = "team/files"
        requested_paths = []

        def handler(request):
            requested_paths.append(request.url.path)
            if request.method == "PROPFIND":
                document = listing().replace(b"/dav/", b"/dav/team/files/")
                return httpx.Response(207, content=document)
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        result = webdav_locations.listdir(self.row)

        self.assertEqual(requested_paths, ["/dav/team/files/"])
        self.assertEqual(result["items"][0]["path"], "file.txt")

    def test_listing_accepts_explicit_default_ports_but_rejects_other_origins(self):
        def document(accepted_href, rejected_href):
            return f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>{accepted_href}</d:href><d:propstat><d:prop>
    <d:resourcetype/><d:getcontentlength>5</d:getcontentlength>
    <d:getetag>"accepted"</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
  <d:response><d:href>{rejected_href}</d:href><d:propstat><d:prop>
    <d:resourcetype/><d:getcontentlength>7</d:getcontentlength>
    <d:getetag>"rejected"</d:getetag>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>""".encode()

        cases = [
            (
                "https://dav.example.test/dav",
                "https://dav.example.test:443/dav/file.txt",
                "https://dav.example.test:444/dav/foreign.txt",
            ),
            (
                "http://localhost/dav",
                "http://localhost:80/dav/file.txt",
                "http://localhost:81/dav/foreign.txt",
            ),
        ]
        for endpoint, accepted_href, rejected_href in cases:
            with self.subTest(endpoint=endpoint):
                self.row.endpoint = endpoint
                payload = document(accepted_href, rejected_href)

                def handler(request):
                    self.assertEqual(request.method, "PROPFIND")
                    return httpx.Response(207, content=payload)

                self.client(handler)
                result = webdav_locations.listdir(self.row)

                self.assertEqual([item["path"] for item in result["items"]], ["file.txt"])

    def test_empty_root_still_proves_etag_support(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={"Allow": "PROPFIND, GET, PUT, DELETE"},
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing())
            raise AssertionError(request.method)

        self.client(handler)
        result = webdav_locations.capabilities(self.row)
        self.assertTrue(result["supports_etag"])
        self.assertTrue(result["writable"])

    def test_empty_root_probes_conditional_etag_support_before_tree_uploads(self):
        requests = []
        create_attempts = 0

        def handler(request):
            nonlocal create_attempts
            requests.append(request.method)
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={"Allow": "PROPFIND, GET, PUT, DELETE"},
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing(etag=""))
            if request.method == "PUT" and request.headers.get("if-none-match") == "*":
                create_attempts += 1
                if create_attempts > 1:
                    return httpx.Response(412)
                return httpx.Response(201, headers={"ETag": '"probe-v1"'})
            if request.method == "PUT" and request.headers.get("if-match"):
                return httpx.Response(412)
            if request.method == "DELETE":
                self.assertEqual(request.headers.get("if-match"), '"probe-v1"')
                return httpx.Response(204)
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        result = webdav_locations.capabilities(self.row)

        self.assertTrue(result["supports_etag"])
        self.assertEqual(requests, ["OPTIONS", "PROPFIND", "PUT", "PUT", "PUT", "DELETE"])

    def test_etag_probe_does_not_delete_a_concurrent_replacement(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing(etag=""))
            if request.method == "PUT" and request.headers.get("if-none-match") == "*":
                if not hasattr(handler, "created"):
                    handler.created = True
                    return httpx.Response(201, headers={"ETag": '"probe-v1"'})
                return httpx.Response(412)
            if request.method == "PUT":
                return httpx.Response(412)
            if request.method == "DELETE":
                self.assertEqual(request.headers.get("if-match"), '"probe-v1"')
                return httpx.Response(412)
            raise AssertionError(request.method)

        self.client(handler)

        self.assertTrue(webdav_locations.capabilities(self.row)["supports_etag"])

    def test_probe_without_an_etag_is_journaled_and_not_recreated(self):
        create_attempts = 0
        probe_path = ""
        marker = b""
        etag_available = False

        def probe_document(path, etag=""):
            return f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/{path}</d:href>
<d:propstat><d:prop><d:resourcetype/><d:getetag>{etag}</d:getetag></d:prop>
<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>""".encode()

        def handler(request):
            nonlocal create_attempts, marker, probe_path
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND" and str(request.url).rstrip("/").endswith("dav"):
                child = probe_path or "missing"
                return httpx.Response(
                    207,
                    content=empty_listing()
                    if etag_available
                    else empty_listing(etag="")
                    if not probe_path
                    else listing(etag="", child=child).replace(b'"child-etag"', b""),
                )
            if request.method == "PROPFIND":
                etag = '"probe-v1"' if etag_available else ""
                return httpx.Response(207, content=probe_document(probe_path, etag))
            if request.method == "PUT" and request.headers.get("if-none-match") == "*":
                create_attempts += 1
                if not probe_path:
                    probe_path = request.url.path.rsplit("/", 1)[-1]
                    marker = request.content
                    return httpx.Response(201)
                return httpx.Response(412)
            if request.method == "GET":
                self.assertEqual(request.headers.get("if-match"), '"probe-v1"')
                return httpx.Response(200, content=marker)
            if request.method == "DELETE":
                self.assertEqual(request.headers.get("if-match"), '"probe-v1"')
                probe_path = ""
                return httpx.Response(204)
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        self.assertFalse(webdav_locations.capabilities(self.row)["supports_etag"])
        self.assertFalse(webdav_locations.capabilities(self.row)["supports_etag"])
        self.assertEqual(create_attempts, 2)
        self.assertTrue(webdav_locations._probe_journal_path(self.row).is_file())
        etag_available = True
        self.assertTrue(webdav_locations.capabilities(self.row)["supports_etag"])
        self.assertEqual(create_attempts, 2)
        self.assertFalse(webdav_locations._probe_journal_path(self.row).exists())

    def test_weak_etags_do_not_advertise_mutation_safe_identity(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(
                    207,
                    content=listing(etag='W/"root-etag"').replace(
                        b'"child-etag"', b'W/"child-etag"'
                    ),
                )
            raise AssertionError(request.method)

        self.client(handler)
        result = webdav_locations.capabilities(self.row)
        self.assertFalse(result["supports_etag"])
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "stable ETags"):
            webdav_locations._mutation_capabilities(self.row)

    def test_empty_collection_without_etags_allows_create_only_writes(self):
        uploaded = b"first bytes"
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "PUT":
                self.assertEqual(request.headers.get("if-none-match"), "*")
                return httpx.Response(201)
            if request.method == "GET":
                return httpx.Response(200, content=uploaded)
            if request.method == "MKCOL":
                return httpx.Response(201)
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        source = self.root / "first.txt"
        source.write_bytes(uploaded)

        with patch.object(
            webdav_locations,
            "capabilities",
            return_value={"supports_etag": True},
        ):
            result = webdav_locations.upload(self.row, "first.txt", source)
        created = webdav_locations.mkdir(self.row, "first folder")

        self.assertEqual(result["etag"], "")
        self.assertEqual(created["path"], "first folder")
        self.assertEqual([request.method for request in requests], ["PUT", "GET", "MKCOL"])

    def test_known_target_etag_allows_write_when_root_options_are_incomplete(self):
        uploaded = b"replacement"

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "OPTIONS, PROPFIND, GET"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing(etag=""))
            if request.method == "PUT":
                self.assertEqual(request.headers.get("if-match"), '"target-v1"')
                return httpx.Response(204, headers={"ETag": '"target-v2"'})
            if request.method == "GET":
                return httpx.Response(200, content=uploaded, headers={"ETag": '"target-v2"'})
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)
        source = self.root / "replacement.txt"
        source.write_bytes(uploaded)

        with patch.object(
            webdav_locations,
            "capabilities",
            return_value={"supports_etag": True},
        ):
            result = webdav_locations.upload(
                self.row,
                "nested/replacement.txt",
                source,
                expected_etag='"target-v1"',
            )

        self.assertEqual(result["etag"], '"target-v2"')
        self.assertEqual(result["size"], len(uploaded))

    def test_known_target_etag_allows_delete_when_root_omits_delete(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "OPTIONS, PROPFIND, GET"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing(etag=""))
            if request.method == "DELETE":
                self.assertEqual(request.headers.get("if-match"), '"target-v1"')
                return httpx.Response(204)
            raise AssertionError((request.method, str(request.url)))

        self.client(handler)

        webdav_locations.delete(self.row, "nested/old.txt", expected_etag='"target-v1"')

    def test_resume_uses_range_only_after_server_proves_support(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={
                        "Allow": "PROPFIND, GET, PUT, DELETE",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "GET":
                self.assertEqual(request.headers.get("range"), "bytes=5-")
                return httpx.Response(
                    206,
                    content=b" world",
                    headers={"ETag": '"v1"', "Content-Range": "bytes 5-10/11"},
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"hello")
        identity.write_text(json.dumps({"etag": '"v1"'}), encoding="utf-8")
        result = webdav_locations.download(
            self.row,
            "file.txt",
            target,
            expected_etag='"v1"',
            resume=True,
        )
        self.assertEqual(target.read_bytes(), b"hello world")
        self.assertEqual(result["size"], 11)
        self.assertEqual([r.method for r in requests], ["OPTIONS", "PROPFIND", "GET"])

    def test_fresh_download_cannot_relabel_stale_partial_for_later_resume(self):
        requested_ranges = []

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={"Allow": "PROPFIND, GET", "Accept-Ranges": "bytes"},
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "GET":
                requested_range = request.headers.get("range")
                requested_ranges.append(requested_range)
                if requested_range:
                    self.assertEqual(requested_range, "bytes=5-")
                    return httpx.Response(
                        206,
                        content=b" world",
                        headers={"ETag": '"new"', "Content-Range": "bytes 5-10/11"},
                    )
                return httpx.Response(200, content=b"fresh world", headers={"ETag": '"new"'})
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"stale")
        identity.write_text(json.dumps({"etag": '"old"', "size": 5}), encoding="utf-8")

        class SimulatedHardStop(BaseException):
            pass

        original_open = Path.open
        stopped = False

        def stop_before_fresh_partial(path, mode="r", *args, **kwargs):
            nonlocal stopped
            if path == partial and mode == "xb" and not stopped:
                stopped = True
                raise SimulatedHardStop
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", stop_before_fresh_partial):
            with self.assertRaises(SimulatedHardStop):
                webdav_locations.download(
                    self.row,
                    "file.txt",
                    target,
                    expected_etag='"new"',
                    expected_size=11,
                )

        webdav_locations.download(
            self.row,
            "file.txt",
            target,
            expected_etag='"new"',
            expected_size=11,
            resume=True,
        )

        self.assertEqual(target.read_bytes(), b"fresh world")
        self.assertEqual(requested_ranges, [None, None])

    def test_text_prefix_uses_an_identity_bound_bounded_range(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers.get("range"), "bytes=0-4")
            self.assertEqual(request.headers.get("if-match"), '"v1"')
            return httpx.Response(
                206,
                content=b"hello",
                headers={
                    "Content-Length": "5",
                    "Content-Range": "bytes 0-4/11",
                    "ETag": '"v1"',
                },
            )

        self.client(handler)
        result = webdav_locations.read_prefix(
            self.row,
            "note.txt",
            5,
            expected_etag='"v1"',
            expected_size=11,
        )

        self.assertEqual(result["content"], b"hello")
        self.assertEqual(result["size"], 11)
        self.assertEqual(result["etag"], '"v1"')
        self.assertEqual(len(requests), 1)

    def test_text_prefix_proves_an_identity_bound_empty_file_with_a_get(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers.get("if-match"), '"empty"')
            self.assertIsNone(request.headers.get("range"))
            response = httpx.Response(
                200,
                content=b"",
                headers={"ETag": '"empty"'},
            )
            response.headers.pop("content-length", None)
            return response

        self.client(handler)
        result = webdav_locations.read_prefix(
            self.row,
            "empty.txt",
            5,
            expected_etag='"empty"',
            expected_size=0,
        )

        self.assertEqual(result, {"content": b"", "size": 0, "etag": '"empty"'})
        self.assertEqual(len(requests), 1)

    def test_text_prefix_fails_closed_when_webdav_ignores_range(self):
        def handler(request):
            self.assertEqual(request.headers.get("range"), "bytes=0-4")
            return httpx.Response(
                200,
                content=b"hello world",
                headers={"Content-Length": "11", "ETag": '"v1"'},
            )

        self.client(handler)
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "range"):
            webdav_locations.read_prefix(
                self.row,
                "note.txt",
                5,
                expected_etag='"v1"',
                expected_size=11,
            )

    def test_text_prefix_rejects_a_different_remote_identity(self):
        def handler(_request):
            return httpx.Response(
                206,
                content=b"hello",
                headers={
                    "Content-Length": "5",
                    "Content-Range": "bytes 0-4/11",
                    "ETag": '"v2"',
                },
            )

        self.client(handler)
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "changed"):
            webdav_locations.read_prefix(
                self.row,
                "note.txt",
                5,
                expected_etag='"v1"',
                expected_size=11,
            )

    def test_resume_restarts_when_server_does_not_prove_ranges(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "GET":
                self.assertIsNone(request.headers.get("range"))
                return httpx.Response(200, content=b"fresh", headers={"ETag": '"v2"'})
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, _identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"stale")
        webdav_locations.download(self.row, "file.txt", target, resume=True)
        self.assertEqual(target.read_bytes(), b"fresh")

    def test_resume_discards_a_partial_from_a_different_etag(self):
        def handler(request):
            if request.method == "GET":
                self.assertIsNone(request.headers.get("range"))
                self.assertEqual(request.headers.get("if-match"), '"new"')
                return httpx.Response(200, content=b"fresh", headers={"ETag": '"new"'})
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"stale")
        identity.write_text(json.dumps({"etag": '"old"'}), encoding="utf-8")
        webdav_locations.download(
            self.row,
            "file.txt",
            target,
            expected_etag='"new"',
            resume=True,
        )
        self.assertEqual(target.read_bytes(), b"fresh")

    def test_download_rejects_a_short_response_before_promoting_it(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=b"cut",
                    headers={"Content-Length": "3", "ETag": '"same"'},
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "size"):
            webdav_locations.download(
                self.row,
                "file.txt",
                target,
                expected_etag='"same"',
                expected_size=5,
            )
        self.assertFalse(target.exists())

    def test_download_atomically_replaces_an_existing_target(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=b"fresh", headers={"ETag": '"v1"'})
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        target.write_bytes(b"old")
        original_unlink = Path.unlink

        def forbid_separate_target_unlink(path, *args, **kwargs):
            if path == target:
                raise AssertionError("download publication must not unlink the target first")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", forbid_separate_target_unlink):
            result = webdav_locations.download(
                self.row,
                "file.txt",
                target,
                expected_etag='"v1"',
                expected_size=5,
            )

        self.assertEqual(result["size"], 5)
        self.assertEqual(target.read_bytes(), b"fresh")

    def test_download_rejects_a_response_that_omits_the_conditional_etag(self):
        def handler(request):
            if request.method == "GET":
                self.assertEqual(request.headers.get("if-match"), '"v1"')
                return httpx.Response(200, content=b"fresh")
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download-without-response-etag.txt"
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "changed"):
            webdav_locations.download(
                self.row,
                "file.txt",
                target,
                expected_etag='"v1"',
                expected_size=5,
            )

        self.assertFalse(target.exists())

    def test_resume_rejects_a_mismatched_content_range(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={
                        "Allow": "PROPFIND, GET, PUT, DELETE",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "GET":
                return httpx.Response(
                    206,
                    content=b" world",
                    headers={
                        "Content-Range": "bytes 4-10/11",
                        "Content-Length": "6",
                        "ETag": '"v1"',
                    },
                )
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"hello")
        identity.write_text(json.dumps({"etag": '"v1"', "size": 11}), encoding="utf-8")
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "range"):
            webdav_locations.download(
                self.row,
                "file.txt",
                target,
                expected_etag='"v1"',
                expected_size=11,
                resume=True,
            )
        self.assertFalse(target.exists())

    def test_resume_discards_an_empty_partial_before_restarting(self):
        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(
                    204,
                    headers={
                        "Allow": "PROPFIND, GET, PUT, DELETE",
                        "Accept-Ranges": "bytes",
                    },
                )
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "GET":
                self.assertIsNone(request.headers.get("range"))
                return httpx.Response(200, content=b"fresh", headers={"ETag": '"v1"'})
            raise AssertionError(request.method)

        self.client(handler)
        target = self.root / "download.txt"
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"")
        identity.write_text(json.dumps({"etag": '"v1"', "size": 5}), encoding="utf-8")

        webdav_locations.download(
            self.row,
            "file.txt",
            target,
            expected_etag='"v1"',
            expected_size=5,
            resume=True,
        )

        self.assertEqual(target.read_bytes(), b"fresh")

    def test_resume_redownloads_a_full_sized_but_unverified_partial(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "GET":
                self.assertIsNone(request.headers.get("range"))
                self.assertEqual(request.headers.get("if-match"), '"v1"')
                return httpx.Response(200, content=b"fresh", headers={"ETag": '"v1"'})
            raise AssertionError(f"unexpected {request.method}")

        self.client(handler)
        target = self.root / "download.txt"
        target.write_bytes(b"old")
        partial, identity = webdav_locations._partial_paths(target)
        partial.write_bytes(b"wrong")
        identity.write_text(json.dumps({"etag": '"v1"', "size": 5}), encoding="utf-8")

        original_unlink = Path.unlink

        def forbid_separate_target_unlink(path, *args, **kwargs):
            if path == target:
                raise AssertionError("download publication must not unlink the target first")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", forbid_separate_target_unlink):
            result = webdav_locations.download(
                self.row,
                "file.txt",
                target,
                expected_etag='"v1"',
                expected_size=5,
                resume=True,
            )

        self.assertEqual(target.read_bytes(), b"fresh")
        self.assertEqual(result["size"], 5)
        self.assertEqual([request.method for request in requests], ["GET"])

    def test_upload_is_conditional_and_read_back_verified(self):
        payload = b"verified upload"
        seen_put = []

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "PUT":
                seen_put.append(request)
                return httpx.Response(201, headers={"ETag": '"uploaded"'})
            if request.method == "GET":
                return httpx.Response(200, content=payload, headers={"ETag": '"uploaded"'})
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("buffered upload")):
            result = webdav_locations.upload(self.row, "folder/source.txt", source)
        self.assertEqual(result["size"], len(payload))
        self.assertEqual(seen_put[0].headers.get("if-none-match"), "*")

    def test_upload_rejects_an_empty_normalized_target_before_request(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(500)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(b"must stay local")

        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "path required"):
            webdav_locations.upload(self.row, "./", source)

        self.assertEqual(requests, [])

    def test_upload_verification_accepts_a_max_length_remote_name(self):
        payload = b"verified long name"
        remote_name = f"{'w' * 251}.txt"

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing())
            if request.method == "PUT":
                return httpx.Response(201, headers={"ETag": '"uploaded"'})
            if request.method == "GET":
                return httpx.Response(200, content=payload, headers={"ETag": '"uploaded"'})
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(payload)

        with (
            patch("services.webdav_locations.data_dir", return_value=self.root),
            patch.object(
                webdav_locations,
                "capabilities",
                return_value={"supports_etag": True},
            ),
        ):
            result = webdav_locations.upload(self.row, remote_name, source)

        self.assertEqual(result["size"], len(payload))

    def test_upload_without_conditional_capability_fails_before_target_put(self):
        payload = b"verified without an etag"
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=empty_listing(etag=""))
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "without-etag.txt"
        source.write_bytes(payload)

        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "stable ETags"):
            webdav_locations.upload(self.row, "without-etag.txt", source)

        self.assertEqual([request.method for request in requests], ["OPTIONS", "PROPFIND"])

    def test_delete_requires_and_sends_the_verified_etag(self):
        deletes = []

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "DELETE":
                deletes.append(request)
                return httpx.Response(204)
            raise AssertionError(request.method)

        self.client(handler)
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "ETag"):
            webdav_locations.delete(self.row, "file.txt")
        webdav_locations.delete(self.row, "file.txt", expected_etag='"child-etag"')
        self.assertEqual(deletes[0].headers.get("if-match"), '"child-etag"')

    def test_move_requires_and_sends_the_verified_source_etag(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(201)

        self.client(handler)
        with self.assertRaisesRegex(webdav_locations.WebDAVLocationError, "ETag"):
            webdav_locations.copy_or_move(
                self.row,
                "source.txt",
                "destination.txt",
                move=True,
            )
        self.assertEqual(requests, [])

        webdav_locations.copy_or_move(
            self.row,
            "source.txt",
            "destination.txt",
            move=True,
            expected_etag='"source-v1"',
        )
        self.assertEqual([request.method for request in requests], ["MOVE"])
        self.assertEqual(requests[0].headers.get("if-match"), '"source-v1"')

    def test_send_uses_httpx_streaming_mode(self):
        class StreamingClient:
            def build_request(self, method, url, **kwargs):
                return httpx.Request(method, url, **kwargs)

            def send(self, request, *, stream=False):
                self.stream = stream
                return httpx.Response(204, request=request)

        client = StreamingClient()
        response = webdav_locations._send(client, "OPTIONS", "https://dav.example.test/dav/")
        self.assertTrue(client.stream)
        response.close()

    def test_stale_etag_preserves_incoming_bytes_while_remote_remains_untouched(self):
        remote = b"remote changed copy"
        gets = []

        def handler(request):
            if request.method == "OPTIONS":
                return httpx.Response(204, headers={"Allow": "PROPFIND, GET, PUT, DELETE"})
            if request.method == "PROPFIND":
                return httpx.Response(207, content=listing())
            if request.method == "PUT":
                self.assertEqual(request.headers.get("if-match"), '"old"')
                return httpx.Response(412)
            if request.method == "GET":
                gets.append(request)
                return httpx.Response(200, content=remote, headers={"ETag": '"new"'})
            raise AssertionError(request.method)

        self.client(handler)
        source = self.root / "source.txt"
        source.write_bytes(b"local change")
        with patch("services.webdav_locations.data_dir", return_value=self.root):
            with self.assertRaises(webdav_locations.WebDAVConflictError) as caught:
                webdav_locations.upload(self.row, "source.txt", source, expected_etag='"old"')
        self.assertEqual(caught.exception.conflict_path.read_bytes(), b"local change")
        self.assertEqual(gets, [])

    def test_unsafe_xml_redirect_quota_and_timeout_fail_closed(self):
        cases = [
            httpx.Response(207, content=b'<!DOCTYPE x [<!ENTITY y "z">]><x/>'),
            httpx.Response(302, headers={"Location": "https://other.test"}),
            httpx.Response(507),
            httpx.ReadTimeout("slow"),
        ]
        for result in cases:
            with self.subTest(result=type(result).__name__):

                def handler(request, result=result):
                    if isinstance(result, Exception):
                        raise result
                    return result

                self.client(handler)
                with self.assertRaises(webdav_locations.WebDAVLocationError):
                    webdav_locations.listdir(self.row)


if __name__ == "__main__":
    unittest.main()
