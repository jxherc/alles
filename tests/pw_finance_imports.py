"""Reviewed local import workflows through Money's header; no live bank or Actual service."""

import base64
import json
import os
import re
import struct
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import show_money_sections

from services.appearance import from_legacy


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            profile = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
                is_mobile=width <= 390,
                has_touch=width <= 390,
                timezone_id="UTC",
            )
            if zoom:
                profile_root = Path(os.environ["ALLES_DATA"]) / profile
                extension = profile_root / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            manifest_version=3,
                            name="owned zoom check",
                            version="1.0",
                            permissions=["tabs"],
                            background={"service_worker": "zoom.js"},
                        )
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    profile_root / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(**options)
            external = []

            def owned_only(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                    external.append(route.request.url)
                    return route.abort("blockedbyclient")
                return route.continue_()

            context.route("**/*", owned_only)
            context.route_web_socket("**/*", lambda ws: ws.close())
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
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            assert api.patch(base + "/api/settings", data={"language": "en", "timezone": "UTC"}).ok
            accounts = [
                api.post(
                    base + "/api/money/accounts",
                    data={
                        "name": name + " " + profile,
                        "currency": currency,
                        "opening": 100,
                    },
                ).json()
                for name, currency in [
                    ("a other account", "CAD"),
                    ("z chosen account résumé; 秋季 | everyday", "USD"),
                ]
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

            def capture(state):
                if zoom:
                    data = base64.b64decode(
                        context.new_cdp_session(page).send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )["data"]
                    )
                    assert struct.unpack("!II", data[16:24]) == (1440, 900)
                    (output / f"{profile}-{state}.png").write_bytes(data)
                else:
                    page.screenshot(path=str(output / f"{profile}-{state}.png"), full_page=True)

            def choose_option(label, name):
                field = page.get_by_role("group", name=label, exact=True)
                trigger = field.get_by_role("button", name="change " + label, exact=True)
                trigger.press("Enter")
                search = field.get_by_role(
                    "searchbox", name="search " + label + " choices", exact=True
                )
                expect(search).to_be_focused()
                search.fill("owned nonexistent choice")
                expect(field.get_by_role("option")).to_have_count(0)
                expect(field.get_by_role("status")).to_contain_text("no matching choices")
                search.press("Escape")
                expect(trigger).to_be_focused()
                expect(trigger).to_have_attribute("aria-expanded", "false")
                trigger.press("Enter")
                catalogue = api.get(
                    base
                    + (
                        "/api/money/accounts"
                        if label == "account"
                        else "/api/finance/imports/profiles"
                    )
                ).json()
                expect(field.get_by_role("option")).to_have_count(
                    len(catalogue if label == "account" else catalogue["profiles"])
                )
                search.fill(name)
                expect(field.get_by_role("option", name=name, exact=True)).to_be_visible()
                search.press("ArrowDown")
                expect(field.get_by_role("option", name=name, exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                expect(trigger).to_be_focused()
                expect(trigger).to_have_attribute("aria-expanded", "false")
                expect(field.locator(".finance-import-selected")).to_have_text(name)

            record = begin("header-destination-preview")
            try:
                page.goto(base + "/?view=money", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth===720 && devicePixelRatio===2")
                    record["native_zoom"] = {"factor": 2, "css_width": 720, "dpr": 2}

                page.locator("#money-manage-toggle").press("Enter")
                header = page.locator("#money-import")
                header.focus()
                page.keyboard.press("Enter")
                panel = page.locator(".finance-import-panel")
                expect(panel).to_be_visible()
                expect(panel.get_by_role("option")).to_have_count(0)
                file_button = panel.get_by_role(
                    "button", name="choose statement or notification file", exact=True
                )
                bounds = file_button.bounding_box()
                assert bounds and bounds["y"] + bounds["height"] <= page.evaluate("innerHeight"), (
                    bounds
                )
                capture("compact-choices")
                choose_option("account", account["name"] + " · USD")
                choose_option("statement format", "CSV (date, payee, amount)")
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
                capture("preview")
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
                choose_option("account", account["name"] + " · USD")
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
                page.locator("#money-manage-toggle").click()
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
                page.locator("#money-manage-toggle").click()
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
                capture("undone")
                passed(record)

                record = begin("unreferenced-overlap-explicit-decisions")
                choose_option("account", account["name"] + " · USD")
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
                assert not legacy and not external, external
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                passed(record)
                choose_option("account", account["name"] + " · USD")
                choose_option("statement format", "CSV (date, payee, amount)")
                expect(page.locator(".finance-import-format-help")).to_be_visible()
                expect(page.locator(".finance-import-format-help")).to_contain_text(
                    "date, payee, amount"
                )
                expect(page.locator(".finance-import-format-help")).to_contain_text(
                    "2026-04-05,groceries,-8.25"
                )
                stable = transactions()
                for kind, content in [
                    ("unsupported-columns", f"posted,merchant,net\n{day},unknown,-2.10\n"),
                    (
                        "ambiguous-date",
                        "date,payee,amount,currency\n04/05/2026,ambiguous date,-2.10,USD\n",
                    ),
                    (
                        "ambiguous-currency",
                        f"date,payee,amount,currency\n{day},ambiguous currency,-2.10,$\n",
                    ),
                ]:
                    record = begin(kind + "-recovery")
                    blocked = upload(kind + "-" + name, content)
                    assert blocked["counts"]["conflicts"] == 1, blocked
                    expect(receipt.locator(".finance-import-apply")).to_have_count(0)
                    assert (
                        api.post(base + "/api/finance/imports/" + blocked["id"] + "/apply").status
                        == 409
                    )
                    assert transactions() == stable
                    record["blocked_preview"] = blocked
                    hint = receipt.locator(".finance-import-repair-hint")
                    expect(hint).to_contain_text(
                        {
                            "unsupported-columns": "amount column",
                            "ambiguous-date": "year-month-day",
                            "ambiguous-currency": "currency code",
                        }[kind]
                    )
                    expect(hint).to_contain_text("preview before applying")
                    record["actual_guidance"] = receipt.inner_text()
                    capture(kind + "-blocked")
                    repaired = f"date,payee,amount,currency,reference\n{day},repaired {kind},-2.10,USD,repaired-{kind}-{profile}\n"
                    corrected = upload("corrected-" + kind + "-" + name, repaired)
                    assert (
                        corrected["counts"]["pending"] == 1
                        and corrected["counts"]["conflicts"] == 0
                    )
                    page.get_by_role("button", name="apply 1 ready row", exact=True).press("Enter")
                    expect(receipt).to_contain_text("applied")
                    assert len(imported(corrected)) == 1
                    page.get_by_role("button", name="undo this import", exact=True).click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).press("Enter")
                    expect(receipt).to_contain_text("undone")
                    assert transactions() == stable
                    record["recovery"] = (
                        "real corrected CSV preview/apply/exact one linked transaction/undo; all original transactions unchanged"
                    )
                    passed(record)
                record = begin("mixed-currency-separate-account-recovery")
                mixed = f"date,payee,amount,currency,reference\n{day},mixed dollar row,-2.10,USD,mixed-usd-{profile}\n{day},mixed canada row,-3.10,CAD,mixed-cad-{profile}\n"
                blocked = upload("mixed-" + name, mixed)
                assert blocked["counts"]["pending"] == 1 and blocked["counts"]["conflicts"] == 1, (
                    blocked
                )
                expect(receipt.locator(".finance-import-apply")).to_have_count(0)
                assert (
                    api.post(base + "/api/finance/imports/" + blocked["id"] + "/apply").status
                    == 409
                )
                assert transactions() == stable
                record["blocked_preview"] = blocked
                record["actual_guidance"] = receipt.inner_text()
                expect(receipt.locator(".finance-import-repair-hint")).to_contain_text(
                    "split the file by currency"
                )
                expect(receipt.locator(".finance-import-repair-hint")).to_contain_text(
                    "amounts are not converted"
                )
                capture("mixed-currency-blocked")
                for selected, code, amount in [
                    (account, "USD", "-2.10"),
                    (accounts[0], "CAD", "-3.10"),
                ]:
                    choose_option("account", selected["name"] + " · " + code)
                    correct = upload(
                        "split-" + code + "-" + name,
                        f"date,payee,amount,currency,reference\n{day},split {code},{amount},{code},split-{code}-{profile}\n",
                    )
                    assert (
                        correct["counts"]["pending"] == 1 and correct["counts"]["conflicts"] == 0
                    ), correct
                    page.get_by_role("button", name="apply 1 ready row", exact=True).press("Enter")
                    expect(receipt).to_contain_text("applied")
                    linked = imported(correct)
                    assert (
                        len(linked) == 1
                        and linked[0]["account_id"] == selected["id"]
                        and Decimal(str(linked[0]["amount"])) == Decimal(amount)
                        and linked[0]["original_amount_text"] == amount
                        and linked[0]["original_currency_code"] == code
                        and linked[0]["base_amount_text"] == amount
                        and linked[0]["base_currency_code"] == code
                    ), linked
                    page.get_by_role("button", name="undo this import", exact=True).click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).press("Enter")
                    expect(receipt).to_contain_text("undone")
                    assert transactions() == stable
                assert not errors and not external and not legacy
                assert all(any(str(status) in m for status in [409, 503]) for m in console), console
                record["recovery"] = (
                    "mixed file refused with no writes; split USD and CAD into matching accounts, exact native amounts applied and undone; all original records preserved"
                )
                passed(record)
            except Exception as error:
                record["status"] = "failed"
                record["error"] = str(error)
                checkpoint()
                capture("failed")
            finally:
                (output / f"{profile}-events.json").write_text(
                    json.dumps(
                        {"page_errors": errors, "console_errors": console, "external": external},
                        indent=2,
                    )
                )
                page.unroute_all(behavior="ignoreErrors")
                context.close()
        browser.close()
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
