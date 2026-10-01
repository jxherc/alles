"""Reviewed local import workflows through Money's header; no live bank or Actual service."""

import json
import os
import re
from datetime import date
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import show_money_sections


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            profile = "desktop" if width == 1440 else "phone"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
                is_mobile=width == 390,
                has_touch=width == 390,
                timezone_id="UTC",
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            errors, console, legacy = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "request",
                lambda request: (
                    legacy.append(request.url)
                    if request.url.endswith("/transactions/import.csv")
                    else None
                ),
            )
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            accounts = [
                api.post(
                    base + "/api/money/accounts",
                    data={
                        "name": name + " " + profile,
                        "currency": currency,
                        "opening": 100,
                    },
                ).json()
                for name, currency in [("a other account", "CAD"), ("z chosen account", "USD")]
            ]
            account = accounts[1]
            aid = account["id"]
            day = date.today().isoformat()
            manual = api.post(
                base + "/api/money/transactions",
                data={
                    "account_id": aid,
                    "date": day,
                    "payee": "manual unrelated " + profile,
                    "amount": -5,
                    "cleared": True,
                },
            ).json()
            name = "daily-" + profile + ".csv"
            payee = "grocer " + profile
            content = f'date,payee,amount,category,notes,tags,reference\n{day},{payee},-12.34,food,weekly shop,"food,home",ref-{profile}\n'

            def checkpoint():
                (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))

            def begin(name):
                record = {
                    "scenario_id": "finance.import." + name,
                    "feature_id": "finance.actual-ledger",
                    "profile": profile,
                    "scope": "real local ledger; no live provider",
                    "status": "failed",
                }
                scenarios.append(record)
                checkpoint()
                return record

            def passed(record):
                record["status"] = "passed"
                checkpoint()

            def transactions():
                response = api.get(base + "/api/money/transactions")
                assert response.ok
                return response.json()

            def upload(filename, text, expected_status=200):
                panel = page.locator(".finance-import-panel")
                with page.expect_file_chooser() as chooser:
                    panel.get_by_role(
                        "button", name="choose statement or notification file", exact=True
                    ).click()
                chooser.value.set_files(
                    {"name": filename, "mimeType": "text/csv", "buffer": text.encode()}
                )
                preview = panel.get_by_role("button", name="preview import", exact=True)
                preview.focus()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/finance/imports/preview")
                ) as result:
                    page.keyboard.press("Enter")
                assert result.value.status == expected_status, result.value.text()
                return result.value.json()

            def imported(batch):
                return [row for row in transactions() if row.get("import_batch_id") == batch["id"]]

            record = begin("header-destination-preview")
            try:
                page.goto(base + "/?view=money", wait_until="networkidle")
                header = page.locator("#money-import")
                header.focus()
                page.keyboard.press("Enter")
                panel = page.locator(".finance-import-panel")
                expect(panel).to_be_visible()
                panel.get_by_role("option", name=account["name"] + " · USD", exact=True).click()
                panel.get_by_role("option", name="CSV (date, payee, amount)", exact=True).click()
                page.route(
                    base + "/api/finance/imports/preview",
                    lambda route: route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic preview unavailable"}',
                    ),
                    times=1,
                )
                upload(name, content, expected_status=503)
                expect(panel).to_contain_text("synthetic preview unavailable")
                assert len([row for row in transactions() if row["account_id"] == aid]) == 1
                batch = upload(name, content)
                assert batch["account_id"] == aid and batch["counts"]["pending"] == 1
                assert not imported(batch) and not legacy
                receipt = page.locator(".finance-import-receipt")
                expect(receipt).to_contain_text(account["name"])
                for text in [
                    "USD -12.34",
                    "category: food",
                    "notes: weekly shop",
                    "tags: food,home",
                ]:
                    expect(receipt).to_contain_text(text)
                metadata = receipt.locator(".finance-import-metadata")
                assert metadata.count() == 3
                assert (
                    metadata.first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 12
                )
                assert metadata.first.evaluate(
                    "el => getComputedStyle(el).color"
                ) == receipt.locator(".finance-import-row-date").evaluate(
                    "el => getComputedStyle(el).color"
                )
                page.screenshot(path=str(output / f"preview-{profile}.png"), full_page=True)
                passed(record)

                record = begin("lost-apply-retry-reload")
                apply_path = base + f"/api/finance/imports/{batch['id']}/apply"

                def lose_apply(route):
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic lost apply response"}',
                    )

                page.route(apply_path, lose_apply, times=1)
                page.get_by_role("button", name="apply 1 ready row", exact=True).click()
                expect(receipt).to_contain_text("synthetic lost apply response")
                before = imported(batch)
                assert len(before) == 1
                page.get_by_role("button", name="apply 1 ready row", exact=True).click()
                expect(
                    page.get_by_role("button", name="undo this import", exact=True)
                ).to_be_visible()
                rows = imported(batch)
                assert len(rows) == 1 and rows[0]["id"] == before[0]["id"]
                transaction = rows[0]
                assert transaction["account_id"] == aid
                assert (transaction["category"], transaction["notes"], transaction["tags"]) == (
                    "food",
                    "weekly shop",
                    "food,home",
                )
                page.reload(wait_until="networkidle")
                expect(
                    page.get_by_role("button", name="undo this import", exact=True)
                ).to_be_visible()
                passed(record)

                record = begin("repeat-and-changed-source")
                panel.get_by_role("option", name=account["name"] + " · USD", exact=True).click()
                duplicate = upload("duplicate-" + name, content)
                assert duplicate["counts"]["duplicates"] == 1
                page.get_by_role("button", name="finish duplicate receipt", exact=True).click()
                expect(receipt).to_contain_text("duplicate")
                changed = upload("changed-" + name, content.replace("weekly shop", "changed note"))
                assert changed["counts"]["conflicts"] == 1
                expect(receipt).to_contain_text("conflict")
                expect(receipt.locator(".finance-import-apply")).to_have_count(0)
                assert len(imported(batch)) == 1
                passed(record)

                record = begin("reconcile-and-edited-undo-guard")
                page.goto(base + "/?view=money", wait_until="networkidle")
                show_money_sections(page)
                row = page.locator(f'.txn[data-id="{transaction["id"]}"]')
                row.locator(".tx-clear").click()
                expect(row.locator(".tx-clear")).to_have_class("tx-clear on")
                page.locator(f'[data-rc-acct="{aid}"]').click()
                statement = page.locator(f"#rc-stmt-{aid}")
                statement.fill("82.66")
                page.locator(f'[data-rc-run="{aid}"]').click()
                expect(page.locator(f"#rc-out-{aid}")).to_contain_text("reconciled")
                page.locator("#money-import").click()
                page.get_by_role("button", name=name + " · applied", exact=True).click()
                page.get_by_role("button", name="undo this import", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(receipt).to_contain_text("changed after apply")
                assert len(imported(batch)) == 1
                passed(record)

                record = begin("failed-undo-retry-preserves-unrelated")
                page.goto(base + "/?view=money", wait_until="networkidle")
                row.locator(".tx-clear").click()
                expect(row.locator(".tx-clear")).not_to_have_class(re.compile(r"\bon\b"))
                page.locator("#money-import").click()
                page.get_by_role("button", name=name + " · applied", exact=True).click()
                undo_path = base + f"/api/finance/imports/{batch['id']}/undo"
                page.route(
                    undo_path,
                    lambda route: route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic undo unavailable"}',
                    ),
                    times=1,
                )
                page.get_by_role("button", name="undo this import", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(receipt).to_contain_text("synthetic undo unavailable")
                assert len(imported(batch)) == 1
                page.get_by_role("button", name="undo this import", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(receipt).to_contain_text("undone")
                assert not imported(batch)
                assert any(row["id"] == manual["id"] for row in transactions())
                assert not any(row["account_id"] == accounts[0]["id"] for row in transactions())
                page.reload(wait_until="networkidle")
                page.get_by_role("button", name=name + " · undone", exact=True).click()
                expect(receipt).to_contain_text("undone")
                page.screenshot(path=str(output / f"undone-{profile}.png"), full_page=True)
                passed(record)

                record = begin("unreferenced-overlap-explicit-decisions")
                panel.get_by_role("option", name=account["name"] + " · USD", exact=True).click()
                overlap = f"date,payee,amount\n{day},overlap {profile},-3.00\n"
                original = upload("original-" + name, overlap)
                assert original["counts"]["pending"] == 1
                page.get_by_role("button", name="apply 1 ready row", exact=True).click()
                expect(receipt).to_contain_text("applied")
                repeated = upload("overlap-" + name, overlap)
                assert repeated["counts"]["conflicts"] == 1
                expect(receipt.locator(".finance-import-apply")).to_have_count(0)
                page.get_by_role("button", name="treat as duplicate", exact=True).click()
                page.get_by_role("button", name="finish duplicate receipt", exact=True).click()
                expect(receipt).to_contain_text("duplicate")
                assert len(imported(original)) == 1 and not imported(repeated)
                additional = upload("intentional-" + name, overlap)
                assert additional["counts"]["conflicts"] == 1
                page.get_by_role("button", name="import as new", exact=True).click()
                page.get_by_role("button", name="apply 1 ready row", exact=True).click()
                expect(
                    page.get_by_role("button", name="undo this import", exact=True)
                ).to_be_visible()
                assert len(imported(additional)) == 1
                page.get_by_role("button", name="undo this import", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(receipt).to_contain_text("undone")
                assert not imported(additional) and len(imported(original)) == 1
                assert any(row["id"] == manual["id"] for row in transactions())
                assert not errors, errors
                assert all(
                    any(str(status) in message for status in [409, 503]) for message in console
                ), console
                assert not legacy
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                passed(record)
            except Exception as error:
                record["error"] = str(error)
                checkpoint()
                page.screenshot(path=str(output / f"failed-{profile}.png"), full_page=True)
            finally:
                page.unroute_all(behavior="ignoreErrors")
                context.close()
        browser.close()
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
