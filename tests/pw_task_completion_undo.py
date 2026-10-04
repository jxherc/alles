"""Owned task completion undo, exact completion guards and recovery."""

import base64
import json
import os
import sys
import traceback
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
                    "scenario_id": "plan.task-completion-undo",
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
                    task = api.post(
                        base + "/api/tasks",
                        data={
                            "title": "Review the household plan — 中文 " + label,
                            "stage": "doing",
                            "repeat": "monthly",
                            "due_date": "2032-01-31",
                            "notes": "retain exact notes",
                        },
                    ).json()
                    other = api.post(
                        base + "/api/tasks", data={"title": "Second task", "stage": "waiting"}
                    ).json()
                    task_ids += [task["id"], other["id"]]
                    endpoint = base + "/api/tasks/" + task["id"]
                    page.goto(base + "/?view=tasks", wait_until="networkidle")
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
                    receipt = page.locator("#task-completion-receipt")
                    message = page.locator("#task-completion-message")
                    undo = page.locator("#task-completion-undo")
                    dismiss = page.locator("#task-completion-dismiss")
                    check = page.locator(f'.task-item[data-id="{task["id"]}"] .task-check')
                    other_check = page.locator(f'.task-item[data-id="{other["id"]}"] .task-check')

                    def saved(identity):
                        tasks = (
                            api.get(base + "/api/tasks").json()
                            + api.get(base + "/api/tasks/done").json()
                        )
                        return next(t for t in tasks if t["id"] == identity)

                    def reject(route):
                        route.fulfill(status=503, json={"detail": "synthetic unavailable"})

                    def lost(route):
                        assert route.fetch().ok
                        reject(route)

                    expect(receipt).to_be_hidden()
                    announcer = page.locator("#task-completion-announcer")
                    expect(announcer).to_have_attribute("role", "status")
                    assert announcer.evaluate(
                        "e=>!e.closest('[hidden]') && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden'"
                    )
                    check.press("Enter")
                    expect(check).to_have_count(0)
                    expect(message).to_have_text("completed: " + task["title"])
                    expect(undo).to_be_focused()
                    expect(announcer).to_have_text("completed: " + task["title"])
                    expect(undo).to_have_attribute("aria-describedby", "task-completion-message")
                    assert undo.evaluate(
                        "e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44}"
                    )
                    assert undo.evaluate("e=>getComputedStyle(e).outlineStyle !== 'none'")
                    first = saved(task["id"])
                    successor = next(
                        t for t in api.get(base + "/api/tasks").json() if t["id"] != other["id"]
                    )
                    task_ids.append(successor["id"])
                    assert successor["due_date"] == "2032-02-29"
                    capture("completed")
                    page.route(endpoint, reject)
                    undo.press("Enter")
                    expect(message).to_have_text(
                        "could not confirm undo for " + task["title"] + ". try again."
                    )
                    expect(undo).to_be_enabled()
                    expect(undo).to_be_focused()
                    assert saved(task["id"])["done"]
                    capture("rejected")
                    page.unroute(endpoint, reject)
                    page.route(endpoint, lost)
                    undo.press("Enter")
                    expect(undo).to_have_attribute("aria-busy", "false")
                    assert saved(task["id"])["stage"] == "doing"
                    page.unroute(endpoint, lost)
                    undo.press("Enter")
                    expect(undo).to_be_hidden()
                    expect(message).to_contain_text("changed. check the task list or history")
                    expect(check).to_be_focused()
                    assert saved(task["id"])["stage"] == "doing"
                    assert len(api.get(base + "/api/tasks").json()) == 3

                    check.press("Enter")
                    expect(undo).to_be_visible()
                    expect(check).to_have_count(0)
                    assert saved(task["id"])["completed_at"] != first["completed_at"]
                    assert api.patch(endpoint, data={"stage": "waiting"}).ok
                    newer = api.patch(endpoint, data={"done": True}).json()
                    undo.press("Enter")
                    expect(undo).to_be_hidden()
                    expect(dismiss).to_be_focused()
                    assert saved(task["id"])["completed_at"] == newer["completed_at"]
                    assert saved(task["id"])["done"]
                    capture("changed-completion")

                    # History reopening remains available after a conflicting receipt.
                    page.locator('.tasks-tab[data-tab="done"]').click()
                    check.press("Enter")
                    expect(check).to_have_count(0)
                    page.locator('.tasks-tab[data-tab="active"]').click()
                    expect(check).to_be_visible()
                    assert api.patch(endpoint, data={"stage": "doing"}).ok
                    page.reload(wait_until="networkidle")
                    check.press("Enter")
                    expect(check).to_have_count(0)
                    assert api.patch(endpoint, data={"notes": "newer notes"}).ok
                    assert api.patch(
                        base + "/api/tasks/" + successor["id"], data={"title": "Edited future"}
                    ).ok
                    undo.press("Enter")
                    expect(check).to_be_focused()
                    expect(message).to_have_text("reopened: " + task["title"])
                    assert saved(task["id"])["stage"] == "doing"
                    assert saved(task["id"])["notes"] == "newer notes"
                    assert saved(successor["id"])["title"] == "Edited future"
                    assert len(api.get(base + "/api/tasks").json()) == 3
                    capture("undone")
                    dismiss.press("Enter")
                    expect(receipt).to_be_hidden()
                    expect(page.locator("#tasks-search")).to_be_focused()
                    page.reload(wait_until="networkidle")
                    expect(check).to_be_visible()
                    assert saved(task["id"])["stage"] == "doing"

                    # A saved completion still offers undo when its list refresh fails.
                    page.route(base + "/api/tasks/tree", reject)
                    check.press("Enter")
                    expect(message).to_have_text("completed: " + task["title"])
                    expect(page.locator(".toast.error").last).to_have_text(
                        "could not refresh tasks. reload to see the latest status."
                    )
                    expect(undo).to_be_enabled()
                    page.unroute(base + "/api/tasks/tree", reject)
                    undo.press("Enter")
                    expect(message).to_have_text("reopened: " + task["title"])
                    expect(check).to_be_focused()

                    # An old pending undo must not clear or steal a newer receipt.
                    check.press("Enter")
                    expect(check).to_have_count(0)
                    held = []
                    page.route(endpoint, lambda route: held.append(route))
                    undo.press("Enter")
                    expect(undo).to_be_disabled()
                    assert len(held) == 1
                    other_check.press("Enter")
                    expect(message).to_have_text("completed: Second task")
                    expect(undo).to_be_enabled()
                    held.pop().continue_()
                    expect(check).to_be_visible()
                    expect(message).to_have_text("completed: Second task")
                    expect(undo).to_be_focused()
                    page.unroute(endpoint)
                    undo.press("Enter")
                    expect(other_check).to_be_visible()
                    assert saved(other["id"])["stage"] == "waiting"
                    expect(message).to_have_text("reopened: Second task")

                    # A newer rejected completion does not discard an older success.
                    page.route(endpoint, lambda route: held.append(route))
                    page.route(base + "/api/tasks/" + other["id"], reject)
                    check.press("Enter")
                    expect(check).to_be_disabled()
                    other_check.press("Enter")
                    expect(other_check).to_be_enabled()
                    expect(page.locator(".toast.error").last).to_have_text(
                        "could not confirm task completion. try again."
                    )
                    held.pop().continue_()
                    expect(check).to_have_count(0)
                    expect(message).to_have_text("completed: " + task["title"])
                    expect(undo).to_be_enabled()
                    page.unroute(endpoint)
                    page.unroute(base + "/api/tasks/" + other["id"], reject)
                    undo.press("Enter")
                    expect(check).to_be_visible()
                    expect(message).to_have_text("reopened: " + task["title"])

                    # A newer acknowledged completion retains its receipt after a late older reply.
                    page.route(endpoint, lambda route: held.append(route))
                    check.press("Enter")
                    expect(check).to_be_disabled()
                    other_check.press("Enter")
                    expect(message).to_have_text("completed: Second task")
                    held.pop().continue_()
                    page.wait_for_load_state("networkidle")
                    expect(check).to_have_count(0)
                    expect(message).to_have_text("completed: Second task")
                    expect(undo).to_be_focused()
                    page.unroute(endpoint)
                    undo.press("Enter")
                    expect(other_check).to_be_visible()
                    assert api.patch(endpoint, data={"stage": "doing"}).ok
                    page.reload(wait_until="networkidle")
                    expect(check).to_be_visible()

                    # Leaving Tasks while completion is pending never moves Home's focus.
                    page.route(endpoint, lambda route: held.append(route))
                    check.press("Enter")
                    expect(check).to_be_disabled()
                    assert len(held) == 1
                    assert page.evaluate("window._navigateHome()")
                    expect(page.locator("#today-view")).to_be_visible()
                    home = page.locator(".today-summary-tasks")
                    home.focus()
                    held.pop().continue_()
                    expect(message).to_have_text("completed: " + task["title"])
                    page.wait_for_load_state("networkidle")
                    expect(home).to_be_focused()
                    expect(receipt).to_be_hidden()
                    page.unroute(endpoint)
                    home.press("Enter")
                    expect(receipt).to_be_visible()
                    undo.press("Enter")
                    expect(check).to_be_visible()
                    assert saved(task["id"])["stage"] == "doing"
                    assert len(api.get(base + "/api/tasks").json()) == 3
                    assert not api.get(base + "/api/tasks/done").json()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert not external and not errors, (external, errors)
                    assert len(console) == 6 and all(
                        "Failed to load resource" in c and ("503" in c or "409" in c)
                        for c in console
                    ), console
                    row.update(
                        status="passed",
                        checks="completion/undo/reload, original stage, exactly one recurring successor, preserved edits, rejected/lost undo retry, newer completion conflict, list refresh failure, newer receipt, pending navigation, keyboard/focus, reduced motion, native zoom, console and overflow",
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
