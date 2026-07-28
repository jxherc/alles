"""Browser gate for Aide's dedicated scheduled-work screen."""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8045")
URL = f"http://aide.localhost:{PORT}/?app=scheduled"


def run() -> None:
    errors: list[str] = []
    output = Path(os.environ.get("SCREENSHOT_DIR", "/tmp"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.goto(URL, wait_until="domcontentloaded")
            page.locator("#aide-scheduled-view").wait_for(state="visible")

            if label == "mobile":
                page.locator("body.sidebar-hidden").wait_for()

            assert page.locator("#proactive-view").count() == 0
            assert page.locator("select:visible").count() == 0
            assert (
                page.locator('input[type="radio"]:visible, input[type="checkbox"]:visible').count()
                == 0
            )
            assert page.locator("body").evaluate(
                "el => el.scrollWidth <= document.documentElement.clientWidth + 1"
            )
            assert page.locator(".aide-scheduled-head").evaluate(
                "el => el.getBoundingClientRect().right <= document.documentElement.clientWidth"
            )

            if label == "desktop":
                page.get_by_role("button", name="new schedule").click()
                page.locator("#aide-schedule-form").wait_for(state="visible")
                assert page.locator("#aide-schedule-form-status").inner_text() == ""
                page.locator("#aide-schedule-name").fill("morning plan")
                page.locator("#aide-schedule-prompt").fill("prepare a short morning plan")
                page.locator("#aide-schedule-value").fill("09:00")

                daily = page.locator('[data-schedule-kind="schedule"]')
                daily.focus()
                page.keyboard.press("ArrowRight")
                assert (
                    page.locator('[data-schedule-kind="once"]').get_attribute("aria-checked")
                    == "true"
                )
                page.keyboard.press("ArrowLeft")
                assert (
                    page.locator('[data-schedule-kind="schedule"]').get_attribute("aria-checked")
                    == "true"
                )
                page.locator("#aide-schedule-value").fill("09:00")

                page.locator("#aide-schedule-project").click()
                assert page.locator("#aide-schedule-project-menu").is_visible()
                page.keyboard.press("Escape")
                assert page.locator("#aide-schedule-project-menu").is_hidden()

                page.screenshot(
                    path=output / "alles-phase5-scheduled-form-desktop.png",
                    full_page=False,
                )

                page.get_by_role("button", name="save schedule").click()
                row = page.locator(".aide-schedule-row", has_text="morning plan").last
                row.wait_for()
                assert "active" in row.inner_text()

                row.get_by_role("button", name="edit").click()
                page.get_by_text("edit schedule", exact=True).wait_for()
                assert page.locator("#aide-schedule-name").input_value() == "morning plan"
                assert page.locator("#aide-schedule-value").input_value() == "09:00"
                page.locator("#aide-schedule-name").fill("morning notes")
                page.locator('[data-schedule-kind="interval"]').click()
                page.locator("#aide-schedule-value").fill("2")
                page.locator('[data-schedule-unit="hours"]').click()
                page.get_by_role("button", name="save changes").click()
                edited = page.locator(".aide-schedule-row", has_text="morning notes").last
                edited.wait_for()
                assert "interval · every 2h" in edited.inner_text()
                page.wait_for_function(
                    "document.querySelector('#aide-schedule-list')?.textContent.includes('morning notes')"
                    " && !document.querySelector('#aide-schedule-list')?.textContent.includes('loading')"
                )

            page.screenshot(
                path=output / f"alles-phase5-scheduled-{label}.png",
                full_page=False,
            )
            context.close()
        browser.close()
    assert not errors, errors


if __name__ == "__main__":
    run()
