"""Gate for standing goals in Aide scheduled: create by keyboard, follow, pause, edit, delete."""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
events = {"console": [], "page_errors": []}
scenarios = []


def page_for(browser, width, theme):
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 390 else 844},
        has_touch=width == 390,
        reduced_motion="reduce",
        service_workers="block",
        timezone_id="UTC",
    )
    assert context.request.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
    page = context.new_page()
    page.set_default_timeout(15_000)
    page.on("console", lambda m: events["console"].append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: events["page_errors"].append(str(e)))
    return context, page


def small_targets(page):
    return page.evaluate("""() => [...document.querySelectorAll('#aide-goal-list button, #aide-goal-list summary')]
      .filter(n => n.getClientRects().length).map(n => [n.textContent.trim(), n.getBoundingClientRect().height])
      .filter(([, h]) => h < 44)""")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        context, page = page_for(browser, 1440, "dark")
        assert context.request.post(base + "/api/setup/dismiss").ok
        page.goto(base + "/?view=scheduled&tab=goals", wait_until="networkidle")
        goals_tab = page.locator('[data-scheduled-tab="goals"]')
        expect(goals_tab).to_have_attribute("aria-selected", "true")
        expect(page.locator("#aide-goal-list .aide-scheduled-empty")).to_contain_text(
            "no goals yet"
        )
        create = page.locator("#aide-scheduled-new")
        expect(create).to_have_text("new goal")
        page.screenshot(path=str(out / "goals-empty-dark.png"))

        # make one by keyboard
        create.focus()
        page.keyboard.press("Enter")
        aim = page.locator("#aide-goal-aim")
        expect(aim).to_be_focused()
        aim.fill("keep an eye on my open tasks: tell me when a new one shows up")
        every = page.locator('[role="radiogroup"][aria-label="check every"]')
        every.locator('[aria-checked="true"]').focus()
        page.keyboard.press("ArrowLeft")
        expect(every.locator('[data-value="six_hours"]')).to_have_attribute("aria-checked", "true")
        page.keyboard.press("ArrowLeft")
        expect(every.locator('[data-value="hour"]')).to_have_attribute("aria-checked", "true")
        page.locator(
            '[role="radiogroup"][aria-label="when it wants to change something"] [data-value="act"]'
        ).click()
        page.screenshot(path=str(out / "goals-form-dark.png"))
        page.locator("#aide-goal-form button[type=submit]").click()
        row = page.locator(".aide-goal-row")
        expect(row).to_have_count(1)
        expect(row.locator("strong")).to_have_text("keep an eye on my open tasks")
        expect(row.locator(".aide-goal-meta")).to_contain_text("every hour")
        expect(row.locator(".aide-goal-meta")).to_contain_text("acts on its own")
        # the first check starts right away; with no model here it ends quickly
        expect(row.locator(".aide-schedule-state")).not_to_have_text("checking now", timeout=30_000)
        expect(row.locator(".aide-goal-headline")).to_contain_text("last check failed")
        listed = context.request.get(base + "/api/jarvis/aide-goals").json()["items"][0]
        runs = context.request.get(base + f"/api/jarvis/runs?workflow_id={listed['id']}").json()
        assert len(runs) == 1, runs

        # pause, resume, edit
        row.get_by_role("button", name="pause").click()
        expect(row.locator(".aide-schedule-state")).to_have_text("paused")
        expect(row.get_by_role("button", name="check now")).to_be_disabled()
        row.get_by_role("button", name="resume").click()
        expect(row.locator(".aide-schedule-state")).to_have_text("active")
        row.get_by_role("button", name="edit").click()
        expect(page.locator("#aide-goal-aim")).to_have_value(
            "keep an eye on my open tasks: tell me when a new one shows up"
        )
        page.locator('[role="radiogroup"][aria-label="check every"] [data-value="week"]').click()
        page.locator("#aide-goal-form button[type=submit]").click()
        expect(row.locator(".aide-goal-meta")).to_contain_text("every week")
        assert not small_targets(page), small_targets(page)
        page.screenshot(path=str(out / "goals-row-dark.png"))
        scenarios.append(
            {
                "scenario_id": "aide.goals.desktop",
                "status": "passed",
                "checks": [
                    "empty state",
                    "keyboard create",
                    "first check starts",
                    "pause and resume",
                    "edit rhythm",
                    "44px targets",
                ],
            }
        )
        context.close()

        context, page = page_for(browser, 390, "light")
        page.goto(base + "/?view=scheduled&tab=goals", wait_until="networkidle")
        row = page.locator(".aide-goal-row")
        expect(row).to_have_count(1)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path=str(out / "goals-phone-light.png"))
        row.get_by_role("button", name="delete").tap()
        page.locator(".dialog-overlay [data-dialog-confirm]").tap()
        expect(page.locator("#aide-goal-list .aide-scheduled-empty")).to_be_visible()
        scenarios.append(
            {
                "scenario_id": "aide.goals.phone",
                "status": "passed",
                "checks": ["390px light", "no overflow", "delete with confirm"],
            }
        )
        context.close()
    finally:
        browser.close()

assert not events["console"], events
assert not events["page_errors"], events
(out / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n", encoding="utf-8")
