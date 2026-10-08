"""Plan capture, searched queues, completion recovery and reopened history."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [1440, 390]:
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            service_workers="block",
            reduced_motion="reduce",
            is_mobile=width == 390,
            has_touch=width == 390,
        )
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        console_errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        try:
            context.request.post(base + "/api/setup/dismiss")
            page.goto(base + "/?view=plan", wait_until="networkidle")
            title = "capture continuity " + str(width)
            capture = page.locator('.specialist-group-capture input[name="title"]')
            capture.fill(title)
            capture.press("Enter")
            expect(capture).to_have_value("")
            page.get_by_role("tab", name="tasks", exact=True).click()
            page.locator("#tasks-search").fill(title)
            today = date.today()
            for suffix, day in [
                ("overdue", str(today - timedelta(days=1))),
                ("today", str(today)),
                ("future", str(today + timedelta(days=1))),
                ("someday", None),
            ]:
                response = context.request.post(
                    base + "/api/tasks", data={"title": title + " " + suffix, "due_date": day}
                )
                assert response.ok, response.text()
            for view, expected in [
                ("today", {"overdue", "today"}),
                ("upcoming", {"future"}),
                ("someday", {"", "someday"}),
            ]:
                page.locator(f'.tasks-tab[data-tab="{view}"]').click()
                for suffix in ["", "overdue", "today", "future", "someday"]:
                    editor = page.get_by_role(
                        "button",
                        name="edit " + title + (" " + suffix if suffix else ""),
                        exact=True,
                    )
                    expect(editor).to_have_count(1 if suffix in expected else 0)
            page.locator('.tasks-tab[data-tab="active"]').click()
            page.get_by_role("button", name="edit " + title, exact=True).click()
            page.locator("#te-due").fill("2032-11-07")
            page.locator("#te-notes").fill("retained source and correction")
            page.locator("#te-save").click()
            expect(page.locator("#te-title")).to_have_count(0)
            record = next(
                x for x in context.request.get(base + "/api/tasks").json() if x["title"] == title
            )
            endpoint = base + "/api/tasks/" + record["id"]
            page.route(
                endpoint,
                lambda route: (
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic rejected completion"}',
                    )
                    if route.request.method == "PATCH"
                    else route.continue_()
                ),
            )
            button = page.get_by_role("button", name="mark " + title + " complete", exact=True)
            button.click()
            expect(page.locator(".toast.error").last).to_be_visible()
            expect(button).to_be_visible()
            assert not next(
                x
                for x in context.request.get(base + "/api/tasks").json()
                if x["id"] == record["id"]
            )["done"]
            assert len(console_errors) == 1 and "503" in console_errors[0], console_errors
            console_errors.clear()
            page.unroute(endpoint)
            button.click()
            expect(button).to_have_count(0)
            page.locator('.tasks-tab[data-tab="done"]').click()
            undo = page.get_by_role("button", name="mark " + title + " incomplete", exact=True)
            expect(undo).to_be_visible()
            page.reload(wait_until="networkidle")
            page.locator('.tasks-tab[data-tab="done"]').click()
            page.locator("#tasks-search").fill(title)
            page.get_by_role("button", name="edit " + title, exact=True).click()
            expect(page.locator("#te-due")).to_have_value("2032-11-07")
            expect(page.locator("#te-notes")).to_have_value("retained source and correction")
            page.locator("#te-cancel").click()
            undo.click()
            page.locator('.tasks-tab[data-tab="active"]').click()
            expect(button).to_be_visible()
            saved = next(
                x
                for x in context.request.get(base + "/api/tasks").json()
                if x["id"] == record["id"]
            )
            assert not saved["done"] and saved["due_date"] == "2032-11-07"
            assert not errors and not console_errors, (errors, console_errors)
            results.append(
                {
                    "scenario_id": "plan.search-history-continuity",
                    "feature_id": "plan.tasks-calendar",
                    "profile": "desktop" if width == 1440 else "phone",
                    "width": width,
                    "status": "passed",
                    "workflow": "capture/search due queues/edit/reschedule/rejected completion/retry/search history/reload/reopen",
                }
            )
        except Exception as e:
            results.append({"width": width, "status": "failed", "error": repr(e)})
            raise
        finally:
            page.screenshot(path=str(out / f"{width}-continuity.png"), full_page=True)
            (out / "scenarios.json").write_text(json.dumps(results, indent=2))
            context.close()
    browser.close()
