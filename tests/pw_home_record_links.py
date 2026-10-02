"""Home opens the selected source record and preserves its edit/recovery workflow."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def run():
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    today = datetime.now(UTC).date().isoformat()
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    evidence = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for host, width, theme in (
            ("127.0.0.1", 1440, "dark"),
            ("127.0.0.1", 390, "light"),
            ("localhost", 1440, "light"),
            ("localhost", 390, "dark"),
        ):
            label = f"{host}-{width}-{theme}"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                timezone_id="UTC",
                reduced_motion="reduce",
                service_workers="block",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            task = context.request.post(
                base + "/api/tasks", data={"title": f"target task {label}", "due_date": today}
            )
            assert task.ok, task.text()
            task_id = task.json()["id"]
            cleanup = [("tasks", task_id)]
            home = f"http://{host}:{port}/?app=home"
            try:
                page.goto(home, wait_until="networkidle")
                if page.locator("#setup-wizard").is_visible():
                    page.locator("#setup-skip").click()
                page.locator("#today-settings").click()
                choose_settings_section(page, "themes")
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/api/appearance")
                        and response.request.method == "PUT"
                    )
                ) as appearance:
                    page.locator(f'[data-theme-mode="{theme}"]').click()
                assert appearance.value.ok
                page.locator("#settings-modal-close").click()
                row = page.locator("#today-sections button").filter(has_text=f"target task {label}")
                expect(row).to_be_visible()
                row.focus()
                row.press("Enter")
                expect(page.locator("#te-title")).to_have_value(f"target task {label}")
                expect(page.locator("#te-title")).to_be_focused()
                assert task_id in page.url
                if theme == "light":
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                else:
                    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
                page.screenshot(path=str(output / f"task-open-{label}.png"), full_page=True)
                page.locator("#te-title").fill(f"edited task {label}")
                page.locator("#te-save").click()
                expect(page.locator("#te-title")).to_have_count(0)
                saved = context.request.get(base + "/api/tasks").json()
                assert (
                    next(item for item in saved if item["id"] == task_id)["title"]
                    == f"edited task {label}"
                )
                page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(f"edited task {label}")
                saved_link = page.url
                page.go_back(wait_until="networkidle")
                expect(page.locator("#today-view")).to_be_visible()
                expect(page.locator("#te-title")).to_have_count(0)
                page.go_forward(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(f"edited task {label}")
                page.locator("#te-title").fill(f"unsaved task {label}")
                page.go_back(wait_until="networkidle")
                if host == "127.0.0.1":
                    page.get_by_role("alertdialog").get_by_role("button", name="cancel").click()
                    expect(page).to_have_url(saved_link)
                    expect(page.locator("#te-title")).to_have_value(f"unsaved task {label}")
                    expect(page.locator("#today-view")).not_to_be_visible()
                    page.go_back(wait_until="networkidle")
                    page.get_by_role("alertdialog").get_by_role("button", name="confirm").click()
                    expect(page.locator("#today-view")).to_be_visible()
                    expect(page.locator("#te-title")).to_have_count(0)
                    page.go_forward(wait_until="networkidle")
                else:
                    # A different host unloads the document; its per-tab draft must recover.
                    expect(page.locator("#today-view")).to_be_visible()
                    page.go_forward(wait_until="networkidle")
                    expect(page.locator("#te-title")).to_have_value(f"unsaved task {label}")
                    page.locator("#te-cancel").click()
                    page.get_by_role("alertdialog").get_by_role("button", name="confirm").click()
                    page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(f"edited task {label}")
                page.locator("#te-cancel").click()
                error_count = len(errors)
                page.route(
                    "**/api/tasks/tree", lambda route: route.fulfill(status=503, body="unavailable")
                )
                page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_count(0)
                retry = page.locator("#plan-view > .specialist-state .specialist-state-retry")
                expect(retry).to_be_visible()
                assert errors[error_count:] and all(
                    "503" in error for error in errors[error_count:]
                )
                del errors[error_count:]
                page.unroute("**/api/tasks/tree")
                retry.click()
                expect(page.locator("#te-title")).to_have_value(f"edited task {label}")
                page.locator("#te-cancel").click()
                page.locator(f'.task-item[data-id="{task_id}"] .task-check').click()
                expect(page.locator(f'.task-item[data-id="{task_id}"]')).to_have_count(0)
                page.goto(home, wait_until="networkidle")
                expect(
                    page.locator("#today-sections button").filter(has_text=f"edited task {label}")
                ).to_have_count(0)
                page.goto(saved_link, wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(f"edited task {label}")
                page.locator("#te-cancel").click()
                expect(page.locator('.tasks-tab[data-tab="done"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                assert context.request.delete(base + "/api/tasks/" + task_id).ok
                page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_count(0)
                expect(page.locator("#toast-container .toast.error").last).to_contain_text(
                    "could not open this item"
                )

                event = context.request.post(
                    base + "/api/calendar",
                    data={
                        "title": f"daily event {label}",
                        "start_dt": f"{yesterday}T09:00",
                        "end_dt": f"{yesterday}T10:00",
                        "recurrence": "daily",
                    },
                )
                assert event.ok, event.text()
                event_id = event.json()["id"]
                cleanup.append(("calendar", event_id))
                page.goto(home, wait_until="networkidle")
                page.locator("#today-sections button").filter(
                    has_text=f"daily event {label}"
                ).click()
                expect(page.locator("#cal-title")).to_have_value(f"daily event {label}")
                expect(page.locator("#cal-title")).to_be_focused()
                assert page.locator("#cal-start").evaluate("el => el.value") == f"{today}T09:00"
                page.screenshot(path=str(output / f"event-open-{label}.png"), full_page=True)
                page.locator("#cal-title").fill(f"changed occurrence {label}")
                page.locator("#cal-save").click()
                page.get_by_role("dialog", name="edit recurring event").get_by_role(
                    "button", name="This event", exact=True
                ).click()
                expect(page.locator("#cal-title")).to_have_count(0)
                events = context.request.get(base + "/api/calendar").json()
                child = next(
                    item for item in events if item["title"] == f"changed occurrence {label}"
                )
                cleanup.append(("calendar", child["id"]))
                assert child["start_dt"] == f"{today}T09:00"
                page.reload(wait_until="networkidle")
                expect(page.locator("#cal-title")).to_have_value(f"changed occurrence {label}")
                assert child["id"] in page.url
                assert (
                    next(item for item in events if item["id"] == event_id)["start_dt"]
                    == f"{yesterday}T09:00"
                )
                evidence.append(
                    {
                        "profile": label,
                        "record_type": "calendar",
                        "id": event_id,
                        "result": "today's occurrence opened and changed; series start preserved",
                    }
                )

                for view, endpoint, payload, selector in (
                    (
                        "reminders",
                        "reminders",
                        {"text": f"reminder {label}", "trigger_at": f"{today}T23:59:59"},
                        "#reminder-list .settings-list-row",
                    ),
                    ("habits", "habits", {"name": f"habit {label}"}, "#habits-body .habit-card"),
                    (
                        "subs",
                        "subscriptions",
                        {
                            "name": f"renewal {label}",
                            "next_due": tomorrow,
                            "price": 5,
                            "currency": "CAD",
                        },
                        "#subs-list .sub-item",
                    ),
                    (
                        "days",
                        "days",
                        {"name": f"countdown {label}", "date": tomorrow},
                        "#days-grid .day-card",
                    ),
                ):
                    created = context.request.post(base + f"/api/{endpoint}", data=payload)
                    assert created.ok, created.text()
                    item_id = created.json()["id"]
                    cleanup.append((endpoint, item_id))
                    page.goto(home, wait_until="networkidle")
                    page.locator(
                        f'#today-sections [data-view="{view}"][data-record="{item_id}"]'
                    ).click()
                    selected = page.locator(f'{selector}[data-id="{item_id}"]')
                    expect(selected).to_be_focused()
                    assert selected.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
                    page.screenshot(path=str(output / f"{view}-open-{label}.png"), full_page=True)
                    if view == "reminders":
                        selected.get_by_role("button", name="cancel", exact=True).click()
                        expect(selected).to_have_count(0)
                        assert not any(
                            item["id"] == item_id
                            for item in context.request.get(base + "/api/reminders").json()
                        )
                    elif view == "habits":
                        selected.locator(f'[data-toggle="{today}"]').click()
                        expect(selected.locator(f'[data-toggle="{today}"]')).to_have_class(
                            "habit-day done"
                        )
                        assert next(
                            item
                            for item in context.request.get(base + "/api/habits/overview").json()[
                                "habits"
                            ]
                            if item["id"] == item_id
                        )["done_today"]
                    else:
                        selected.locator('[data-act="edit"]').last.click()
                        selected.locator('[data-f="name"]').fill(f"updated {view} {label}")
                        selected.locator('[data-act="save"]').click()
                        expect(selected).not_to_have_class(re.compile(r"\bediting\b"))
                        page.reload(wait_until="networkidle")
                        expect(selected).to_be_focused()
                        expect(selected).to_contain_text(f"updated {view} {label}")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                    )
                    evidence.append(
                        {
                            "profile": label,
                            "record_type": view,
                            "id": item_id,
                            "result": "focused and acted on exact record; saved state checked",
                        }
                    )
                assert not errors, errors
                evidence.append(
                    {
                        "profile": label,
                        "task_id": task_id,
                        "task": "opened, edited, reloaded, completed, absent from home",
                    }
                )
            finally:
                page.screenshot(path=str(output / f"home-record-{label}.png"), full_page=True)
                (output / "scenarios.json").write_text(json.dumps(evidence, indent=2))
                for endpoint, item_id in reversed(cleanup):
                    context.request.delete(base + f"/api/{endpoint}/{item_id}")
                context.close()
        browser.close()


if __name__ == "__main__":
    run()
