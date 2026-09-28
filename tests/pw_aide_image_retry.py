"""Image chat retry after the response is lost, against an owned app and loopback provider."""

import base64
import io
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)

    buffer = io.BytesIO()
    Image.new("RGB", (180, 120), (200, 30, 30)).save(buffer, "PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    provider_calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.path == "/v1/images/generations", self.path
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            provider_calls.append(body)
            payload = json.dumps({"data": [{"b64_json": encoded}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for profile, width, theme in (
                    ("desktop-light", 1440, "light"),
                    ("phone-dark", 390, "dark"),
                ):
                    context = browser.new_context(
                        base_url=base,
                        viewport={"width": width, "height": 900},
                        is_mobile=width < 700,
                        has_touch=width < 700,
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    errors = []
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            errors.append(message.text)
                            if message.type == "error" and "503" not in message.text
                            else None
                        ),
                    )
                    try:
                        api = context.request

                        def request(method, path, body=None):
                            response = api.fetch(path, method=method, data=body)
                            assert response.ok, (method, path, response.status, response.text())
                            return response.json()

                        request("POST", "/api/setup/dismiss")
                        endpoint = request(
                            "POST",
                            "/api/models/endpoint",
                            {
                                "name": profile,
                                "base_url": f"http://127.0.0.1:{provider.server_port}",
                                "provider_adapter": "manual",
                            },
                        )
                        request(
                            "PATCH",
                            f"/api/models/endpoint/{endpoint['id']}",
                            {
                                "models": ["chat-fixture"],
                                "image_models": json.dumps(["gpt-image-1"]),
                            },
                        )
                        request(
                            "PATCH",
                            "/api/settings",
                            {
                                "default_endpoint_id": endpoint["id"],
                                "default_model": "chat-fixture",
                                "memory_policy": "off",
                                "memory_auto_inject": False,
                            },
                        )
                        session = request(
                            "POST",
                            "/api/sessions",
                            {
                                "model": "chat-fixture",
                                "endpoint_id": endpoint["id"],
                                "name": profile,
                            },
                        )
                        session_id = session["id"]
                        slot = json.dumps({"endpointId": endpoint["id"], "model": "gpt-image-1"})
                        context.add_init_script(
                            f"localStorage.setItem('aide-image-model', {json.dumps(slot)})"
                        )
                        page.goto(f"/?view=chat#{session_id}", wait_until="networkidle")
                        expect(page.locator("#composer-ta")).to_be_visible()
                        backdrop = page.locator("#nav-backdrop")
                        if backdrop.is_visible():
                            box = backdrop.bounding_box()
                            assert box
                            backdrop.click(position={"x": box["width"] - 12, "y": 200})
                            expect(backdrop).to_be_hidden()
                        requests = []

                        def lose_first_response(route):
                            requests.append(route.request.post_data_json)
                            if len(requests) == 1:
                                response = route.fetch()
                                assert response.status == 200, response.text()
                                route.fulfill(
                                    status=503,
                                    content_type="application/json",
                                    body=json.dumps({"detail": "response lost after save"}),
                                )
                            else:
                                route.continue_()

                        page.route("**/api/images/chat", lose_first_response)
                        before_provider = len(provider_calls)
                        page.locator("#composer-ta").fill("/image a red square")
                        page.locator("#send-btn").click()
                        retry = page.get_by_role("button", name="retry image")
                        expect(retry).to_be_visible()
                        expect(page.get_by_role("alert")).to_contain_text(
                            "response lost after save"
                        )
                        assert len(requests) == 1, requests
                        assert len(provider_calls) == before_provider + 1
                        assert page.locator("#messages .user-bubble").count() == 1
                        box = retry.bounding_box()
                        assert box and box["width"] >= 44 and box["height"] >= 44, box
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        assert page.evaluate("""() => {
                          const status = document.createElement('div');
                          status.className = 'img-gen-status';
                          document.body.append(status);
                          const animation = getComputedStyle(status).animationName;
                          status.remove();
                          return animation === 'none';
                        }""")
                        page.screenshot(path=str(output / f"{profile}-retry.png"))

                        for _ in range(100):
                            if retry.evaluate("element => element === document.activeElement"):
                                break
                            page.keyboard.press("Tab")
                        expect(retry).to_be_focused()
                        page.keyboard.press("Enter")
                        expect(retry).to_have_count(0)
                        expect(page.locator("#messages .ai-content img")).to_be_visible()
                        assert page.locator("#messages .ai-content img").evaluate(
                            "image => image.naturalWidth === 180"
                        )
                        assert len(requests) == 2 and requests[0] == requests[1], requests
                        assert len(provider_calls) == before_provider + 1
                        assert page.locator("#messages .user-bubble").count() == 1
                        assert page.locator("#messages .ai-body").count() == 1
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        history = request("GET", f"/api/sessions/{session_id}/history")
                        assert len(history["messages"]) == 2, history
                        with sqlite3.connect(data / "aide.db") as db:
                            photos = db.execute(
                                "SELECT count(*) FROM photos WHERE caption = ?", ("a red square",)
                            ).fetchone()[0]
                        assert photos == len(results) + 1, photos
                        page.screenshot(path=str(output / f"{profile}-recovered.png"))
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#messages .ai-content img")).to_be_visible()
                        assert not errors, errors
                        results.append(
                            {
                                "scenario_id": "aide.image-retry-after-lost-response",
                                "profile": profile,
                                "status": "passed",
                                "session": session_id,
                                "simulation": "local provider; response lost after server commit",
                            }
                        )
                    finally:
                        context.close()
            finally:
                browser.close()
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
    (output / "scenarios.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    run()
