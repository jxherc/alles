"""Real-server browser gate for Aide selectable questions and reload reattachment."""

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

PORT = os.environ.get("PORT", "8992")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://aide.localhost:{PORT}/"


def _require_throwaway_data_root() -> None:
    if os.environ.get("ALLES_TEST_DATA") != "1":
        raise RuntimeError("set ALLES_TEST_DATA=1 for this isolated browser gate")
    data = Path(os.environ.get("ALLES_DATA", "")).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "")
    if not run_id or data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be an owned system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match")
    require_server_ownership(HOME, run_id)


class QuestionModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        messages = request.get("messages") or []
        has_answer = any(message.get("role") == "tool" for message in messages)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        if has_answer:
            chunks = [
                {"choices": [{"delta": {"content": "question answer received"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        else:
            arguments = json.dumps(
                {
                    "title": "Choose the verification",
                    "questions": [
                        {
                            "id": "surface",
                            "prompt": "Which surface should Aide verify first?",
                            "choices": [
                                {"id": "files", "label": "Files"},
                                {
                                    "id": "aide",
                                    "label": "Aide",
                                    "description": "question cards and background resume",
                                },
                            ],
                            "allow_free_text": True,
                            "free_text_label": "extra detail",
                        },
                        {
                            "id": "proof",
                            "prompt": "Which proof should be included?",
                            "selection": "multiple",
                            "choices": [
                                {"id": "desktop", "label": "desktop"},
                                {"id": "phone", "label": "phone"},
                                {"id": "keyboard", "label": "keyboard"},
                            ],
                        },
                    ],
                }
            )
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "question-call",
                                        "type": "function",
                                        "function": {"name": "ask_user", "arguments": arguments},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.05)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def api(method, path, body=None):
    request = urllib.request.Request(
        f"{HOME}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def run() -> None:
    _require_throwaway_data_root()
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), QuestionModelHandler)
    thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    thread.start()
    endpoint_id = ""
    original = api("GET", "/api/settings")
    original_settings = {
        "default_endpoint_id": original.get("default_endpoint_id", ""),
        "default_model": original.get("default_model", ""),
        "model_roles": original.get("model_roles", {}),
    }
    try:
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "selectable question fixture",
                "base_url": f"http://127.0.0.1:{model_server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )
        endpoint_id = endpoint["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint_id}", {"models": ["question-model"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint_id,
                "default_model": "question-model",
                "model_roles": {
                    **original_settings["model_roles"],
                    "aide_chat": {"endpoint_id": endpoint_id, "model": "question-model"},
                },
            },
        )
        session = api(
            "POST",
            "/api/sessions",
            {"name": "question browser gate", "mode": "jarvis", "endpoint_id": endpoint_id, "model": "question-model"},
        )
        api(
            "POST",
            "/api/agent/background",
            {"session_id": session["id"], "message": "ask me for the verification scope", "mode": "agent"},
        )

        errors = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(f"{URL}#{session['id']}", wait_until="networkidle")
            page.wait_for_selector(".bg-reattach .aide-question-card")
            card = page.locator(".bg-reattach .aide-question-card")
            assert card.locator("input[type=radio], input[type=checkbox], select").count() == 0
            assert card.locator('[role="radiogroup"]').count() == 1
            assert card.locator('[role="group"]').count() == 1
            assert card.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            page.screenshot(path="/tmp/alles-aide-question-desktop.png", full_page=True)

            page.reload(wait_until="networkidle")
            page.wait_for_selector(".bg-reattach .aide-question-card")
            card = page.locator(".bg-reattach .aide-question-card")
            first = card.locator('[data-aide-question-id="surface"] [data-choice-id]').first
            first.focus()
            page.keyboard.press("ArrowDown")
            assert card.locator('[data-choice-id="aide"]').evaluate("el => el === document.activeElement")
            page.keyboard.press("Enter")
            assert card.locator('[data-choice-id="aide"]').get_attribute("aria-checked") == "true"
            card.locator("[data-question-free-text]").fill("include reload and focus")
            card.locator('[data-aide-question-id="proof"] [data-choice-id="desktop"]').click()
            phone = card.locator('[data-aide-question-id="proof"] [data-choice-id="phone"]')
            phone.focus()
            page.keyboard.press("Space")
            assert phone.get_attribute("aria-checked") == "true"

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
            assert card.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            page.screenshot(path="/tmp/alles-aide-question-phone.png", full_page=True)
            card.locator(".aide-question-submit").click()
            page.wait_for_function(
                "() => [...document.querySelectorAll('#messages .ai-content')].some(el => el.textContent.includes('question answer received'))",
                timeout=20_000,
            )
            assert page.locator(".aide-question-card:not(.answered):not(.cancelled)").count() == 0
            browser.close()
        if errors:
            raise AssertionError("Aide question browser errors:\n" + "\n".join(errors))
    finally:
        cleanup_error = None
        try:
            api("PATCH", "/api/settings", original_settings)
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
        if cleanup_error:
            raise cleanup_error
    print("Aide selectable-question real browser gate passed")


if __name__ == "__main__":
    run()
