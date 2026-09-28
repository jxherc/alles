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

            def use_light_theme_on_phone():
                if profile != "phone":
                    return
                page.evaluate(
                    """async () => {
                      const { applyAppearance, PRESETS } = await import('/static/js/theme.js');
                      applyAppearance({ preset: 'light', colors: PRESETS.light.colors });
                    }"""
                )
                expect(page.locator("html")).to_have_attribute("data-theme", "light")

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
            envelope_card = page.locator('.money-card[data-card="envelope"]')
            expect(envelope_card.locator("h3")).to_contain_text("age of money:")
            envelope_card.locator("#env-new-cat").fill("food")
            envelope_card.locator("#env-new-amt").fill("10")
            envelope_card.locator("#env-assign-btn").click()
            expect(envelope_card.locator('.env-row[data-cat="food"]')).to_be_visible()
            expect(envelope_card.locator("h3")).to_contain_text("age of money:")
            use_light_theme_on_phone()
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
            use_light_theme_on_phone()
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
            canonical_envelope_month = {
                "month": month_start.strftime("%Y-%m"),
                "income": 200,
                "assigned_total": 60,
                "to_be_budgeted": 90,
                "categories": [
                    {
                        "category_id": "food-id",
                        "category": "food",
                        "group": "living",
                        "assigned": 60,
                        "spent": 10,
                        "available": 100,
                        "target": None,
                    },
                    {
                        "category_id": "vacation-id",
                        "category": "vacation",
                        "group": "plans",
                        "assigned": 0,
                        "spent": 0,
                        "available": 0,
                        "target": None,
                    },
                    {
                        "category_id": "books-id",
                        "category": "books",
                        "group": "plans",
                        "assigned": 0,
                        "spent": 0,
                        "available": 0,
                        "target": None,
                    },
                ],
                "unbound_targets": [
                    {
                        "id": "old-target",
                        "category": "old vacation",
                        "amount": 100,
                        "date": "2027-01-01",
                        "reason": "choose an Actual category",
                    }
                ],
                "pending_assignments": [],
            }
            page.route(
                "**/api/money/envelope?*",
                lambda route: route.fulfill(
                    status=200,
                    body=json.dumps(canonical_envelope_month),
                    content_type="application/json",
                ),
            )
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

            alert_failures = 2
            alerts_empty = False
            current_alerts = {
                "upcoming_bills": [
                    {
                        "id": "variable-bill",
                        "payee": "variable utilities",
                        "amount": None,
                        "amount_kind": "range",
                        "days": 2,
                    },
                    {
                        "id": "approx-bill",
                        "payee": "approximate rent",
                        "amount": -50,
                        "amount_kind": "approx",
                        "days": 3,
                    },
                ],
                "large_purchases": [
                    {"id": "actual-purchase", "payee": "current market", "amount": -250}
                ],
                "watch_hits": [
                    {
                        "id": "actual-purchase",
                        "watch": "groceries",
                        "payee": "current market",
                        "amount": -250,
                    }
                ],
                "low_balance": [
                    {
                        "id": "actual-account",
                        "name": "current checking",
                        "balance": 5,
                        "threshold": 80,
                    }
                ],
            }

            def canonical_alerts(route):
                nonlocal alert_failures, alerts_empty
                if alert_failures:
                    alert_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"Actual alerts unavailable"}',
                        content_type="application/json",
                    )
                else:
                    payload = (
                        {key: [] for key in current_alerts} if alerts_empty else current_alerts
                    )
                    route.fulfill(
                        status=200,
                        body=json.dumps(payload),
                        content_type="application/json",
                    )

            page.route("**/api/money/alerts?*", canonical_alerts)
            page.reload(wait_until="networkidle")
            use_light_theme_on_phone()
            alert_content = page.locator("#money-alerts-content")
            alert_retry = alert_content.get_by_role("button", name="retry", exact=True)
            expect(alert_retry).to_be_visible()
            expect(alert_content).to_contain_text("couldn't load alerts")
            expect(alert_content).not_to_contain_text("no alerts right now")
            assert alert_retry.bounding_box()["height"] >= 44
            alert_content.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-alerts-unavailable-{profile}.png"))
            if profile == "phone":
                alert_retry.tap()
            else:
                alert_retry.click()
            alert_retry = alert_content.get_by_role("button", name="retry", exact=True)
            expect(alert_retry).to_be_focused()
            if profile == "phone":
                alert_retry.tap()
            else:
                alert_retry.press("Enter")
            expect(alert_content).to_contain_text("variable utilities amount varies")
            expect(alert_content).to_contain_text("approximate rent ≈")
            expect(alert_content).to_contain_text("current market")
            expect(alert_content).to_contain_text("current checking low")
            expect(alert_content).to_be_focused()
            assert alert_content.evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            if profile == "desktop":
                page.evaluate("document.documentElement.style.zoom = '2'")
                assert alert_content.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
                page.evaluate("document.documentElement.style.zoom = '1'")
            alert_content.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-alerts-current-{profile}.png"))

            alerts_empty = True
            alert_failures = 1
            page.reload(wait_until="networkidle")
            use_light_theme_on_phone()
            alert_content = page.locator("#money-alerts-content")
            alert_retry = alert_content.get_by_role("button", name="retry", exact=True)
            if profile == "phone":
                alert_retry.tap()
            else:
                alert_retry.click()
            expect(alert_content).to_contain_text("no alerts right now")
            expect(alert_content).to_be_focused()
            alert_content.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-alerts-empty-{profile}.png"))
            page.reload(wait_until="networkidle")
            expect(page.locator("#money-alerts-content")).to_be_empty()

            age_failures = 2
            age_empty = False

            def canonical_age(route):
                nonlocal age_failures, age_empty
                if age_failures:
                    age_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"Actual age unavailable"}',
                        content_type="application/json",
                    )
                else:
                    payload = {"age": None, "sample": 0} if age_empty else {"age": 10, "sample": 1}
                    route.fulfill(
                        status=200,
                        body=json.dumps(payload),
                        content_type="application/json",
                    )

            page.route("**/api/money/age-of-money", canonical_age)
            envelope_failures = 2

            def canonical_envelope(route):
                nonlocal envelope_failures
                if envelope_failures:
                    envelope_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"Actual budget month unavailable"}',
                        content_type="application/json",
                    )
                else:
                    route.fulfill(
                        status=200,
                        body=json.dumps(canonical_envelope_month),
                        content_type="application/json",
                    )

            page.route("**/api/money/envelope?*", canonical_envelope)
            assignment_writes = []
            assignment_failures = 1

            def canonical_assignment(route):
                nonlocal assignment_failures
                payload = route.request.post_data_json
                assignment_writes.append(payload)
                assert payload["category_id"] == "food-id"
                assert payload["expected_amount"] in {60, 75}
                if assignment_failures:
                    assignment_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"Actual assignment unavailable"}',
                        content_type="application/json",
                    )
                    return
                canonical_envelope_month["categories"][0]["assigned"] = payload["amount"]
                canonical_envelope_month["pending_assignments"] = []
                route.fulfill(
                    status=200,
                    body=json.dumps(
                        {
                            "category_id": "food-id",
                            "category": "food",
                            "month": canonical_envelope_month["month"],
                            "assigned": payload["amount"],
                        }
                    ),
                    content_type="application/json",
                )

            page.route("**/api/money/envelope/assign", canonical_assignment)
            target_failures = 1
            target_writes = []

            def canonical_target(route):
                nonlocal target_failures
                payload = route.request.post_data_json
                target_writes.append(payload)
                if target_failures:
                    target_failures -= 1
                    route.fulfill(
                        status=503,
                        body='{"detail":"target save unavailable"}',
                        content_type="application/json",
                    )
                    return
                target = next(
                    row
                    for row in canonical_envelope_month["categories"]
                    if row["category_id"] == payload["category_id"]
                )
                target["target"] = (
                    {
                        "id": "actual-native:funding_target:food-id",
                        "amount": payload["amount"],
                        "date": payload["target_date"],
                        "funded": 0.5,
                    }
                    if payload["amount"]
                    else None
                )
                route.fulfill(
                    status=200,
                    body=json.dumps(
                        {"category_id": payload["category_id"], "target": target["target"]}
                    ),
                    content_type="application/json",
                )

            def canonical_target_bind(route):
                payload = route.request.post_data_json
                assert payload["target_id"] == "old-target"
                assert payload["category_id"] in {"vacation-id", "books-id"}
                canonical_envelope_month["categories"][1]["target"] = None
                destination = next(
                    row
                    for row in canonical_envelope_month["categories"]
                    if row["category_id"] == payload["category_id"]
                )
                destination["target"] = {
                    "id": "old-target",
                    "amount": 100,
                    "date": "2027-01-01",
                    "funded": 0,
                }
                canonical_envelope_month["unbound_targets"] = []
                route.fulfill(
                    status=200,
                    body=json.dumps({"category_id": payload["category_id"]}),
                    content_type="application/json",
                )

            page.route("**/api/money/envelope/target/bind", canonical_target_bind)
            page.route("**/api/money/envelope/target", canonical_target)
            page.reload(wait_until="networkidle")
            use_light_theme_on_phone()
            envelope_card = page.locator('.money-card[data-card="envelope"]')
            age_retry = envelope_card.locator("#age-retry")
            envelope_retry = envelope_card.locator("#env-retry")
            expect(age_retry).to_be_visible()
            expect(envelope_retry).to_be_visible()
            expect(envelope_card).to_contain_text("couldn't load age of money")
            expect(envelope_card).to_contain_text("couldn't load Actual's budget month")
            expect(
                envelope_card.locator("#env-assign-btn, .env-assign, .env-tgt-btn")
            ).to_have_count(0)
            assert age_retry.bounding_box()["height"] >= 44
            assert envelope_retry.bounding_box()["height"] >= 44
            envelope_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-age-unavailable-{profile}.png"))
            if profile == "phone":
                age_retry.tap()
            else:
                age_retry.click()
            age_retry = envelope_card.locator("#age-retry")
            expect(age_retry).to_be_focused()
            if profile == "phone":
                age_retry.tap()
            else:
                age_retry.press("Enter")
            expect(envelope_card).to_contain_text("age of money: 10d")
            expect(envelope_card.locator("h3")).to_be_focused()
            envelope_retry = envelope_card.locator("#env-retry")
            if profile == "phone":
                envelope_retry.tap()
            else:
                envelope_retry.click()
            expect(envelope_retry).to_be_focused()
            if profile == "phone":
                envelope_retry.tap()
            else:
                envelope_retry.press("Enter")
            expect(envelope_card).to_contain_text("spending caps and funding targets stay separate")
            assignment_input = envelope_card.locator(
                '.env-row[data-category-id="food-id"] .env-assign'
            )
            expect(assignment_input).to_have_value("60")
            expect(assignment_input).to_have_attribute(
                "aria-label", "assigned this month for living / food"
            )
            assert assignment_input.bounding_box()["height"] >= 44
            expect(envelope_card.locator('.env-row[data-cat="food"] .env-spent')).to_contain_text(
                "10"
            )
            expect(envelope_card.locator('.env-row[data-cat="food"] .env-avail')).to_contain_text(
                "100"
            )
            expect(envelope_card.locator("#env-assign-btn")).to_have_count(0)
            expect(envelope_card.locator(".env-tgt-btn")).to_have_count(3)
            assert envelope_card.locator(".env-tgt-btn").first.bounding_box()["height"] >= 44
            assert envelope_card.locator(".env-bind-target").bounding_box()["height"] >= 44
            expect(envelope_card.locator("h3")).to_be_focused()
            if profile == "phone":
                assignment_input.tap()
            else:
                assignment_input.click()
            assignment_input.fill("75")
            assignment_input.press("Tab")
            expect(assignment_input).to_have_value("75")
            expect(envelope_card.locator("#env-save-status")).to_contain_text("save not confirmed")
            retry_save = envelope_card.get_by_role("button", name="retry same amount", exact=True)
            if profile == "phone":
                retry_save.tap()
            else:
                retry_save.click()
            expect(envelope_card.locator("#env-save-status")).to_be_empty()
            expect(assignment_input).to_be_focused()
            assert (
                assignment_writes[0]
                == assignment_writes[1]
                == {
                    "category_id": "food-id",
                    "month": canonical_envelope_month["month"],
                    "amount": 75,
                    "expected_amount": 60,
                }
            )
            canonical_envelope_month["pending_assignments"] = [
                {
                    "category_id": "food-id",
                    "category": "food",
                    "assigned": 80,
                    "expected_assigned": 75,
                }
            ]
            page.reload(wait_until="networkidle")
            envelope_card = page.locator('.money-card[data-card="envelope"]')
            pending_retry = envelope_card.get_by_role("button", name="retry the same amount")
            expect(pending_retry).to_be_visible()
            expect(
                envelope_card.locator('.env-row[data-category-id="food-id"] .env-assign')
            ).to_have_count(0)
            if profile == "phone":
                pending_retry.tap()
            else:
                pending_retry.click()
            expect(
                envelope_card.locator('.env-row[data-category-id="food-id"] .env-assign')
            ).to_have_value("80")
            assert assignment_writes[-1]["expected_amount"] == 75
            food_target = envelope_card.get_by_role(
                "button", name="set funding target for living / food"
            )
            if profile == "phone":
                food_target.tap()
            else:
                food_target.press("Enter")
            target_dialog = page.get_by_role(
                "dialog", name="funding target for living / food (0 clears it)"
            )
            target_date_field = target_dialog.get_by_label("by date (YYYY-MM-DD, optional)")
            assert target_date_field.bounding_box()["width"] >= 200
            assert target_date_field.bounding_box()["height"] >= 44
            page.screenshot(path=str(artifacts / f"finance-target-editor-{profile}.png"))
            target_dialog.get_by_label("target amount").fill("200")
            target_date_field.fill("2027-02-01")
            page.screenshot(path=str(artifacts / f"finance-target-editor-filled-{profile}.png"))
            target_dialog.get_by_role("button", name="save").click()
            expect(envelope_card.locator("#env-target-status")).to_contain_text("couldn't save")
            food_target.click()
            target_dialog = page.get_by_role(
                "dialog", name="funding target for living / food (0 clears it)"
            )
            expect(target_dialog.get_by_label("target amount")).to_have_value("200")
            expect(target_dialog.get_by_label("by date (YYYY-MM-DD, optional)")).to_have_value(
                "2027-02-01"
            )
            target_dialog.get_by_role("button", name="save").click()
            expect(envelope_card).to_contain_text("target CAD200.00 by 2027-02-01")
            assert target_writes[0]["category_id"] == target_writes[1]["category_id"] == "food-id"
            choose_category = envelope_card.get_by_role("button", name="choose category")
            if profile == "phone":
                choose_category.tap()
            else:
                choose_category.press("Enter")
            picker = page.get_by_role("dialog", name="choose the category for old vacation")
            picker.get_by_role("button", name="plans / vacation").press("Enter")
            expect(envelope_card.locator(".env-unbound")).to_have_count(0)
            expect(envelope_card).to_contain_text("target CAD100.00 by 2027-01-01")
            expect(
                envelope_card.get_by_role("button", name="edit funding target for plans / vacation")
            ).to_be_focused()
            envelope_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-target-bound-{profile}.png"))
            move_target = envelope_card.locator(
                '.env-row[data-category-id="vacation-id"] .env-move-target'
            )
            assert move_target.bounding_box()["height"] >= 44
            if profile == "phone":
                move_target.tap()
            else:
                move_target.press("Enter")
            mover = page.get_by_role("dialog", name="choose the category for plans / vacation")
            mover.get_by_role("button", name="plans / books").press("Enter")
            expect(
                envelope_card.locator('.env-row[data-category-id="vacation-id"]')
            ).not_to_contain_text("target CAD100.00")
            expect(envelope_card.locator('.env-row[data-category-id="books-id"]')).to_contain_text(
                "target CAD100.00 by 2027-01-01"
            )
            envelope_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-target-moved-{profile}.png"))
            assert envelope_card.evaluate(
                "element => element.scrollWidth <= element.clientWidth + 1"
            )
            cap_card = page.locator('.money-card[data-card="budgets"]')
            expect(cap_card.locator("h3")).to_contain_text("spending caps")
            expect(cap_card.locator("#bf-cat")).to_have_attribute("placeholder", "Actual category")
            assert cap_card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
            cap_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-spending-caps-{profile}.png"))
            envelope_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-age-current-{profile}.png"))

            age_empty = True
            age_failures = 1
            page.reload(wait_until="networkidle")
            use_light_theme_on_phone()
            envelope_card = page.locator('.money-card[data-card="envelope"]')
            age_retry = envelope_card.locator("#age-retry")
            if profile == "phone":
                age_retry.tap()
            else:
                age_retry.click()
            expect(envelope_card).to_contain_text("age of money: not enough data")
            expect(envelope_card.locator("h3")).to_be_focused()
            envelope_card.scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts / f"finance-age-empty-{profile}.png"))
            if profile == "desktop":
                page.evaluate("document.documentElement.style.zoom = '2'")
                assert card.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
                assert projection.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
                assert recurring_card.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
                assert page.locator("#money-alerts-content").evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
                assert envelope_card.evaluate(
                    "element => element.scrollWidth <= element.clientWidth + 1"
                )
            assert failures == 0
            assert envelope_failures == 0
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
                    "alerts_canonical_read_and_retry": True,
                    "age_canonical_read_and_retry": True,
                    "envelope_canonical_read_and_retry": True,
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
