"""Habit failures retain real records and drafts; retry preserves the requested day state."""

import json
import os
import re
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    cases = [
        "archive",
        "delete",
        "toggle",
        "toggle-lost",
        "load-first",
        "load-draft",
        "save",
        "create",
        "create-during-load",
        "toolbar-focus",
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in cases:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="America/Toronto",
                    service_workers="block",
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(7000)
                errors, console = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                item = context.request.post(
                    base + "/api/habits", data={"name": f"habit {case} {width}"}
                ).json()
                endpoint = base + "/api/habits/" + item["id"]
                overview = base + "/api/habits/overview"
                overview_route = re.compile(re.escape(overview) + r"\?date_q=\d{4}-\d{2}-\d{2}$")
                result = {
                    "scenario_id": "habits.recovery." + case,
                    "feature_id": "health.logs-and-habits",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                results.append(result)

                def reject(route):
                    if case == "toggle-lost":
                        response = route.fetch()
                        assert response.ok, response.text()
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def stored():
                    rows = context.request.get(overview).json()["habits"]
                    return next((row for row in rows if row["id"] == item["id"]), None)

                try:
                    context.request.post(base + "/api/setup/dismiss")
                    held = []
                    if case == "load-first":
                        page.route(overview_route, reject)
                    if case == "create-during-load":
                        page.route(overview_route, lambda route: held.append(route))
                    page.goto(
                        base + "/?view=habits",
                        wait_until="domcontentloaded"
                        if case == "create-during-load"
                        else "networkidle",
                    )
                    card = page.locator(f'.habit-card[data-id="{item["id"]}"]')
                    if case == "create-during-load":
                        expect(page.locator('#habits-body [role="status"]')).to_contain_text(
                            "loading"
                        )
                        page.locator("#habits-add-toggle").click()
                        draft = page.locator('.habit-add [data-f="name"]')
                        draft.fill("retained slow-load draft")
                        page.route(base + "/api/habits", reject)
                        page.locator('.habit-add [data-act="create"]').click()
                        expect(page.locator(".toast.error").last).to_be_visible()
                        assert held, "initial overview was not held"
                        page.unroute(overview_route)
                        for route in held:
                            route.fulfill(response=route.fetch())
                        expect(page.locator(".habit-load-error")).to_be_visible()
                        expect(page.locator('#habits-body [role="status"]')).to_have_count(0)
                        expect(draft).to_have_value("retained slow-load draft")
                        page.screenshot(
                            path=str(output / f"{case}-{width}-error.png"), full_page=True
                        )
                        retry = page.locator('[data-act="retry-load"]')
                        retry.focus()
                        page.keyboard.press("Enter")
                        expect(card).to_be_visible()
                        expect(page.locator(".habit-load-error")).to_have_count(0)
                        expect(draft).to_have_value("retained slow-load draft")
                        page.unroute(base + "/api/habits")
                        page.locator('.habit-add [data-act="create"]').click()
                        expect(page.locator(".habit-add")).to_have_count(0)
                        assert (
                            sum(
                                row["name"] == "retained slow-load draft"
                                for row in context.request.get(overview).json()["habits"]
                            )
                            == 1
                        )
                    elif case == "toolbar-focus":
                        for selector in ['[data-act="archive-view"]', "#habits-add-toggle"]:
                            held.clear()
                            page.route(overview_route, lambda route: held.append(route))
                            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                            expect(page.locator('#habits-body [role="status"]')).to_contain_text(
                                "loading"
                            )
                            control = page.locator(selector)
                            control.focus()
                            expect(control).to_be_focused()
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert held, "overview refresh was not held"
                            for route in list(held):
                                route.fulfill(response=route.fetch())
                            page.unroute(overview_route)
                            expect(page.locator('#habits-body [role="status"]')).to_have_count(0)
                            expect(control).to_be_focused()
                        page.keyboard.press("Enter")
                        draft = page.locator('.habit-add [data-f="name"]')
                        expect(draft).to_be_focused()
                        draft.fill("keyboard draft after refresh")
                        expect(draft).to_have_value("keyboard draft after refresh")
                    elif case.startswith("load"):
                        if case == "load-draft":
                            card.locator('[data-act="edit"]').click()
                            card.locator('[data-f="name"]').fill("retained draft")
                            page.route(overview_route, reject)
                            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                        expect(page.locator(".habit-load-error")).to_contain_text("could not load")
                        expect(page.locator(".habits-empty")).to_have_count(0)
                        if case == "load-draft":
                            expect(card.locator('[data-f="name"]')).to_have_value("retained draft")
                        if case == "load-draft":
                            expect(card.locator('[data-f="name"]')).to_be_focused()
                        retry = page.locator('[data-act="retry-load"]')
                        retry.scroll_into_view_if_needed()
                        box = retry.bounding_box()
                        assert box["width"] >= 44 and box["height"] >= 44, box
                        page.screenshot(
                            path=str(output / f"{case}-{width}-error.png"), full_page=True
                        )
                        page.unroute(overview_route)
                        retry.focus()
                        page.keyboard.press("Enter")
                        expect(page.locator(".habit-load-error")).to_have_count(0)
                        expect(card).to_be_visible()
                        if case == "load-draft":
                            expect(card.locator('[data-f="name"]')).to_have_value("retained draft")
                            card.locator('[data-act="save"]').click()
                            expect(card.locator(".habit-name")).to_have_text("retained draft")
                    else:
                        if case in {"archive", "save"}:
                            card.locator('[data-act="edit"]').click()
                            if case == "save":
                                card.locator('[data-f="name"]').fill("retained edit")
                        if case == "create":
                            page.locator("#habits-add-toggle").click()
                            card = page.locator(".habit-add")
                            card.locator('[data-f="name"]').fill("retained new habit")
                            pattern = base + "/api/habits"
                            action = card.locator('[data-act="create"]')
                        elif case.startswith("toggle"):
                            pattern = endpoint + "/toggle"
                            action = card.locator(".habit-day").last
                            day = action.get_attribute("data-toggle")
                        else:
                            pattern = endpoint
                            action = card.locator(
                                '[data-act="del"]' if case == "delete" else f'[data-act="{case}"]'
                            )
                        page.route(pattern, reject)

                        def click_action():
                            action.click()
                            if case == "delete":
                                page.locator(".dialog-overlay [data-dialog-confirm]").click()

                        click_action()
                        expect(page.locator(".toast.error").last).to_be_visible()
                        expect(action).to_be_enabled()
                        if case == "save":
                            expect(card.locator('[data-f="name"]')).to_have_value("retained edit")
                            assert stored()["name"] == item["name"]
                        elif case == "create":
                            expect(card.locator('[data-f="name"]')).to_have_value(
                                "retained new habit"
                            )
                            assert not any(
                                row["name"] == "retained new habit"
                                for row in context.request.get(overview).json()["habits"]
                            )
                        elif case.startswith("toggle"):
                            expect(action).not_to_have_class("habit-day done")
                            assert next(row for row in stored()["grid"] if row["date"] == day)[
                                "done"
                            ] == (case == "toggle-lost")
                        else:
                            assert stored() is not None
                        page.screenshot(
                            path=str(output / f"{case}-{width}-error.png"), full_page=True
                        )
                        page.unroute(pattern)
                        click_action()
                        if case in {"archive", "delete"}:
                            expect(card).to_have_count(0)
                            assert stored() is None
                        elif case.startswith("toggle"):
                            expect(action).to_have_class("habit-day done")
                            assert next(row for row in stored()["grid"] if row["date"] == day)[
                                "done"
                            ]
                            action.click()
                            expect(action).to_have_class("habit-day")
                        elif case == "save":
                            expect(card.locator(".habit-name")).to_have_text("retained edit")
                        else:
                            expect(page.locator(".habit-add")).to_have_count(0)
                            assert (
                                len(
                                    [
                                        row
                                        for row in context.request.get(overview).json()["habits"]
                                        if row["name"] == "retained new habit"
                                    ]
                                )
                                == 1
                            )
                    assert not errors, errors
                    assert (
                        (not console)
                        if case == "toolbar-focus"
                        else (len(console) == 1 and "503" in console[0])
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    page.reload(wait_until="networkidle")
                    assert not errors, errors
                    assert (
                        (not console)
                        if case == "toolbar-focus"
                        else (len(console) == 1 and "503" in console[0])
                    ), console
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    page.screenshot(path=str(output / f"{case}-{width}.png"), full_page=True)
                    for row in context.request.get(overview).json()["habits"]:
                        context.request.delete(base + "/api/habits/" + row["id"])
                    context.request.delete(endpoint)
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
    print(json.dumps(results, indent=2))
    raise SystemExit(any(row["status"] != "passed" for row in results))


if __name__ == "__main__":
    run()
