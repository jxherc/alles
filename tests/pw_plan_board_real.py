"""Rendered Plan-board gate against the real shell and isolated API fixtures."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, sync_playwright

PORT = os.environ.get("PORT", "8964")
BASE = f"http://127.0.0.1:{PORT}"
EVIDENCE = Path(tempfile.gettempdir()) / "alles-plan-board-real"


def _task(task_id: str, title: str, stage: str, order: int, **extra) -> dict:
    return {
        "id": task_id,
        "title": title,
        "done": False,
        "stage": stage,
        "priority": 0,
        "due_date": None,
        "tags": [],
        "repeat": "",
        "notes": "",
        "project": "afterlife",
        "sort_order": order,
        "created_at": "2026-07-22T08:00:00",
        **extra,
    }


def _json_body(route: Route) -> dict:
    return json.loads(route.request.post_data or "{}")


def _route_tasks(route: Route, state: dict, calls: list[str]) -> None:
    request = route.request
    path = urlparse(request.url).path
    if request.method == "GET" and path == "/api/tasks":
        route.fulfill(json=state["active"])
        return
    if request.method == "GET" and path == "/api/tasks/done":
        route.fulfill(json=state["done"])
        return
    if request.method == "POST" and path == "/api/tasks":
        body = _json_body(route)
        task = _task(
            f"added-{len(state['active'])}",
            body["title"],
            body.get("stage", "backlog"),
            len(state["active"]),
        )
        state["active"].append(task)
        calls.append("create")
        route.fulfill(json=task)
        return
    if request.method == "POST" and path == "/api/tasks/reorder":
        items = _json_body(route)["items"]
        by_id = {task["id"]: task for task in state["active"]}
        for item in items:
            by_id[item["id"]].update(stage=item["stage"], sort_order=item["sort_order"])
        calls.append("reorder")
        route.fulfill(json={"items": [by_id[item["id"]] for item in items]})
        return
    if request.method == "PATCH" and path.startswith("/api/tasks/"):
        task_id = path.rsplit("/", 1)[-1]
        task = next(
            (item for item in state["active"] + state["done"] if item["id"] == task_id),
            None,
        )
        if not task:
            route.fulfill(status=404, json={"detail": "task not found"})
            return
        body = _json_body(route)
        stage = body.get("stage", task["stage"])
        task.update(body)
        task["stage"] = stage
        task["done"] = stage == "done"
        if task["done"] and task in state["active"]:
            state["active"].remove(task)
            state["done"].insert(0, task)
        elif not task["done"] and task in state["done"]:
            state["done"].remove(task)
            state["active"].append(task)
        calls.append(f"patch:{stage}")
        route.fulfill(json=task)
        return
    route.continue_()


def _no_overflow(page: Page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _open_board(page: Page) -> None:
    response = page.request.post(f"{BASE}/api/setup/dismiss")
    assert response.ok
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("typeof window._navigateTo === 'function'")
    page.evaluate("window._navigateTo('plan-board')")
    page.locator("#plan-view").wait_for(state="visible")
    page.locator(".plan-board-root").wait_for(state="visible")


def run() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    calls: list[str] = []
    state = {
        "active": [
            _task("inbox", "review the source list", "backlog", 0),
            _task("next", "write the delivery copy", "next", 0),
            _task(
                "doing",
                "test the real Plan board",
                "doing",
                0,
                priority=2,
                due_date="2026-07-22",
                notes="Check the phone reflow and keyboard path.",
            ),
            _task("blocked", "owner visual check", "waiting", 0),
        ],
        "done": [{**_task("done", "approved the board starter", "done", 0), "done": True}],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1366, "height": 850},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"page: {error}"))
        page.on(
            "console",
            lambda message: (
                errors.append(f"console: {message.text}") if message.type == "error" else None
            ),
        )
        page.route("**/api/tasks**", lambda route: _route_tasks(route, state, calls))
        _open_board(page)

        assert page.locator(".plan-board-column").count() == 4
        assert page.locator(".plan-board-card").count() == 4
        assert (
            page.locator(
                'select:visible, input[type="checkbox"]:visible, input[type="radio"]:visible'
            ).count()
            == 0
        )
        assert _no_overflow(page)

        page.locator(".plan-board-add input").fill("publish the first digest")
        page.locator(".plan-board-add").evaluate("form => form.requestSubmit()")
        page.locator(".plan-board-card", has_text="publish the first digest").wait_for()
        assert calls.count("create") == 1

        page.drag_and_drop(
            '.plan-board-card[data-task-id="inbox"] .plan-board-drag',
            '.plan-board-list[data-stage="doing"]',
        )
        page.wait_for_function("() => window.location && true")
        page.locator(
            '.plan-board-list[data-stage="doing"] .plan-board-card[data-task-id="inbox"]'
        ).wait_for()
        assert "reorder" in calls

        page.locator('.plan-board-card[data-task-id="doing"] .plan-board-card-main').click()
        assert page.locator(".plan-board-detail h2").inner_text() == "test the real Plan board"
        page.get_by_role("button", name="mark complete").click()
        page.locator('.plan-board-card[data-task-id="doing"]').wait_for(state="detached")
        page.get_by_role("button", name="completed", exact=False).click()
        assert page.locator(
            ".plan-board-completed", has_text="test the real Plan board"
        ).is_visible()

        project = page.locator(".plan-board-filter-wrap > .plan-board-tool")
        project.focus()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        assert project.inner_text() == "project: afterlife"

        page.screenshot(path=str(EVIDENCE / "plan-board-dark-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('.plan-board-stage-choice[data-value="doing"]').focus()
        page.keyboard.press("ArrowRight")
        waiting = page.locator('.plan-board-stage-choice[data-value="waiting"]')
        assert waiting.get_attribute("aria-checked") == "true"
        assert page.locator('.plan-board-column[data-stage="waiting"]').is_visible()
        assert _no_overflow(page)
        undersized = page.locator(
            "#plan-view button:visible, #plan-view input:visible"
        ).evaluate_all(
            """elements => elements.map(element => {
              const box = element.getBoundingClientRect();
              return {label: element.textContent.trim() || element.placeholder, width: box.width, height: box.height};
            }).filter(item => item.width < 43.5 || item.height < 43.5)"""
        )
        assert not undersized, undersized
        page.screenshot(path=str(EVIDENCE / "plan-board-dark-phone.png"), full_page=True)

        page.set_viewport_size({"width": 640, "height": 800})
        assert _no_overflow(page)
        assert not errors, errors
        browser.close()

    print("PASS  plan board real data and create")
    print("PASS  plan board atomic drag reorder")
    print("PASS  plan board details and completed history")
    print("PASS  plan board custom keyboard controls")
    print("PASS  plan board desktop, phone, and 200 percent reflow")
    print("PASS  plan board zero console errors")


if __name__ == "__main__":
    run()
