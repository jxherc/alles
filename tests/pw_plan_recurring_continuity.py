"""Owned monthly task completion, lost acknowledgement and correction workflow."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
records = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in [1440, 390]:
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            service_workers="block",
            reduced_motion="reduce",
        )
        api = context.request
        assert api.post(base + "/api/setup/dismiss").ok
        page = context.new_page()
        page.set_default_timeout(7000)
        errors = []
        console = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda item: console.append(item.text) if item.type == "error" else None)
        result = {
            "scenario_id": "plan.recurring-task-continuity",
            "profile": str(width),
            "status": "failed",
            "steps": [],
        }
        records.append(result)
        try:
            title = "owned monthly continuity " + str(width)
            page.goto(base + "/?view=plan", wait_until="networkidle")
            field = page.locator('.specialist-group-capture input[name="title"]')
            field.fill(title)
            field.press("Enter")
            expect(field).to_have_value("")
            page.get_by_role("tab", name="tasks", exact=True).click()
            page.locator("#tasks-search").fill(title)
            page.get_by_role("button", name="edit " + title, exact=True).click()
            page.locator("#te-due").fill("2032-01-31")
            page.locator("#te-rep").click()
            page.get_by_role("option", name="monthly", exact=True).click()
            page.locator("#te-save").click()
            expect(page.locator("#te-title")).to_have_count(0)

            def rows(done=False):
                response = api.get(base + ("/api/tasks/done" if done else "/api/tasks"))
                assert response.ok
                return [row for row in response.json() if row["title"] == title]

            original = rows()[0]
            assert original["repeat"] == "monthly" and original["due_date"] == "2032-01-31"
            endpoint = base + "/api/tasks/" + original["id"]

            def lose(route):
                if route.request.method == "PATCH":
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(status=503, json={"detail": "owned lost completion reply"})
                else:
                    route.continue_()

            page.route(endpoint, lose)
            button = page.get_by_role("button", name="mark " + title + " complete", exact=True)
            button.click()
            expect(page.locator(".toast.error").last).to_be_visible()
            assert (
                len(rows()) == 1 and rows()[0]["due_date"] == "2032-02-29" and len(rows(True)) == 1
            )
            page.unroute(endpoint, lose)
            with page.expect_response(
                lambda r: r.url == endpoint and r.request.method == "PATCH"
            ) as retry:
                button.click()
            assert retry.value.status == 409, retry.value.text()
            assert retry.value.json()["detail"]["code"] == "task_conflict"
            expect(page.locator(f'.task-item[data-id="{original["id"]}"]')).to_have_count(0)
            assert len(rows()) == 1 and len(rows(True)) == 1
            successor = rows()[0]
            expect(page.locator(f'.task-item[data-id="{successor["id"]}"]')).to_be_visible()
            result["steps"].append(
                "capture/edit/monthly/leap-day completion/lost response/same-action retry creates one successor"
            )
            page.locator('.tasks-tab[data-tab="done"]').click()
            page.get_by_role("button", name="mark " + title + " incomplete", exact=True).click()
            page.locator('.tasks-tab[data-tab="active"]').click()
            original_row = page.locator(f'.task-item[data-id="{original["id"]}"]')
            expect(original_row).to_be_visible()
            original_row.locator(".task-check").click()
            expect(original_row).to_have_count(0)
            assert len(rows()) == 1, (
                "undoing and repeating completion duplicated the existing next occurrence: "
                + json.dumps([{"id": r["id"], "due_date": r["due_date"]} for r in rows()])
            )
            result["steps"].append(
                "correct mistaken completion and redo without duplicating next occurrence"
            )
            page.reload(wait_until="networkidle")
            page.get_by_role("tab", name="tasks", exact=True).click()
            page.locator("#tasks-search").fill(title)
            page.get_by_role("button", name="mark " + title + " complete", exact=True).click()
            expect(page.locator(f'.task-item[data-id="{successor["id"]}"]')).to_have_count(0)
            assert len(rows()) == 1 and rows()[0]["due_date"] == "2032-03-31"
            result["steps"].append("reload/complete February/preserve January anchor at March31")
            assert not errors and all("503" in item or "409" in item for item in console), (
                errors,
                console,
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            result["status"] = "passed"
        except Exception as error:
            result.update(error=str(error), page_errors=errors, console=console)
        finally:
            page.screenshot(path=str(out / f"{width}-recurring-continuity.png"), full_page=True)
            context.close()
            (out / "scenarios.json").write_text(json.dumps(records, indent=2))
    browser.close()
raise SystemExit(any(r["status"] != "passed" for r in records))
