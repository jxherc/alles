"""Opt-in network browser gate for an automatic Andromeda AI Overview.

The model is a local OpenAI-compatible HTTP fixture. Search, page extraction,
model selection, evidence verification, streaming, and rendering stay real. The
gate refuses to run without both a throwaway-data ownership sentinel and the
explicit ``ALLES_ALLOW_NETWORK_TESTS=1`` acknowledgement.
"""

import json
import os
import re
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://andromeda.localhost:{PORT}/"


def _require_safe_live_gate() -> None:
    if os.environ.get("ALLES_ALLOW_NETWORK_TESTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise RuntimeError("set ALLES_ALLOW_NETWORK_TESTS=1 for this opt-in network gate")
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated Andromeda gate")
    raw = os.environ.get("ALLES_DATA", "").strip()
    if not raw:
        raise RuntimeError("set ALLES_DATA to this browser run's temporary data folder")
    data = Path(raw).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        relative = data.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if not relative.parts:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser run")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(HOME, run_id)


class ModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        bundle = json.loads(request["messages"][-1]["content"])
        source = bundle["sources"][0]
        passage = source["passages"][0]
        sentence = re.search(r".{35,240}?[.!?](?:\s|$)", passage)
        quote = sentence.group(0).strip() if sentence else passage[:240].strip()
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": quote,
                        "citations": [{"source_id": source["id"], "quote": quote}],
                    }
                ]
            }
        )
        chunks = [
            {"choices": [{"delta": {"content": raw}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        body = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def api(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{HOME}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def run() -> None:
    _require_safe_live_gate()
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    endpoint_id = ""
    settings = api("GET", "/api/settings")
    original = {
        "default_endpoint_id": settings.get("default_endpoint_id", ""),
        "default_model": settings.get("default_model", ""),
        "model_roles": settings.get("model_roles", {}),
        "andromeda_model_band": settings.get("andromeda_model_band", "standard"),
        "andromeda_model_bands": settings.get("andromeda_model_bands", {}),
        "andromeda_overview": settings.get("andromeda_overview", True),
        "search_provider": settings.get("search_provider", "duckduckgo"),
        "search_fallback": settings.get("search_fallback", "duckduckgo"),
        "search_fallback_chain": settings.get("search_fallback_chain", ["duckduckgo"]),
    }
    try:
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "local deepseek fixture",
                "base_url": f"http://127.0.0.1:{model_server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )
        endpoint_id = endpoint["id"]
        api(
            "PATCH",
            f"/api/models/endpoint/{endpoint_id}",
            {"models": ["deepseek-v4-pro"]},
        )
        roles = dict(original["model_roles"])
        roles["andromeda_answer"] = {"endpoint_id": endpoint_id, "model": "deepseek-v4-pro"}
        bands = dict(original["andromeda_model_bands"])
        bands["standard"] = {"endpoint_id": endpoint_id, "model": "deepseek-v4-pro"}
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint_id,
                "default_model": "deepseek-v4-pro",
                "model_roles": roles,
                "andromeda_model_band": "standard",
                "andromeda_model_bands": bands,
                "andromeda_overview": True,
                "search_provider": "searxng",
                "search_fallback": "wikipedia",
                "search_fallback_chain": ["wikipedia"],
            },
        )

        errors: list[str] = []
        overview_responses: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "response",
                lambda response: (
                    overview_responses.append(response.text())
                    if response.url.endswith("/api/andromeda/overview")
                    else None
                ),
            )
            page.goto(URL, wait_until="networkidle")
            page.locator("#andromeda-query").fill("example domain")
            page.locator("#andromeda-form").press("Enter")
            page.wait_for_function(
                """() => {
                  const value = document.querySelector('#andromeda-overview-state')?.textContent || '';
                  return value.includes('checked against exact source passages')
                    || value.includes('not enough trustworthy evidence')
                    || value.includes('overview failed');
                }""",
                timeout=60_000,
            )
            state = page.locator("#andromeda-overview-state").inner_text().strip()
            assert "checked against exact source passages" in state, (
                state,
                overview_responses,
                errors,
            )
            answer = page.locator("#andromeda-key-answer-text").inner_text().strip().splitlines()[0]
            assert answer.endswith("."), answer
            assert 1 <= len(answer.split()) <= 12, answer
            assert page.locator("#andromeda-key-answer").is_visible()
            assert page.locator(".andromeda-result-title").count() >= 5
            assert page.locator("#andromeda-overview").is_visible()
            assert not errors, errors
            page.screenshot(path="/tmp/alles-phase6-andromeda-ai-live.png", full_page=True)
            browser.close()
    finally:
        cleanup_error = None
        try:
            api("PATCH", "/api/settings", original)
        except Exception as exc:
            cleanup_error = exc
        try:
            if endpoint_id:
                api("DELETE", f"/api/models/endpoint/{endpoint_id}")
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        model_server.shutdown()
        model_server.server_close()
        model_thread.join(5)
        if cleanup_error is not None:
            raise cleanup_error
    print("live automatic Andromeda AI Overview gate passed")


if __name__ == "__main__":
    run()
