"""Real-server Phase 6 gate for streamed Aide continuity, stop, and retry."""

import json
import os
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8942")
HOME = f"http://localhost:{PORT}"


def _require_throwaway_data_root() -> None:
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated continuity gate")
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
        prompt = json.dumps(request.get("messages") or [])
        if "phase6 failure probe" in prompt:
            body = json.dumps({"error": {"message": "temporary model failure"}}).encode()
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not request.get("stream"):
            body = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ready"}}]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        time.sleep(0.5)
        for token in ("phase ", "six ", "streaming ", "reply ", "finished"):
            chunk = {"choices": [{"delta": {"content": token}, "finish_reason": None}]}
            try:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.25)
        done = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        try:
            self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{HOME}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def session_count():
    groups = api("GET", "/api/sessions")
    return sum(len(rows) for rows in groups.values() if isinstance(rows, list))


def run():
    _require_throwaway_data_root()
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    thread.start()
    endpoint_id = ""
    settings = api("GET", "/api/settings")
    original = {
        "default_endpoint_id": settings.get("default_endpoint_id", ""),
        "default_model": settings.get("default_model", ""),
        "model_roles": settings.get("model_roles", {}),
    }
    try:
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "phase 6 continuity",
                "base_url": f"http://127.0.0.1:{model_server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )
        endpoint_id = endpoint["id"]
        api(
            "PATCH",
            f"/api/models/endpoint/{endpoint['id']}",
            {"models": ["phase6-continuity"]},
        )
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint["id"],
                "default_model": "phase6-continuity",
                "model_roles": {
                    **original["model_roles"],
                    "aide_chat": {
                        "endpoint_id": endpoint["id"],
                        "model": "phase6-continuity",
                    },
                },
            },
        )

        errors = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text)
                    if message.type == "error" and "503" not in message.text
                    else None
                ),
            )
            page.goto(f"http://aide.localhost:{PORT}/", wait_until="networkidle")
            page.wait_for_selector("#composer-ta:visible")
            page.wait_for_function(
                "document.querySelector('#model-label')?.textContent.trim() === 'phase6 continuity'"
            )
            initial_sessions = session_count()

            def send(message):
                page.locator("#composer-ta").fill(message)
                page.locator("#send-btn").click()

            def wait_finished(user_count):
                page.wait_for_function(
                    f"document.querySelectorAll('#messages .user-bubble').length === {user_count}"
                )
                page.wait_for_function(
                    """() => {
                      const answers = [...document.querySelectorAll('#messages .ai-content')];
                      return answers.at(-1)?.textContent.includes('phase six streaming reply finished');
                    }"""
                )
                page.wait_for_function(
                    """() => !document.querySelector('#send-btn')?.disabled
                      && !document.querySelector('#stop-btn')?.classList.contains('visible')"""
                )
                page.wait_for_function(
                    "document.querySelectorAll('.aide-run-progress').length === 0"
                )
                assert page.locator(".aide-run-progress").count() == 0

            send("continuity one")
            page.wait_for_selector(".aide-run-progress")
            assert page.locator(".aide-run-progress").inner_text() == "typing"
            assert page.get_by_text("started in aide", exact=False).count() == 0
            page.wait_for_function(
                """() => {
                  const answer = [...document.querySelectorAll('#messages .ai-content')].at(-1);
                  return answer?.textContent.includes('phase')
                    && !answer.textContent.includes('finished')
                    && document.querySelector('#send-btn')?.disabled;
                }"""
            )
            wait_finished(1)
            assert page.locator("#aide-message-rail").is_hidden()

            send("continuity two")
            wait_finished(2)
            assert page.locator("#aide-message-rail").is_hidden()

            send("stop this stream")
            page.wait_for_function(
                "document.querySelectorAll('#messages .user-bubble').length === 3"
            )
            page.wait_for_selector("#stop-btn.visible")
            page.wait_for_timeout(350)
            page.locator("#stop-btn").click()
            page.wait_for_function(
                "!document.querySelector('#stop-btn')?.classList.contains('visible')"
            )
            assert page.locator(".aide-run-progress").count() == 0

            send("retry after stop")
            wait_finished(4)
            assert page.locator("#messages .user-bubble").count() == 4
            assert page.locator("#aide-message-rail-track button").count() == 4
            assert page.locator("#aide-message-rail:not([hidden])").is_visible()
            assert page.locator(".aide-run-progress").count() == 0

            send("phase6 failure probe")
            page.wait_for_selector("#messages .error-msg")
            page.wait_for_function(
                """() => !document.querySelector('#send-btn')?.disabled
                  && !document.querySelector('#stop-btn')?.classList.contains('visible')"""
            )
            assert page.locator(".aide-run-progress").count() == 0

            send("reconnect after failure")
            wait_finished(6)
            assert page.locator("#messages .user-bubble").count() == 6
            assert page.locator(".aide-run-progress").count() == 0
            final_sessions = session_count()
            assert final_sessions == initial_sessions + 1, (initial_sessions, final_sessions)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path="/tmp/alles-phase6-stream-continuity.png", full_page=True)
            browser.close()
        if errors:
            raise AssertionError("browser console errors:\n" + "\n".join(errors))
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
        thread.join(5)
        if cleanup_error is not None:
            raise cleanup_error
    print("phase 6 stream continuity gate passed")


if __name__ == "__main__":
    run()
