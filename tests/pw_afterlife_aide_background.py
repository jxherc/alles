"""Browser gate for automatic, same-task Aide background work."""

import json
import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8045")
HOME = f"http://127.0.0.1:{PORT}"
URL = f"http://aide.localhost:{PORT}/"


def _require_throwaway_data_root() -> None:
    raw = os.environ.get("ALLES_DATA", "").strip()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if os.environ.get("ALLES_TEST_DATA") != "1" or not raw or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    data = Path(raw).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(HOME, run_id)


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    handoffs: list[dict] = []
    chat_requests: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                errors.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None
            ),
        )
        page.on(
            "console",
            lambda message: (
                errors.append(message.text)
                if message.type == "error" and "Failed to load resource" not in message.text
                else None
            ),
        )

        endpoint = {
            "id": "local-test",
            "name": "local test",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "models": ["small-local"],
            "image_models": [],
            "unavailable_models": [],
        }
        page.route(
            "**/api/models",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps([endpoint])
            ),
        )
        page.route(
            "**/api/models/roles",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "aide_chat": {
                            "status": "ready",
                            "effective": {
                                "endpoint_id": "local-test",
                                "model": "small-local",
                            },
                        }
                    }
                ),
            ),
        )

        def sessions(route):
            if route.request.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "id": "same-task",
                            "name": "new task",
                            "model": "",
                            "endpoint_id": "",
                            "mode": "agent",
                            "project_id": None,
                        }
                    ),
                )
            else:
                route.fulfill(status=200, content_type="application/json", body="[]")

        page.route("**/api/sessions", sessions)
        page.route(
            "**/api/sessions/same-task/git/branches",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "available": False,
                        "current": "",
                        "branches": [],
                        "dirty": False,
                    }
                ),
            ),
        )
        page.route(
            "**/api/chat",
            lambda route: (
                chat_requests.append(route.request.post_data_json),
                route.fulfill(status=500, body="normal chat should not run"),
            )[-1],
        )

        def background_api(route):
            url = route.request.url
            if "/handoffs/preview" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "endpoint_id": "local-test",
                            "endpoint": "local test",
                            "model": "small-local",
                            "privacy_class": "local",
                        }
                    ),
                )
            elif url.endswith("/api/jarvis/handoffs"):
                handoffs.append(route.request.post_data_json)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "run-1", "session_id": "same-task", "state": "queued"}),
                )
            elif url.endswith("/run-1/cancel"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {"id": "run-1", "session_id": "same-task", "state": "cancelled"}
                    ),
                )
            elif url.endswith("/run-1"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "run-1", "session_id": "same-task", "state": "running"}),
                )
            elif "/runs?limit=" in url:
                route.fulfill(status=200, content_type="application/json", body="[]")
            else:
                route.continue_()

        page.route("**/api/jarvis/**", background_api)
        page.goto(URL, wait_until="domcontentloaded")
        page.locator("#composer-ta").wait_for()
        page.locator("#composer-ta").fill("check this in the background")
        page.locator("#send-btn").click()
        card = page.locator(".aide-background-card")
        card.wait_for()
        card.get_by_role("button", name="cancel").wait_for()

        assert handoffs and handoffs[0]["session_id"] == "same-task"
        assert handoffs[0]["request"] == "check this in the background"
        assert handoffs[0]["permission_mode"] in {"full_access", "full_auto", "approve", "plan"}
        assert handoffs[0]["effort"] == "medium"
        assert chat_requests == []
        assert "jarvis" not in card.inner_text().lower()
        assert page.locator(".confirm-modal:visible, .dialog-overlay:visible").count() == 0
        assert page.locator('select:visible, input[type="radio"]:visible').count() == 0

        card.get_by_role("button", name="cancel").click()
        card.get_by_role("button", name="retry").wait_for()
        assert "cancelled" in card.inner_text()
        page.screenshot(path="/tmp/alles-phase5-aide-background.png", full_page=True)
        context.close()
        browser.close()

    assert not errors, errors


if __name__ == "__main__":
    run()
