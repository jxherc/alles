"""Home separates all open tasks from its dated schedule and opens their list."""

import base64
import json
import os
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    timezone_id="UTC",
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
                )
                if zoom:
                    profile = Path(os.environ["ALLES_DATA"]) / label
                    extension = profile / "extension"
                    extension.mkdir(parents=True)
                    (extension / "manifest.json").write_text(
                        json.dumps(
                            dict(
                                manifest_version=3,
                                name="owned zoom check",
                                version="1.0",
                                permissions=["tabs"],
                                background={"service_worker": "zoom.js"},
                            )
                        )
                    )
                    (extension / "zoom.js").write_text(
                        "chrome.runtime.onInstalled.addListener(() => {});"
                    )
                    context = pw.chromium.launch_persistent_context(
                        profile / "browser",
                        channel="chromium",
                        headless=True,
                        args=[
                            f"--disable-extensions-except={extension}",
                            f"--load-extension={extension}",
                        ],
                        **options,
                    )
                else:
                    context = browser.new_context(**options)
                external, errors, console = [], [], []

                def route(request):
                    if urlparse(request.request.url).netloc != urlparse(base).netloc:
                        external.append(request.request.url)
                        return request.abort()
                    return request.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                row = {
                    "scenario_id": "home.task-count-scope",
                    "profile": label,
                    "status": "failed",
                }
                rows.append(row)

                def capture(name):
                    screenshot = context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (output / f"{label}-{name}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )

                task_ids = []
                try:
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(base + "/api/settings", data={"timezone": "UTC"}).ok
                    today = datetime.now(UTC).date()
                    upcoming = api.post(
                        base + "/api/tasks",
                        data={
                            "title": "Tomorrow errand",
                            "due_date": (today + timedelta(days=1)).isoformat(),
                        },
                    ).json()
                    task_ids.append(upcoming["id"])
                    history = api.post(
                        base + "/api/tasks", data={"title": "Already finished"}
                    ).json()
                    task_ids.append(history["id"])
                    assert api.patch(base + "/api/tasks/" + history["id"], data={"done": True}).ok
                    page.goto(base + "/?view=today", wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    count = page.locator(".today-summary-tasks")
                    schedule = page.locator(".today-schedule")
                    expect(count).to_have_text("all open tasks: 1")
                    expect(schedule.locator(".today-row")).to_have_count(0)
                    expect(schedule).not_to_contain_text("open")
                    expect(page.locator("#today-summary")).not_to_contain_text("ready")
                    capture("tomorrow-only")
                    count.press("Enter")
                    first = page.locator('.task-item[data-id="' + upcoming["id"] + '"]')
                    expect(first).to_be_visible()
                    expect(page.locator('.tasks-tab[data-tab="active"]')).to_have_attribute(
                        "aria-pressed", "true"
                    )
                    page.locator('.tasks-tab[data-tab="done"]').click()
                    expect(
                        page.locator('.task-item[data-id="' + history["id"] + '"]')
                    ).to_be_visible()
                    page.locator("#tasks-search").fill("no matching record")
                    expect(page.locator("#tasks-list .task-item")).to_have_count(0)
                    # Existing shell route returns Home without resetting Tasks' in-memory filters.
                    assert page.evaluate("window._navigateHome()")
                    expect(count).to_have_text("all open tasks: 1")
                    count.press("Enter")
                    expect(first).to_be_visible()
                    expect(page.locator("#tasks-search")).to_have_value("")
                    expect(page.locator('.tasks-tab[data-tab="active"]')).to_have_attribute(
                        "aria-pressed", "true"
                    )
                    expect(
                        page.locator('.task-item[data-id="' + history["id"] + '"]')
                    ).to_have_count(0)
                    assert page.evaluate("window._navigateHome()")
                    due = api.post(
                        base + "/api/tasks",
                        data={"title": "Today errand", "due_date": today.isoformat()},
                    ).json()
                    task_ids.append(due["id"])
                    page.reload(wait_until="networkidle")
                    expect(count).to_have_text("all open tasks: 2")
                    expect(schedule.locator('[data-record="' + due["id"] + '"]')).to_be_visible()
                    expect(
                        schedule.locator('[data-record="' + upcoming["id"] + '"]')
                    ).to_have_count(0)
                    capture("today-and-tomorrow")
                    assert api.patch(base + "/api/tasks/" + due["id"], data={"done": True}).ok
                    page.reload(wait_until="networkidle")
                    expect(count).to_have_text("all open tasks: 1")
                    expect(schedule.locator(".today-row")).to_have_count(0)
                    count.press("Enter")
                    first.locator(".task-check").press("Enter")
                    expect(first).to_have_count(0)
                    assert page.evaluate("window._navigateHome()")
                    expect(count).to_have_text("all open tasks: 0")
                    expect(schedule.locator(".today-row")).to_have_count(0)
                    capture("completed")

                    def missing_total(route):
                        response = route.fetch()
                        data = response.json()
                        del data["sections"]["today"]["tasks"]["open_count"]
                        route.fulfill(response=response, json=data)

                    page.route(base + "/api/today?**", missing_total)
                    page.reload(wait_until="networkidle")
                    expect(count).to_have_text("tasks")
                    page.unroute(base + "/api/today?**", missing_total)
                    count.press("Enter")
                    expect(page.locator("#tasks-view")).to_be_visible()
                    expect(page.locator('.tasks-tab[data-tab="active"]')).to_have_attribute(
                        "aria-pressed", "true"
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        checks="tomorrow-only all-open scope, dated schedule, exact task destination, clears history/search, today vs future, completion/reload count, absent total is not guessed, keyboard, console and overflow",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
                    for identity in task_ids:
                        assert context.request.delete(base + "/api/tasks/" + identity).ok
                    row.update(
                        page_errors=errors, console_errors=console, blocked_external=external
                    )
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
