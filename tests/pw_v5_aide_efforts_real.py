"""Real Aide UI gate for model selection, effort profiles, streaming, and recovery.

The provider is an owned loopback OpenAI-compatible fixture. The browser still
uses the shipped endpoint dialog, listbox, composer, session persistence, SSE
parser, and error UI against a real isolated Alles server.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

PORT = os.environ.get("PORT", "8147")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://aide.localhost:{PORT}/"
MODEL_NAME = "gpt-5-kokuen-fixture"
ENDPOINT_NAME = "KOKUEN effort fixture"


def _require_throwaway_server() -> None:
    if os.environ.get("ALLES_TEST_DATA") != "1":
        raise RuntimeError("set ALLES_TEST_DATA=1 for this isolated browser gate")
    raw = os.environ.get("ALLES_DATA", "").strip()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if not raw or len(run_id) < 16:
        raise RuntimeError("set an owned ALLES_DATA and unique ALLES_TEST_RUN_ID")
    data = Path(raw).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be an owned system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match")
    require_server_ownership(HOME, run_id)


class FixtureState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict] = []
        self.failures_remaining = 0

    def record(self, payload: dict) -> int:
        with self.lock:
            self.requests.append(payload)
            return len(self.requests)

    def take_failure(self) -> bool:
        with self.lock:
            if self.failures_remaining <= 0:
                return False
            self.failures_remaining -= 1
            return True

    def set_failures(self, count: int) -> None:
        with self.lock:
            self.failures_remaining = max(0, count)

    def streaming_requests(self) -> list[dict]:
        with self.lock:
            return [dict(item) for item in self.requests if item.get("stream")]

    def streaming_requests_for_user_prefix(self, prefix: str) -> list[dict]:
        matched = []
        for payload in self.streaming_requests():
            messages = payload.get("messages") or []
            user = next(
                (
                    str(message.get("content") or "")
                    for message in reversed(messages)
                    if message.get("role") == "user"
                ),
                "",
            )
            if user.startswith(prefix):
                matched.append(payload)
        return matched


def _handler(state: FixtureState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            pass

        def _json(self, status: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.rstrip("/").endswith("/models"):
                self._json(200, {"object": "list", "data": [{"id": MODEL_NAME}]})
                return
            self.send_error(404)

        def do_POST(self):
            if not self.path.rstrip("/").endswith("/chat/completions"):
                self.send_error(404)
                return
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            call = state.record(payload)
            if state.take_failure():
                self._json(503, {"error": {"message": "intentional fixture interruption"}})
                return
            effort = payload.get("reasoning_effort", "none")
            reply = f"fixture reply {call}: effort {effort}"
            if not payload.get("stream"):
                self._json(
                    200,
                    {
                        "choices": [{"message": {"role": "assistant", "content": reply}}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                    },
                )
                return
            chunks = [
                {"choices": [{"delta": {"content": reply[:18]}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": reply[18:]}, "finish_reason": None}]},
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                },
            ]
            raw = (
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def api(method: str, path: str, body=None):
    raw = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{HOME}{path}",
        data=raw,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _choose_effort(page, effort: str, *, keyboard: bool) -> None:
    page.locator("#effort-btn").click()
    choice = page.locator(f'#perm-menu [data-kind="effort"][data-v="{effort}"]')
    choice.scroll_into_view_if_needed()
    if keyboard:
        choice.focus()
        page.keyboard.press("Enter")
    else:
        choice.click()
    expect(page.locator("#effort-btn .effort-label")).to_have_text(effort.replace("_", " "))


def _send_and_wait(page, text: str, expected_count: int) -> None:
    before = page.locator("#messages .ai-wrap").count()
    page.locator("#composer-ta").fill(text)
    page.locator("#send-btn").click()
    page.wait_for_function(
        """([before]) => {
          const rows = [...document.querySelectorAll('#messages .ai-wrap')];
          const last = rows.at(-1);
          return rows.length > before
            && last?.querySelector('.ai-body.done')
            && last.querySelector('.ai-content')?.textContent.includes('fixture reply');
        }""",
        arg=[before],
        timeout=20_000,
    )
    assert page.locator("#messages .ai-content", has_text="fixture reply").count() >= expected_count
    expect(page.locator("#send-btn")).to_be_enabled()


def run() -> None:
    _require_throwaway_server()
    state = FixtureState()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    endpoint_id = ""
    session_id = ""
    settings = api("GET", "/api/settings")
    original = {
        "default_endpoint_id": settings.get("default_endpoint_id", ""),
        "default_model": settings.get("default_model", ""),
        "model_roles": settings.get("model_roles", {}),
    }
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1366, "height": 920},
                reduced_motion="reduce",
                service_workers="block",
            )
            page = context.new_page()
            page.set_default_timeout(10_000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(URL, wait_until="networkidle")
            page.wait_for_selector("#composer-ta:visible")

            # Add and probe the local endpoint through the shipped dialog.
            model_button = page.locator("#aide-model-choice")
            model_button.click()
            dialog = page.locator("#model-modal")
            expect(dialog).to_be_visible()
            assert page.locator("#model-search-input").evaluate(
                "el => el === document.activeElement"
            )
            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
            assert model_button.evaluate("el => el === document.activeElement")

            model_button.click()
            models_tab = page.locator('.mm-tab[data-tab="models"]')
            models_tab.focus()
            page.keyboard.press("ArrowRight")
            endpoints_tab = page.locator('.mm-tab[data-tab="endpoints"]')
            assert endpoints_tab.get_attribute("aria-selected") == "true"
            assert endpoints_tab.evaluate("el => el === document.activeElement")
            page.locator("#ep-name").fill(ENDPOINT_NAME)
            page.locator("#ep-url").fill(f"http://127.0.0.1:{provider.server_port}/v1")
            page.locator("#ep-add-btn").click()
            expect(page.locator("#toast-container .toast").last).to_contain_text("endpoint added")
            card = page.locator(".mm-ep-card", has_text=ENDPOINT_NAME)
            expect(card).to_be_visible()
            card.locator(".mm-test-btn").click()
            expect(page.locator("#toast-container .toast").last).to_contain_text("success")

            endpoints_tab.focus()
            page.keyboard.press("ArrowLeft")
            expect(page.locator("#mm-panel-models")).to_be_visible()
            model_row = page.locator(f'.model-row[data-model="{MODEL_NAME}"]')
            expect(model_row).to_be_visible()
            assert model_row.get_attribute("role") == "option"
            assert model_row.evaluate(
                "el => el.getBoundingClientRect().height >= 44 && el.getBoundingClientRect().width >= 44"
            )
            model_row.focus()
            page.keyboard.press("Enter")
            expect(dialog).to_be_hidden()
            expect(page.locator("#aide-model-choice-label")).to_contain_text("gpt 5 kokuen fixture")
            assert model_button.evaluate("el => el === document.activeElement")

            endpoints = api("GET", "/api/models")
            endpoint_id = next(item["id"] for item in endpoints if item["name"] == ENDPOINT_NAME)

            # Every effort profile reaches the real provider boundary. Low, max,
            # and custom repeat to prove the state is reusable rather than one-shot.
            sequence = [
                ("low", False),
                ("low", True),
                ("medium", True),
                ("high", False),
                ("xhigh", True),
                ("max", False),
                ("max", True),
                ("deep_work", False),
                ("custom", True),
                ("custom", False),
            ]
            for index, (effort, keyboard) in enumerate(sequence, 1):
                _choose_effort(page, effort, keyboard=keyboard)
                if effort == "custom":
                    menu = page.locator("#perm-menu.effort-menu")
                    expect(menu).to_be_visible()
                    if index == 9:
                        menu.locator('[data-turn-delta="1"]').click()
                        menu.locator('[data-custom-key="verification"]').click()
                        # Exercise both switches twice so the safe final value remains off.
                        for key in ("delegation", "workflows"):
                            menu.locator(f'[data-custom-key="{key}"]').click()
                            menu.locator(f'[data-custom-key="{key}"]').click()
                    page.keyboard.press("Escape")
                    expect(menu).to_be_hidden()
                _send_and_wait(page, f"effort {effort} pass {index}", index)
                if not session_id:
                    session_id = page.evaluate("location.hash.slice(1)")
                    assert session_id

            expected = [
                "low",
                "low",
                "medium",
                "high",
                "high",
                "high",
                "high",
                "high",
                "high",
                "high",
            ]
            effort_requests = state.streaming_requests_for_user_prefix("effort ")
            recorded = [item.get("reasoning_effort") for item in effort_requests]
            assert recorded == expected, recorded

            # An unsupported explicit reasoning switch fails visibly before any
            # provider request. Automatic mode then recovers through the same UI.
            page.locator("#effort-btn").click()
            reasoning_off = page.locator('#perm-menu [data-kind="reasoning"][data-v="off"]')
            reasoning_off.scroll_into_view_if_needed()
            reasoning_off.click()
            before_provider = len(state.streaming_requests())
            before_rows = page.locator("#messages .ai-wrap").count()
            page.locator("#composer-ta").fill("explicit reasoning compatibility check")
            page.locator("#send-btn").click()
            page.wait_for_function(
                """([before]) => {
                  const rows = [...document.querySelectorAll('#messages .ai-wrap')];
                  return rows.length > before && rows.at(-1)?.querySelector('.error-msg');
                }""",
                arg=[before_rows],
            )
            expect(page.locator("#messages .error-msg").last).to_contain_text(
                "reasoning_control_unsupported"
            )
            assert len(state.streaming_requests()) == before_provider
            page.locator("#effort-btn").click()
            automatic = page.locator('#perm-menu [data-kind="reasoning"][data-v="automatic"]')
            automatic.scroll_into_view_if_needed()
            automatic.focus()
            page.keyboard.press("Enter")
            _send_and_wait(page, "automatic reasoning recovery", 11)

            # One transient provider failure is recovered automatically by the
            # agent runtime, with the retry reaching the real provider boundary.
            before_provider = len(state.streaming_requests())
            state.set_failures(1)
            _send_and_wait(page, "transient provider retry", 12)
            assert len(state.streaming_requests()) >= before_provider + 2

            # Exhausted automatic retries render the provider error, release the
            # composer, and permit a successful owner-initiated retry.
            state.set_failures(3)
            before_rows = page.locator("#messages .ai-wrap").count()
            page.locator("#composer-ta").fill("provider interruption")
            page.locator("#send-btn").click()
            page.wait_for_function(
                """([before]) => {
                  const rows = [...document.querySelectorAll('#messages .ai-wrap')];
                  return rows.length > before
                    && rows.at(-1)?.querySelector('.ai-body.done .error-msg')?.textContent.includes('HTTP 503');
                }""",
                arg=[before_rows],
            )
            expect(page.locator("#send-btn")).to_be_enabled()
            _send_and_wait(page, "provider manual retry", 13)

            # Persisted session history survives a true reload.
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#composer-ta:visible")
            expect(
                page.locator("#messages .ai-content", has_text="fixture reply").last
            ).to_be_visible()
            assert page.locator("#effort-btn .effort-label").inner_text().strip() == "custom"
            assert not page.locator(
                "select:visible, input[type=checkbox]:visible, input[type=radio]:visible"
            ).count()
            expected_conflicts = [error for error in errors if "status of 409 (Conflict)" in error]
            unexpected_errors = [error for error in errors if error not in expected_conflicts]
            assert len(expected_conflicts) == 1, errors
            assert not unexpected_errors, unexpected_errors
            page.screenshot(path="/tmp/alles-v5-aide-efforts.png", full_page=True)
            context.close()
            browser.close()
    finally:
        cleanup_error = None
        if session_id:
            try:
                api("DELETE", f"/api/sessions/{session_id}")
            except Exception as exc:
                cleanup_error = exc
        try:
            api("PATCH", "/api/settings", original)
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if endpoint_id:
            try:
                api("DELETE", f"/api/models/endpoint/{endpoint_id}")
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        provider.shutdown()
        provider.server_close()
        thread.join(5)
        if cleanup_error:
            raise cleanup_error
    print(
        "Aide real model/effort gate passed: dialog focus, endpoint probe/test, "
        "all 7 efforts, repeated low/max/custom, reasoning recovery, automatic and manual 503 retry, reload"
    )


if __name__ == "__main__":
    run()
