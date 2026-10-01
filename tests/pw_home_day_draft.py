"""Home's day question stays private and unsent on one or several app hosts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

MARKER = "private calendar marker"
TODAY = {
    "date": "2026-09-27",
    "partial_sources": [],
    "sections": {
        "needs_you": [],
        "today": {
            "events": [{"time": "09:30", "title": MARKER}],
            "tasks": {"open_count": 1, "overdue": [], "due_today": [{"title": "review notes"}]},
            "reminders": [],
            "renewing": [],
            "day_events": [],
            "habits": [],
        },
        "in_progress": [],
        "briefs": [],
        "shortcuts": [],
    },
}


def run() -> None:
    port = os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    backend = f"http://127.0.0.1:{port}"
    require_server_ownership(backend, run_id)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width in (1440, 390):
            for host in ("127.0.0.1", "localhost"):
                multi_host = host == "localhost"
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    is_mobile=width == 390,
                    has_touch=width == 390,
                    reduced_motion="reduce",
                    service_workers="block",
                )
                page = context.new_page()
                page.set_default_timeout(15_000)
                errors: list[str] = []
                writes: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        writes.append(request.url)
                        if request.method == "POST"
                        and request.url.endswith(("/api/chat", "/api/sessions"))
                        else None
                    ),
                )
                page.route(
                    "**/api/today?*",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(TODAY),
                    ),
                )
                page.goto(f"http://{host}:{port}/", wait_until="networkidle")
                if page.locator("#setup-wizard").is_visible():
                    page.locator("#setup-skip").click()
                    page.locator("#setup-wizard").wait_for(state="hidden")
                expect(page.locator("#today-view")).to_be_visible()
                expect(page.get_by_text(MARKER)).to_be_visible()

                action = page.locator("#today-ask-aide")
                if width == 1440:
                    action.focus()
                    action.press("Enter")
                else:
                    action.click()
                expect(page.locator("#composer-ta")).to_be_visible()
                if multi_host:
                    expect(page).to_have_url(re.compile(rf"http://aide\.localhost:{port}/"))
                expect(page.locator("body")).to_have_class(re.compile(r"\bis-incognito\b"))
                expect(page.locator("#composer-ta")).to_have_value(re.compile(MARKER))
                expect(page.locator("#composer-ta")).to_be_focused()
                permission = page.locator("#perm-mode-btn")
                expect(permission).to_be_visible()
                expect(permission).to_have_attribute("aria-label", re.compile(r"^permission: "))
                box = permission.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, box
                permission.click()
                menu = page.locator("#perm-menu")
                expect(menu).to_be_visible()
                expect(menu.locator('[aria-checked="true"]')).to_have_count(1)
                page.keyboard.press("Escape")
                expect(menu).to_have_count(0)
                expect(permission).to_be_focused()
                expect(page.locator("#aide-model-choice")).to_be_visible()
                if width == 390:
                    choice = page.locator("#aide-model-choice")
                    box = choice.bounding_box()
                    assert box and box["width"] >= 44 and box["height"] >= 44, box
                    choice.click()
                    expect(page.locator("#model-modal")).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(page.locator("#model-modal")).to_be_hidden()
                    page.locator("#more-tools-btn").click()
                    expect(page.get_by_role("menuitem", name="upload file")).to_be_visible()
                    page.keyboard.press("Escape")
                assert MARKER not in unquote(page.url), page.url
                assert "ctx=" not in page.url, page.url
                assert not writes, writes
                assert page.evaluate("localStorage.getItem('aide-draft-new')") is None
                sessions = context.request.get(f"{backend}/api/sessions").json()
                assert not any(sessions.values()), sessions
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                page.screenshot(
                    path=str(output / f"home-day-draft-{host}-{width}.png"), full_page=True
                )
                if not multi_host:
                    page.go_back(wait_until="networkidle")
                    expect(page.locator("#today-view")).to_be_visible()
                    expect(page.locator("#incognito-bar")).to_be_hidden()
                assert not errors, errors
                if multi_host and width == 1440:
                    page.goto(f"http://{host}:{port}/", wait_until="networkidle")
                    first_redeem = [True]

                    def unavailable_once(route):
                        if first_redeem[0]:
                            first_redeem[0] = False
                            route.fulfill(status=503, body="unavailable")
                        else:
                            route.continue_()

                    page.route("**/api/auth/context-handoff/*", unavailable_once)
                    before = len(errors)
                    page.locator("#today-ask-aide").click()
                    expect(page.locator("#context-handoff-error")).to_be_visible()
                    assert "ctx=" not in page.url, page.url
                    page.locator("#context-handoff-error button").click()
                    expect(page.locator("#composer-ta")).to_have_value(re.compile(MARKER))
                    expect(page.locator("body")).to_have_class(re.compile(r"\bis-incognito\b"))
                    expect(page.locator("#context-handoff-error")).to_be_hidden()
                    assert not writes, writes
                    assert all("503" in error for error in errors[before:]), errors[before:]
                    page.unroute("**/api/auth/context-handoff/*")

                    page.goto(f"http://{host}:{port}/", wait_until="networkidle")
                    page.route(
                        "**/api/auth/context-handoff",
                        lambda route: route.fulfill(status=503, body="unavailable"),
                    )
                    before = len(errors)
                    page.locator("#today-ask-aide").click()
                    expect(page.locator("#today-view")).to_be_visible()
                    expect(page.locator("#toast-container .toast.error").last).to_contain_text(
                        "could not prepare private day question"
                    )
                    assert MARKER not in unquote(page.url), page.url
                    assert all("503" in error for error in errors[before:]), errors[before:]
                context.close()
        browser.close()


if __name__ == "__main__":
    run()
