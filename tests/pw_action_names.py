"""Named Finance/Skills controls, saved toggle state and keyboard recovery.

Uses only synthetic data in the owned local instance. Browser accessibility
snapshots prove computed names; this is not an assistive-technology session.
"""

import io
import json
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import show_money_sections

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    receipt_image = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(receipt_image, format="PNG")
    receipt_bytes = receipt_image.getvalue()
    results = []
    profiles = [(w, t, False) for w in [1440, 390, 320] for t in ["dark", "light"]]
    profiles += [(1280, t, True) for t in ["dark", "light"]]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900},
                "service_workers": "block",
                "has_touch": width <= 390,
                "locale": "en-US",
                "reduced_motion": "reduce" if theme == "dark" else "no-preference",
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    profile / "browser",
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
            errors, console, external = [], [], []

            def local_only(route):
                if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                    return route.continue_()
                external.append(route.request.url)
                route.abort()

            context.route("**/*", local_only)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            result = {
                "scenario_id": "specialists.action-names",
                "profile": label,
                "status": "failed",
            }
            results.append(result)

            def post(path, body):
                response = context.request.post(base + path, data=body)
                assert response.ok, response.text()
                return response.json()

            def activate(control):
                if width <= 390:
                    control.tap()
                else:
                    control.focus()
                    expect(control).to_be_focused()
                    page.keyboard.press("Enter")

            def named(selector, name, role="button"):
                control = page.locator(selector)
                expect(control).to_have_accessible_name(name)
                expect(page.get_by_role(role, name=name, exact=True)).to_have_count(1)
                control.scroll_into_view_if_needed()
                box = control.bounding_box()
                assert box and box["width"] >= 44 and box["height"] >= 44, (name, box)
                return control

            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                account_name = f'checking & "daily" {label}'
                account = post("/api/money/accounts", {"name": account_name})
                savings = post("/api/money/accounts", {"name": "savings " + label})
                payee = f'R&D "market" {label}'
                day = date.today().isoformat()
                txn = post(
                    "/api/money/transactions",
                    {
                        "account_id": account["id"],
                        "date": day,
                        "amount": -12.5,
                        "payee": payee,
                    },
                )
                transfer = post(
                    "/api/money/transfer",
                    {
                        "from_account": account["id"],
                        "to_account": savings["id"],
                        "amount": 3,
                        "date": day,
                    },
                )
                skill_name = f'packing & "shopping" {label}'
                skill = post("/api/skills", {"name": skill_name, "body": "check the local list"})
                goal = post("/api/money/goals", {"name": "weekend " + label, "target": 100})
                holding = post(
                    "/api/money/holdings",
                    {"symbol": "OWNED" + str(width) + theme.upper(), "qty": 1, "price": 2},
                )
                budget = post(
                    "/api/money/budgets", {"category": "groceries " + label, "limit_amt": 80}
                )
                rule = post("/api/money/rules", {"match": "market " + label, "category": "food"})
                recurring = post(
                    "/api/money/recurring",
                    {
                        "account_id": account["id"],
                        "amount": -5,
                        "payee": "supplies " + label,
                        "next_date": (date.today() + timedelta(days=45)).isoformat(),
                    },
                )
                page.goto(base + "/?view=money", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")

                item = f"{payee}, {day}, −$12.50, {account_name}"
                row = page.locator(f'.txn[data-id="{txn["id"]}"]')
                clear = named(f'[data-clear-txn="{txn["id"]}"]', "cleared: " + item)
                expect(clear).to_have_attribute("aria-pressed", "false")
                failed_path = base + "/api/money/transactions/" + txn["id"]
                page.route(
                    failed_path,
                    lambda route: route.fulfill(
                        status=503, json={"detail": "synthetic interruption"}
                    ),
                )
                activate(clear)
                expect(page.locator(".toast.error").last).to_have_text("failed")
                expect(clear).to_have_attribute("aria-pressed", "false")
                page.unroute(failed_path)
                activate(clear)
                expect(clear).to_have_attribute("aria-pressed", "true")
                if width > 390:
                    expect(clear).to_be_focused()
                result["finance_ax"] = row.aria_snapshot()
                page.screenshot(path=str(out / f"{label}-cleared.png"))
                page.reload(wait_until="networkidle")
                expect(clear).to_have_attribute("aria-pressed", "true")
                activate(clear)
                expect(clear).to_have_attribute("aria-pressed", "false")
                saved = context.request.get(
                    base + f"/api/money/transactions?month={day[:7]}"
                ).json()
                assert not next(t for t in saved if t["id"] == txn["id"])["cleared"]

                edit = named(f'[data-edit-txn="{txn["id"]}"]', "edit " + item)
                activate(edit)
                activate(named(f'[data-cancel-txn="{txn["id"]}"]', "cancel editing " + payee))
                split = named(
                    f'[data-split-txn="{txn["id"]}"]', "split " + item + " across categories"
                )
                expect(split).to_have_attribute("aria-expanded", "false")
                activate(split)
                expect(split).to_have_attribute("aria-expanded", "true")
                named('.split-row-del[data-i="0"]', "remove split row 1")
                page.locator("#split-cancel").click()
                expect(split).to_have_attribute("aria-expanded", "false")
                receipt = named(f'[data-receipt-txn="{txn["id"]}"]', "attach receipt to " + item)
                with page.expect_file_chooser() as chooser:
                    activate(receipt)
                chooser.value.set_files(
                    {
                        "name": "receipt.png",
                        "mimeType": "image/png",
                        "buffer": receipt_bytes,
                    }
                )
                link = named(
                    f'.txn[data-id="{txn["id"]}"] .tx-receipt', "view receipt for " + item, "link"
                )
                response = context.request.get(base + link.get_attribute("href"))
                assert response.ok and response.body() == receipt_bytes
                delete = named(f'[data-del-txn="{txn["id"]}"]', "delete " + item)
                activate(delete)
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(delete).to_be_focused()
                expect(row).to_be_visible()
                for direction, sign, account_label in [
                    ("from", "−", account_name),
                    ("to", "+", savings["name"]),
                ]:
                    leg = transfer[direction]
                    named(
                        f'.txn[data-id="{leg["id"]}"] [data-del-transfer]',
                        f"delete transfer (both legs): {leg['payee']}, {day}, {sign}$3.00, {account_label}",
                    )

                show_money_sections(page)
                for selector, name in [
                    (
                        f'[data-rc-acct="{account["id"]}"]',
                        f"reconcile {account_name} to a statement",
                    ),
                    (f'[data-del-acct="{account["id"]}"]', "delete account " + account_name),
                    (f'[data-del-goal="{goal["id"]}"]', "remove goal weekend " + label),
                    (f'[data-del-hold="{holding["id"]}"]', "remove holding " + holding["symbol"]),
                    (
                        f'[data-del-budget="{budget["id"]}"]',
                        "remove spending cap for groceries " + label,
                    ),
                    (f'[data-del-rule="{rule["id"]}"]', "delete rule for market " + label),
                    (
                        f'[data-del-rec="{recurring["id"]}"]',
                        "delete supplies " + label + " schedule",
                    ),
                    ('.money-card[data-card="goals"] .card-hide', "hide goals card"),
                ]:
                    named(selector, name)

                page.goto(base + "/?view=skills", wait_until="networkidle")
                pin = named(f'.skl-card[data-slug="{skill["slug"]}"] .skl-pin', "pin " + skill_name)
                expect(pin).to_have_attribute("aria-pressed", "false")
                failed_path = base + "/api/skills/" + skill["slug"] + "/pin"
                page.route(
                    failed_path,
                    lambda route: route.fulfill(
                        status=503, json={"detail": "synthetic interruption"}
                    ),
                )
                activate(pin)
                expect(page.locator(".toast.error").last).to_have_text(
                    "pin not confirmed. try again."
                )
                expect(pin).to_have_attribute("aria-pressed", "false")
                expect(pin).to_have_attribute("aria-disabled", "false")
                page.unroute(failed_path)
                activate(pin)
                expect(pin).to_have_attribute("aria-pressed", "true")
                if width > 390:
                    expect(pin).to_be_focused()
                result["skills_ax"] = page.locator(
                    f'.skl-card[data-slug="{skill["slug"]}"]'
                ).aria_snapshot()
                page.screenshot(path=str(out / f"{label}-pinned.png"))
                page.reload(wait_until="networkidle")
                expect(pin).to_have_attribute("aria-pressed", "true")
                activate(pin)
                expect(pin).to_have_attribute("aria-pressed", "false")
                assert not context.request.get(base + "/api/skills/" + skill["slug"]).json()[
                    "pinned"
                ]
                delete = named(
                    f'.skl-card[data-slug="{skill["slug"]}"] .skl-del-q',
                    "delete skill " + skill_name,
                )
                activate(delete)
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(delete).to_be_focused()
                assert context.request.get(base + "/api/skills/" + skill["slug"]).ok
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors and not external, (errors, external)
                assert len(console) == 2 and all("503" in line for line in console), console
                result.update(
                    status="passed",
                    page_errors=errors,
                    console_errors=console,
                    external_attempts=external,
                    native_zoom=zoom,
                )
            except Exception as error:
                result.update(error=str(error), traceback=traceback.format_exc())
                page.screenshot(path=str(out / f"{label}-failed.png"))
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2) + "\n")
        browser.close()
    assert all(row["status"] == "passed" for row in results), results


if __name__ == "__main__":
    run()
