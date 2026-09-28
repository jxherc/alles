"""Finance net-worth history and retry on an owned local browser instance."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    finance = f"http://finance.localhost:{os.environ['PORT']}"
    require_server_ownership(base, run_id)
    artifacts = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    month_start = date.today().replace(day=1)
    prior_month = month_start - timedelta(days=1)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        requests = playwright.request.new_context()
        assert requests.post(base + "/api/setup/dismiss").ok
        account = requests.post(
            base + "/api/money/accounts",
            data={"name": "history account", "currency": "CAD", "opening": 100},
        )
        assert account.ok, account.text()
        account_id = account.json()["id"]
        for txn_date, amount in ((prior_month.isoformat(), 25), (date.today().isoformat(), -5)):
            transaction = requests.post(
                base + "/api/money/transactions",
                data={
                    "account_id": account_id,
                    "date": txn_date,
                    "amount": amount,
                    "payee": "test history movement",
                },
            )
            assert transaction.ok, transaction.text()
        recurring = requests.post(
            base + "/api/money/recurring",
            data={
                "account_id": account_id,
                "amount": -30,
                "payee": "test rent",
                "cycle": "monthly",
                "next_date": (date.today() + timedelta(days=45)).isoformat(),
            },
        )
        assert recurring.ok, recurring.text()
        requests.dispose()
        results = []
        for profile in ("desktop", "phone"):
            context = browser.new_context(
                viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
                timezone_id="UTC",
            )
            page = context.new_page()
            page_errors = []
            console_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.goto(finance, wait_until="networkidle")
            money_tab = page.locator('#finance-tabs [data-group-section="money"]')
            if money_tab.get_attribute("aria-selected") != "true":
                money_tab.click()
            card = page.locator('.money-card[data-card="networth"]')
            expect(card.locator(".nw-svg")).to_be_visible()
            expect(card.locator(".nw-now")).to_contain_text("120")
            assert card.locator(".trend-labels span").count() == 6
            recurring_card = page.locator('.money-card[data-card="recurring"]')
            expect(recurring_card).to_contain_text("test rent")
            expect(recurring_card.locator("#rc-add")).to_be_visible()
            expect(recurring_card.locator("[data-toggle-rec]")).to_have_count(1)
            if profile == "phone":
                page.evaluate(
                    """async () => {
                      const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                      applyAppearance({ preset: 'light', colors: PRESETS.light.colors });
                    }"""
                )
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
            card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-history-{profile}.png"))

            failures = 2

            def history(route):
                nonlocal failures
                if failures:
                    failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"history unavailable"}',
                        content_type="application/json",
                    )
                else:
                    route.continue_()

            page.route("**/api/money/networth-history?*", history)
            page.reload(wait_until="networkidle")
            if profile == "phone":
                page.evaluate(
                    """async () => {
                      const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                      applyAppearance({ preset: 'light', colors: PRESETS.light.colors });
                    }"""
                )
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
            card = page.locator('.money-card[data-card="networth"]')
            retry = card.get_by_role("button", name="retry", exact=True)
            expect(retry).to_be_visible()
            expect(card).to_contain_text("couldn't load history")
            expect(card).not_to_contain_text("not enough history")
            assert retry.bounding_box()["height"] >= 44
            card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-history-unavailable-{profile}.png"))
            if profile == "phone":
                retry.tap()
            else:
                retry.click()
            retry = card.get_by_role("button", name="retry", exact=True)
            expect(retry).to_be_focused()
            if profile == "phone":
                retry.tap()
            else:
                retry.press("Enter")
            expect(card.locator(".nw-svg")).to_be_visible()
            expect(card.locator(".nw-now")).to_contain_text("120")
            expect(card.get_by_role("heading", name="net worth over time")).to_be_focused()
            assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-history-recovered-{profile}.png"))

            forecast_failures = 2

            def forecast(route):
                nonlocal forecast_failures
                if forecast_failures:
                    forecast_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"forecast unavailable"}',
                        content_type="application/json",
                    )
                else:
                    route.continue_()

            page.route("**/api/money/forecast?*", forecast)
            page.reload(wait_until="networkidle")
            projection = page.locator("[data-forecast]")
            retry_forecast = projection.get_by_role("button", name="retry", exact=True)
            expect(retry_forecast).to_be_visible()
            expect(projection).to_contain_text("couldn't load forecast")
            assert retry_forecast.bounding_box()["height"] >= 44
            projection.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-forecast-unavailable-{profile}.png"))
            if profile == "phone":
                retry_forecast.tap()
            else:
                retry_forecast.click()
            retry_forecast = projection.get_by_role("button", name="retry", exact=True)
            expect(retry_forecast).to_be_focused()
            if profile == "phone":
                retry_forecast.tap()
            else:
                retry_forecast.press("Enter")
            expect(projection.locator(".ms-val")).to_contain_text("120")
            expect(projection).to_be_focused()
            assert projection.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            assert forecast_failures == 0
            projection.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-forecast-recovered-{profile}.png"))

            schedule_failures = 1

            def schedule_rule(route):
                nonlocal schedule_failures
                if schedule_failures:
                    schedule_failures -= 1
                    route.fulfill(
                        status=409,
                        body='{"detail":"the Actual schedule end rule cannot be forecast exactly"}',
                        content_type="application/json",
                    )
                else:
                    route.continue_()

            page.route("**/api/money/forecast?*", schedule_rule)
            page.reload(wait_until="networkidle")
            projection = page.locator("[data-forecast]")
            expect(projection).to_contain_text("fix Actual schedule")
            projection.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-forecast-schedule-{profile}.png"))
            retry_forecast = projection.get_by_role("button", name="retry", exact=True)
            if profile == "phone":
                retry_forecast.tap()
            else:
                retry_forecast.click()
            expect(projection.locator(".ms-val")).to_contain_text("120")
            assert schedule_failures == 0

            def canonical_summary(route):
                response = route.fetch()
                payload = response.json()
                payload["ledger"] = "actual"
                route.fulfill(
                    status=response.status,
                    body=json.dumps(payload),
                    content_type="application/json",
                )

            recurring_failures = 2
            recurring_empty = False
            canonical_schedules = [
                {
                    "id": "actual-rent",
                    "payee": "rent in Actual",
                    "amount": -30,
                    "amount_kind": "exact",
                    "cycle": "monthly",
                    "next_date": "2026-10-01",
                    "active": True,
                },
                {
                    "id": "actual-range",
                    "payee": "variable utilities",
                    "amount": None,
                    "amount_kind": "range",
                    "cycle": "actual",
                    "next_date": "",
                    "active": False,
                },
            ]

            def canonical_recurring(route):
                nonlocal recurring_failures, recurring_empty
                if recurring_failures:
                    recurring_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"Actual schedules unavailable"}',
                        content_type="application/json",
                    )
                else:
                    route.fulfill(
                        status=200,
                        body=json.dumps([] if recurring_empty else canonical_schedules),
                        content_type="application/json",
                    )

            page.route("**/api/money/summary?*", canonical_summary)
            page.route("**/api/money/recurring", canonical_recurring)
            page.reload(wait_until="networkidle")
            recurring_card = page.locator('.money-card[data-card="recurring"]')
            recurring_retry = recurring_card.get_by_role("button", name="retry", exact=True)
            expect(recurring_retry).to_be_visible()
            expect(recurring_card).to_contain_text("couldn't load schedules")
            expect(recurring_card).not_to_contain_text("nothing recurring")
            expect(recurring_card.locator("#rc-add")).to_have_count(0)
            assert recurring_retry.bounding_box()["height"] >= 44
            recurring_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-recurring-unavailable-{profile}.png"))
            if profile == "phone":
                recurring_retry.tap()
            else:
                recurring_retry.click()
            recurring_retry = recurring_card.get_by_role("button", name="retry", exact=True)
            expect(recurring_retry).to_be_focused()
            if profile == "phone":
                recurring_retry.tap()
            else:
                recurring_retry.press("Enter")
            expect(recurring_card).to_contain_text("rent in Actual")
            expect(recurring_card).to_contain_text("variable utilities")
            expect(recurring_card).to_contain_text("range")
            expect(recurring_card).to_contain_text("editing in Finance isn't available yet")
            expect(recurring_card.locator("#rc-add")).to_have_count(0)
            expect(recurring_card.locator("[data-toggle-rec], [data-del-rec]")).to_have_count(0)
            expect(recurring_card.get_by_role("heading", name="recurring")).to_be_focused()
            assert recurring_card.evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            recurring_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-recurring-readonly-{profile}.png"))

            recurring_empty = True
            page.reload(wait_until="networkidle")
            recurring_card = page.locator('.money-card[data-card="recurring"]')
            expect(recurring_card).to_contain_text("no auto-post schedules in Actual")
            expect(recurring_card.locator("#rc-add")).to_have_count(0)
            if profile == "desktop":
                page.evaluate("document.documentElement.style.zoom = '2'")
                assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
                assert projection.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
                assert recurring_card.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
            assert failures == 0
            assert not page_errors, page_errors
            assert all("503" in message or "409" in message for message in console_errors), (
                console_errors
            )
            results.append(
                {
                    "profile": profile,
                    "month_end_history": True,
                    "outage_retry": True,
                    "forecast_outage_retry": True,
                    "recurring_canonical_read_and_retry": True,
                    "keyboard_or_touch": True,
                    "reduced_motion": True,
                    "console_errors": console_errors,
                }
            )
            context.close()
        browser.close()
    print(json.dumps(results))


if __name__ == "__main__":
    run()
