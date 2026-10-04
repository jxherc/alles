"""Managed search tests reject malformed localhost replies without claiming success."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from services import managed_searxng as ms
from tests._client import ApiTest


class SearchFixture(BaseHTTPRequestHandler):
    payload = {}
    status_code = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        assert self.path.startswith("/search?")
        payload = (
            self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        )
        self.send_response(self.status_code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ManagedSearchResultTests(ApiTest):
    def check_search(self, payload, expected_status, response_status=200):
        SearchFixture.payload = payload
        SearchFixture.status_code = response_status
        server = ThreadingHTTPServer(("127.0.0.1", 0), SearchFixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with (
                mock.patch.object(ms, "status", return_value={"healthy": True}),
                mock.patch.object(
                    ms, "managed_url", return_value=f"http://127.0.0.1:{server.server_port}"
                ),
            ):
                result = self.client.post("/api/system/searxng/test")
            self.assertEqual(result.status_code, expected_status, result.text)
            if expected_status == 200:
                self.assertEqual(result.json(), {"ok": True, "results": len(payload["results"])})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_missing_results_is_not_a_successful_search_test(self):
        self.check_search({"error": "owned invalid result"}, 409)

    def test_string_results_is_not_a_successful_search_test(self):
        self.check_search({"results": "owned invalid result"}, 409)

    def test_non_object_response_is_not_a_successful_search_test(self):
        self.check_search([], 409)

    def test_normal_results_remain_a_successful_search_test(self):
        self.check_search({"results": [{"title": "owned result", "url": "/owned"}]}, 200)

    def test_normal_empty_results_remain_a_successful_search_test(self):
        self.check_search({"results": []}, 200)

    def test_invalid_json_returns_a_retryable_search_failure(self):
        self.check_search(b"not json", 409)

    def test_service_http_failure_returns_a_retryable_search_failure(self):
        self.check_search({"error": "owned unavailable service"}, 409, response_status=503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
