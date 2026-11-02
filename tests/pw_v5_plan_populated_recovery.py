"""Populated Plan real-use gate for named controls, keyboard editing, and mutation recovery."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Route, sync_playwright

PORT = os.environ.get("PORT", "8147")
DATA = Path(os.environ["ALLES_DATA"]).resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
BASE = f"http://127.0.0.1:{PORT}"
PLAN = f"http://plan.localhost:{PORT}/?view=tasks"
_EN = json.loads(
    (Path(__file__).resolve().parents[1] / "static/locales/en.json").read_text("utf-8")
)
# the error toast a failed completion shows, read from the catalog so a reworded message can't
# leave the gate waiting for text that no longer exists
COMPLETION_FAILED = _EN.get("messages", _EN)["tasks.completion_failed"]


def _require_owned_data() -> None:
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the populated Plan gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if DATA == temp_root or temp_root not in DATA.parents:
        raise RuntimeError("ALLES_DATA must be an owned child of the system temp directory")
    if len(RUN_ID) < 16 or (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this run")
    require_server_ownership(BASE, RUN_ID)


def run() -> None:
    _require_owned_data()
    task_title = f"KOKUEN populated recovery {time.time_ns()}"
    renamed_title = f"{task_title} verified"
    unexpected_errors: list[str] = []
    expected_failures: list[str] = []
    failed_patch_count = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.set_default_timeout(10_000)
        page.on("pageerror", lambda error: unexpected_errors.append(str(error)))

        def on_console(message) -> None:
            if message.type != "error":
                return
            if "503" in message.text:
                expected_failures.append(message.text)
            else:
                unexpected_errors.append(message.text)

        page.on("console", on_console)
        assert page.request.post(f"{BASE}/api/setup/dismiss").ok
        page.goto(PLAN, wait_until="domcontentloaded")
        page.locator("#task-add-input").wait_for(state="visible")

        # Create through the real quick-add UI and keep the generated row as the
        # authority for every subsequent pointer and keyboard action.
        page.locator("#task-add-input").fill(task_title)
        page.locator("#task-add-input").press("Enter")
        edit = page.get_by_role("button", name=f"edit {task_title}", exact=True)
        edit.wait_for(state="visible")
        row = edit.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' task-item ')][1]"
        )
        task_id = row.get_attribute("data-id")
        assert task_id

        # the row's more menu is closed: its items are hidden until it opens
        controls = row.locator("button:visible")
        for index in range(controls.count()):
            control = controls.nth(index)
            assert control.get_attribute("data-kokuen-primitive"), index
            assert control.get_attribute("aria-label") or control.inner_text().strip(), index
            box = control.bounding_box()
            assert box and box["width"] >= 43.5 and box["height"] >= 43.5, (index, box)

        # Native Enter activation opens the labelled modal. Escape closes it and
        # returns focus to the same task edit control.
        edit.press("Enter")
        dialog = page.get_by_role("dialog", name="edit task")
        dialog.wait_for(state="visible")
        assert page.locator("#te-title").evaluate("node => document.activeElement === node")
        page.locator("#te-title").press("Escape")
        dialog.wait_for(state="detached")
        assert edit.evaluate("node => document.activeElement === node")

        # Fail the first completion PATCH and double-click the real pointer
        # coordinates. Busy/disabled state must collapse both clicks to one
        # request, recover to an enabled error state, and preserve the task.
        def fail_first_patch(route: Route) -> None:
            nonlocal failed_patch_count
            if route.request.method == "PATCH" and route.request.url.endswith(
                f"/api/tasks/{task_id}"
            ):
                failed_patch_count += 1
                route.fulfill(
                    status=503, content_type="application/json", body='{"detail":"forced"}'
                )
                return
            route.continue_()

        page.route("**/api/tasks/*", fail_first_patch)
        complete = page.get_by_role("button", name=f"mark {task_title} complete", exact=True)
        box = complete.bounding_box()
        assert box
        page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.locator("#toast-container .toast.error").filter(has_text=COMPLETION_FAILED).wait_for(
            state="visible"
        )
        assert failed_patch_count == 1
        assert complete.is_enabled()
        assert complete.get_attribute("data-kokuen-state") == "error"
        assert complete.get_attribute("aria-busy") is None
        assert edit.is_visible()
        page.unroute("**/api/tasks/*", fail_first_patch)

        # Retry by keyboard against the real backend. Completion moves the row
        # out of the active tree, so follow it through the visible History view.
        complete.press("Enter")
        edit.wait_for(state="detached")
        page.click("#tasks-view-pick")
        page.locator(".custom-dropdown-panel [role=option]").nth(
            ["active", "today", "upcoming", "someday", "done"].index("done")
        ).click()
        page.get_by_role("button", name=f"mark {task_title} incomplete", exact=True).wait_for(
            state="visible"
        )
        edit = page.get_by_role("button", name=f"edit {task_title}", exact=True)
        edit.click()
        page.locator("#te-title").fill(renamed_title)
        page.get_by_role("button", name="save", exact=True).click()
        renamed_edit = page.get_by_role("button", name=f"edit {renamed_title}", exact=True)
        renamed_edit.wait_for(state="visible")
        assert renamed_edit.evaluate("node => document.activeElement === node")

        # delete lives in the row's named more menu (u.10): no "are you sure", the row says
        # "deleted" with undo where the change happened, and the server deletes once undo lapses
        more = page.get_by_role("button", name=f"more for {renamed_title}", exact=True)
        more.press("Enter")
        menu = page.locator(f"#{more.get_attribute('aria-controls')}")
        menu.wait_for(state="visible")
        delete = menu.get_by_role("menuitem", name="delete", exact=True)
        delete.focus()
        delete.press("Enter")
        renamed_edit.wait_for(state="detached")
        gone = page.locator(".task-undo-del")
        gone.wait_for(state="visible")
        assert gone.evaluate("node => document.activeElement === node")
        assert page.get_by_text(f"deleted “{renamed_title}”", exact=True).is_visible()
        deleted_at = time.monotonic()
        while page.evaluate(
            """async id => [...await fetch('/api/tasks').then(r => r.json()),
                ...await fetch('/api/tasks/done').then(r => r.json())].some(t => t.id === id)""",
            task_id,
        ):
            assert time.monotonic() - deleted_at < 15, "the task was never deleted"
            page.wait_for_timeout(500)
        # undo had its few seconds before the server was asked
        assert time.monotonic() - deleted_at > 4, time.monotonic() - deleted_at
        assert not page.get_by_text(renamed_title, exact=True).count()

        context.close()
        browser.close()

    assert not unexpected_errors, unexpected_errors
    assert expected_failures, "forced 503 did not reach the browser"
    print(
        "populated Plan real-use recovery gate passed: create, pointer repeat rejection, error, keyboard retry, edit, focus return, delete with undo"
    )


if __name__ == "__main__":
    run()
