"""Owned budget, goal, and receipt workflows with real local persistence and failure recovery."""

import io
import json
import os
import traceback
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(1440, "dark"), (390, "light")]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
                has_touch=width == 390,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(8000)
            state = {"path": "", "mode": ""}
            held, writes, errors, console, external = [], [], [], [], []
            row = {"profile": f"{width}-{theme}", "status": "failed", "checks": []}
            rows.append(row)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def boundary(route):
                request = route.request
                parsed = urlsplit(request.url)
                if parsed.netloc != urlsplit(base).netloc:
                    external.append(request.url)
                    route.abort("blockedbyclient")
                    return
                if request.method in {"POST", "PATCH", "DELETE"}:
                    writes.append({"path": parsed.path, "method": request.method})
                if parsed.path == state["path"] and request.method == "POST":
                    mode = state["mode"]
                    state["path"] = ""
                    if mode == "hold":
                        held.append(route)
                    elif mode == "malformed":
                        route.fulfill(status=200, json={})
                    else:
                        route.fulfill(status=503, json={"detail": "synthetic save refusal"})
                    return
                route.continue_()

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda socket: socket.close())
            api = context.request

            def post(path, body):
                response = api.post(base + path, data=body)
                assert response.ok, response.text()
                return response.json()

            def read(path):
                response = api.get(base + path)
                assert response.ok, response.text()
                return response.json()

            def task(name):
                toggle = page.locator('[data-money-section="plans"]')
                if toggle.get_attribute("aria-expanded") == "false":
                    toggle.click()
                page.locator(f'[data-money-task="{name}"]').click()

            def release():
                assert len(held) == 1
                request = held.pop()
                response = request.fetch()
                assert response.ok, response.text()
                request.fulfill(response=response)
                return response.json()

            def receipt(color):
                stream = io.BytesIO()
                Image.new("RGB", (24, 24), color).save(stream, format="PNG")
                return stream.getvalue()

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(base + "/api/settings", data={"theme": theme, "language": "en"}).ok
                account = post(
                    "/api/money/accounts",
                    {"name": f"planning {width}", "currency": "CAD", "opening": 100},
                )
                txn = post(
                    "/api/money/transactions",
                    {
                        "account_id": account["id"],
                        "date": date.today().isoformat(),
                        "amount": -12.34,
                        "payee": f"receipt {width}",
                        "category": f"groceries {width}",
                    },
                )
                page.goto(base + "/?view=finance", wait_until="networkidle")
                page.locator('#finance-tabs [data-group-section="money"]').click()
                task("budgets")
                category = f"groceries {width}"
                page.locator("#bf-cat").fill(category)
                page.locator("#bf-amt").fill("75.25")
                state.update(path="/api/money/budgets", mode="malformed")
                page.locator("#bf-add").click()
                expect(page.locator(".toast.error").last).to_contain_text("not confirmed")
                expect(page.locator("#bf-cat")).to_have_value(category)
                expect(page.locator("#bf-amt")).to_have_value("75.25")
                state.update(path="/api/money/budgets", mode="hold")
                page.locator("#bf-add").click()
                expect(page.locator("#bf-add")).to_be_disabled()
                page.locator("#bf-cat").fill("newer budget 草稿")
                page.locator("#bf-amt").fill("99.01")
                saved = release()
                expect(page.locator("#bf-add")).to_be_enabled()
                expect(page.locator("#bf-cat")).to_have_value("newer budget 草稿")
                expect(page.locator("#bf-amt")).to_have_value("99.01")
                assert saved["category"] == category and saved["limit_amt"] == 75.25
                page.locator("#bf-cat").fill(category)
                page.locator("#bf-amt").fill("80.50")
                page.locator("#bf-add").click()
                expect(page.locator("#bf-cat")).to_have_value("")
                budgets = [
                    item for item in read("/api/money/budgets") if item["category"] == category
                ]
                assert len(budgets) == 1 and budgets[0]["limit_amt"] == 80.5
                page.screenshot(path=str(output / f"{width}-budget.png"))
                row["checks"].append(
                    "budget malformed acknowledgment retains input; pending save preserves newer draft; exact cap update persists once"
                )

                task("goals")
                goal_name = f"weekend {width}"
                for field, value in [
                    ("name", goal_name),
                    ("target", "250.50"),
                    ("current", "25.25"),
                    ("monthly", "50.05"),
                ]:
                    page.locator("#gl-" + field).fill(value)
                state.update(path="/api/money/goals", mode="refuse")
                page.locator("#gl-add").click()
                expect(page.locator(".toast.error").last).to_contain_text("failed")
                expect(page.locator("#gl-name")).to_have_value(goal_name)
                state.update(path="/api/money/goals", mode="hold")
                page.locator("#gl-add").click()
                expect(page.locator("#gl-add")).to_be_disabled()
                page.locator("#gl-name").fill("newer goal 草稿")
                goal = release()
                expect(page.locator("#gl-add")).to_be_enabled()
                expect(page.locator("#gl-name")).to_have_value("newer goal 草稿")
                goals = [
                    item for item in read("/api/money/goals")["goals"] if item["name"] == goal_name
                ]
                assert len(goals) == 1
                assert {
                    key: goal[key] for key in ["target", "current", "monthly", "eta_months"]
                } == {"target": 250.5, "current": 25.25, "monthly": 50.05, "eta_months": 5}
                expect(page.locator(f'.goal-row[data-id="{goal["id"]}"]')).to_contain_text(
                    "5mo left"
                )
                page.screenshot(path=str(output / f"{width}-goal.png"))
                row["checks"].append(
                    "goal refused save retains values; retry creates one exact goal; pending newer draft survives; progress and ETA render"
                )

                plans = page.locator('[data-money-section="plans"]')
                plans.click()
                target = page.locator(f'[data-receipt-txn="{txn["id"]}"]')
                state.update(path="/api/uploads", mode="refuse")
                with page.expect_file_chooser() as chooser:
                    target.click()
                chooser.value.set_files(
                    {"name": "first.png", "mimeType": "image/png", "buffer": receipt("white")}
                )
                expect(page.locator(".toast.error").last).to_contain_text(
                    "receipt attachment not confirmed"
                )
                assert next(
                    item for item in read("/api/money/transactions") if item["id"] == txn["id"]
                )["receipt_id"] in (None, "")
                replacement = receipt("blue")
                with page.expect_file_chooser() as chooser:
                    target.click()
                chooser.value.set_files(
                    {"name": "replacement.png", "mimeType": "image/png", "buffer": replacement}
                )
                link = page.locator(f'.txn[data-id="{txn["id"]}"] .tx-receipt')
                expect(link).to_be_visible()
                response = api.get(base + link.get_attribute("href"))
                assert response.ok and response.body() == replacement
                page.reload(wait_until="networkidle")
                expect(link).to_be_visible()
                response = api.get(base + link.get_attribute("href"))
                assert response.ok and response.body() == replacement
                page.screenshot(path=str(output / f"{width}-receipt.png"))
                row["checks"].append(
                    "receipt upload refusal shows error; replacement file retries, attaches exact bytes, survives reload and can be opened"
                )
                assert not errors and not external, (errors, external)
                assert len(console) == 2 and all("503" in item for item in console), console
                row["status"] = "passed"
            except Exception:
                row["error"] = traceback.format_exc()
                page.screenshot(path=str(output / f"{width}-failure.png"))
            finally:
                for request in held:
                    request.abort()
                row.update(errors=errors, console=console, external=external, writes=writes)
                (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.tracing.stop(path=str(output / f"planning-{width}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps(rows, indent=2))
    assert all(row["status"] == "passed" for row in rows)


if __name__ == "__main__":
    run()
