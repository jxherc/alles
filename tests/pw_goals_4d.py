"""goals (progress/ETA), reports, and net worth in one totals currency on a USD + EUR ledger."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

base = f"http://127.0.0.1:{os.environ['PORT']}"
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width in (1440, 390):
        record = {
            "scenario_id": "finance.goals-reports-totals",
            "profile": str(width),
            "status": "failed",
        }
        results.append(record)
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            has_touch=width == 390,
            service_workers="block",
            reduced_motion="reduce",
        )
        blocked, errors = [], []

        def guard(route):
            if urlparse(route.request.url).netloc != urlparse(base).netloc:
                blocked.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)
        api = context.request
        page = context.new_page()
        page.set_default_timeout(8000)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        try:
            assert api.post(base + "/api/setup/dismiss").ok
            for old in api.get(base + "/api/money/accounts").json():
                assert api.delete(base + "/api/money/accounts/" + old["id"]).ok
            for old in api.get(base + "/api/money/goals").json()["goals"]:
                assert api.delete(base + "/api/money/goals/" + old["id"]).ok
            assert api.patch(base + "/api/money/totals-currency", data={"base": "CAD"}).ok
            assert api.patch(
                base + "/api/money/totals-currency",
                data={"rate": {"from": "EUR", "to": "USD", "rate": ""}},
            ).ok
            us = api.post(
                base + "/api/money/accounts",
                data={"name": "US", "kind": "checking", "currency": "USD", "opening": 100},
            ).json()
            api.post(
                base + "/api/money/accounts",
                data={"name": "EU", "kind": "savings", "currency": "EUR", "opening": 100},
            )
            for amount, category in ((1000, "salary"), (-200, "food")):
                assert api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": us["id"],
                        "date": "2026-06-10",
                        "amount": amount,
                        "category": category,
                        "payee": "Cafe" if amount < 0 else "work",
                    },
                ).ok
            page.goto(base + "/?view=money&m=2026-06", wait_until="networkidle")
            # neither account is in the ledger's CAD: the note offers the rate, not a guess
            expect(page.locator(".totals-currency-wrap")).to_contain_text(
                "1 account in EUR isn't in these totals"
            )
            # totals in USD, picked from the bar
            page.locator("[data-totals-base]").click()
            page.get_by_role("dialog").locator('[data-value="USD"]').click()
            expect(page.locator("[data-totals-base]")).to_contain_text("USD")
            expect(page.locator(".money-summary .ms-card").first).to_contain_text("USD")
            # then the EUR rate from its note
            page.locator('.totals-currency-note [data-totals-rate="EUR:USD"]').click()
            dialog = page.get_by_role("dialog")
            dialog.locator("input").fill("1,087")
            expect(dialog.locator("input")).to_have_value("1.087")
            dialog.get_by_role("button", name="save rate").click()
            expect(page.locator(".totals-rate")).to_have_text("1 EUR = 1.087 USD")
            # US 900 (100 + 1000 - 200) + EU 100 at 1.087 = 1,008.70
            expect(page.locator(".money-summary .ms-card").first).to_contain_text("1,008.70")
            page.screenshot(path=str(out / f"{width}-totals.png"))
            plans = page.locator('[data-money-section="plans"]')
            if plans.get_attribute("aria-expanded") != "true":
                plans.click()
            page.locator('[data-money-task="goals"]').click()
            goals = page.locator('[data-card="goals"]')
            goals.locator("#gl-name").fill("Emergency Fund")
            goals.locator("#gl-target").fill("1000")
            goals.locator("#gl-current").fill("250")
            goals.locator("#gl-monthly").fill("150")
            goals.locator("#gl-add").click()
            expect(goals.locator(".goal-row .goal-eta")).to_contain_text("25%")
            expect(goals.locator(".goal-row .goal-eta")).to_contain_text("5mo")
            # saved in the ledger's CAD with no CAD rate: shown as saved, not relabelled USD
            expect(goals.locator(".goal-row .goal-nums")).to_contain_text("CAD")
            page.screenshot(path=str(out / f"{width}-goals.png"))
            analytics = page.locator('[data-money-section="analytics"]')
            if analytics.get_attribute("aria-expanded") != "true":
                analytics.click()
            page.locator("#rp-start").evaluate("el => { el.dataset.value = '2026-06-01'; }")
            page.locator("#rp-end").evaluate("el => { el.dataset.value = '2026-06-30'; }")
            page.locator("#rp-run").click()
            report = page.locator("#rp-out .rp-tot")
            expect(report).to_contain_text("USD 1,000.00")
            expect(report).to_contain_text("USD 200.00")
            expect(page.locator("#rp-export")).to_have_attribute(
                "href", "/api/money/report/export.csv?start=2026-06-01&end=2026-06-30"
            )
            page.reload(wait_until="networkidle")
            plans = page.locator('[data-money-section="plans"]')
            if plans.get_attribute("aria-expanded") != "true":
                plans.click()
            page.locator('[data-money-task="goals"]').click()
            expect(page.locator('[data-card="goals"]')).to_contain_text("Emergency Fund")
            page.locator(".goal-row [data-del-goal]").click()
            page.get_by_role("alertdialog").locator("[data-dialog-confirm]").click()
            expect(page.locator(".goal-row")).to_have_count(0)
            assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors and not blocked, (errors, blocked)
            record["status"] = "passed"
        except Exception as error:
            record["error"] = str(error)
            page.screenshot(path=str(out / f"{width}-failed.png"))
        finally:
            record.update(page_errors=errors, blocked_external_requests=blocked)
            context.close()
            (out / "scenarios.json").write_text(json.dumps({"scenarios": results}, indent=2))
    browser.close()
print({r["profile"]: r["status"] for r in results})
raise SystemExit(any(r["status"] != "passed" for r in results))
