"""Retained account currency choices recover through real Money controls."""

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

data = Path(os.environ["ALLES_DATA"]).resolve()
run_id = os.environ["ALLES_TEST_RUN_ID"]
assert Path(tempfile.gettempdir()).resolve() in data.parents
assert os.environ["ALLES_TEST_DATA"] == "1" and os.environ["PYTHON_DOTENV_DISABLED"] == "1"
assert (data / ".alles-test-owner").read_text().strip() == run_id
assert data in Path(os.environ["ALLES_DB"]).resolve().parents
base = "http://127.0.0.1:" + str(int(os.environ["PORT"]))
origin = urlsplit(base)
require_server_ownership(base, run_id)
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
out.mkdir(parents=True, exist_ok=True)
results = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width in (1440, 390):
            for case in ("month-success", "open-picker", "failed-month-retry", "selected-refresh"):
                context = browser.new_context(
                    viewport={"width": width, "height": 844 if width == 390 else 900},
                    service_workers="block",
                    reduced_motion="reduce",
                    timezone_id="UTC",
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                errors, console, blocked, writes, held = [], [], [], [], []
                state = {
                    "currency": "pass" if case == "selected-refresh" else "fail",
                    "reject_create": True,
                }
                name = "currency recovery " + uuid.uuid4().hex
                record = {"case": case, "width": width, "status": "failed"}
                results.append(record)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )

                def guard(route):
                    request = route.request
                    parsed = urlsplit(request.url)
                    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                        blocked.append(request.url)
                        return route.abort()
                    if parsed.path == "/api/money/currencies":
                        if state["currency"] == "fail":
                            return route.fulfill(
                                status=503, json={"detail": "owned currency read unavailable"}
                            )
                        if state["currency"] == "hold":
                            held.append(route)
                            return None
                    if parsed.path == "/api/money/accounts" and request.method == "POST":
                        writes.append(request.post_data_json)
                        if state["reject_create"]:
                            return route.fulfill(
                                status=503, json={"detail": "owned account save unavailable"}
                            )
                    return route.continue_()

                context.route("**/*", guard)
                context.route_web_socket("**/*", lambda socket: socket.close())
                api = context.request

                def choose(selector, label):
                    control = page.locator(selector)
                    control.tap() if width == 390 else control.press("Enter")
                    option = page.get_by_role("option", name=label, exact=True)
                    option.tap() if width == 390 else option.click()
                    expect(control).to_be_focused()

                def draft(currency):
                    expect(page.locator("#af-name")).to_have_value(name)
                    expect(page.locator("#af-kind")).to_have_attribute("data-value", "savings")
                    expect(page.locator("#af-open")).to_have_value("0012.30")
                    expect(page.locator("#af-low")).to_have_value("0002.50")
                    expect(page.locator("#af-currency")).to_have_attribute("data-value", currency)
                    assert page.evaluate(
                        "Object.entries(window.moneyDraftNodes).every(([id,node]) => document.getElementById(id) === node)"
                    )

                try:
                    assert api.post(base + "/api/setup/dismiss", max_redirects=0).ok
                    assert api.patch(
                        base + "/api/settings",
                        data={"language": "en", "timezone": "UTC"},
                        max_redirects=0,
                    ).ok
                    accounts = api.get(base + "/api/money/accounts", max_redirects=0)
                    assert accounts.ok and accounts.json() == [], (
                        "this regression requires a fresh owned ledger"
                    )
                    page.goto(base + "/?view=money&m=2026-10", wait_until="networkidle")
                    expect(page.locator("#af-name")).to_be_visible()
                    page.locator("#af-name").fill(name)
                    choose("#af-kind", "savings")
                    page.locator("#af-open").fill("0012.30")
                    page.locator("#af-low").fill("0002.50")
                    if case == "selected-refresh":
                        choose("#af-currency", "CAD")
                    else:
                        expect(page.locator("#af-currency-error")).to_contain_text(
                            "could not be loaded"
                        )
                        page.locator("#af-add").press("Enter")
                        assert writes == []
                        expect(page.locator("#af-currency")).to_be_focused()
                    selected = "CAD" if case == "selected-refresh" else ""
                    page.evaluate(
                        "window.moneyDraftNodes = Object.fromEntries(['acct-form','af-name','af-kind','af-open','af-low','af-currency','af-add'].map(id => [id, document.getElementById(id)]))"
                    )
                    state["currency"] = "hold"
                    page.locator("#money-next").press("Enter")
                    deadline = time.monotonic() + 6
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "currency route callback did not arrive"
                    if case == "open-picker":
                        page.locator("#af-currency").press("Enter")
                        expect(page.locator("#af-currency")).to_have_attribute(
                            "aria-expanded", "true"
                        )
                    else:
                        page.locator("#af-name").focus()
                        page.locator("#af-name").evaluate(
                            "el => el.setSelectionRange(2, 8, 'backward')"
                        )
                    state["currency"] = "pass"
                    with page.expect_response(base + "/api/money/currencies") as response:
                        if case == "failed-month-retry":
                            held.pop().fulfill(
                                status=503,
                                json={"detail": "owned second currency read unavailable"},
                            )
                        else:
                            held.pop().continue_()
                    assert response.value.status == (503 if case == "failed-month-retry" else 200)
                    page.wait_for_load_state("networkidle")
                    draft(selected)
                    if case == "open-picker":
                        expect(page.locator("#af-currency")).to_be_focused()
                        expect(page.locator("#af-currency")).to_have_attribute(
                            "aria-expanded", "true"
                        )
                        expect(page.get_by_role("option", name="CAD", exact=True)).to_be_visible()
                    else:
                        expect(page.locator("#af-name")).to_be_focused()
                        assert page.locator("#af-name").evaluate(
                            "el => [el.selectionStart,el.selectionEnd,el.selectionDirection]"
                        ) == [2, 8, "backward"]
                    if case == "failed-month-retry":
                        with page.expect_response(base + "/api/money/currencies") as retry:
                            page.locator("#af-currency-retry").press("Enter")
                        assert retry.value.ok
                        expect(page.locator("#af-currency")).to_be_focused()
                    expect(page.locator("#af-currency-retry")).to_have_count(0)
                    expect(page.locator("#af-currency")).to_have_attribute(
                        "data-options", re.compile(r"CAD\|CAD")
                    )
                    draft(selected)
                    if case == "open-picker":
                        option = page.get_by_role("option", name="CAD", exact=True)
                        option.tap() if width == 390 else option.click()
                    elif not selected:
                        page.locator("#af-add").press("Enter")
                        expect(page.locator("#af-currency-error")).to_contain_text(
                            "choose a currency"
                        )
                        assert writes == []
                        choose("#af-currency", "CAD")
                    page.locator("#af-add").press("Enter")
                    expect(page.locator(".toast.error").last).to_contain_text(
                        "couldn't add account"
                    )
                    assert len(writes) == 1
                    draft("CAD")
                    state["reject_create"] = False
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/money/accounts"
                            and response.request.method == "POST"
                        )
                    ) as saved:
                        page.locator("#af-add").press("Enter")
                    assert saved.value.ok
                    account_id = saved.value.json()["id"]
                    expect(page.locator(f'.money-acct[data-id="{account_id}"]')).to_be_attached()
                    assert len(writes) == 2 and writes[0] == writes[1]
                    assert writes[1]["currency"] == "CAD" and writes[1]["request_id"]
                    page.reload(wait_until="networkidle")
                    response = api.get(base + "/api/money/accounts", max_redirects=0)
                    assert response.ok
                    saved_rows = [item for item in response.json() if item["name"] == name]
                    assert len(saved_rows) == 1
                    saved_account = saved_rows[0]
                    assert saved_account["id"] == account_id and saved_account["currency"] == "CAD"
                    assert (
                        saved_account["kind"] == "savings"
                        and saved_account["opening"] == 12.3
                        and saved_account["low_balance"] == 2.5
                    )
                    record["saved_account"] = saved_account
                    assert not errors and not blocked, (errors, blocked)
                    assert all("503" in message for message in console), console
                    record["status"] = "passed"
                except Exception as error:
                    record["error"] = repr(error)
                finally:
                    record.update(
                        page_errors=errors, console=console, blocked=blocked, writes=writes
                    )
                    try:
                        page.screenshot(path=str(out / f"money-{width}-{case}.png"), full_page=True)
                    except Exception as error:
                        record.update(status="failed", screenshot_error=repr(error))
                    try:
                        for route in held:
                            route.abort()
                        response = api.get(base + "/api/money/accounts", max_redirects=0)
                        if response.ok:
                            for account in response.json():
                                if account["name"] == name:
                                    assert api.delete(
                                        base + "/api/money/accounts/" + account["id"],
                                        max_redirects=0,
                                    ).ok
                    except Exception as error:
                        record.update(status="failed", cleanup_error=repr(error))
                    finally:
                        context.close()
                    (out / "money-currency-recovery.json").write_text(
                        json.dumps(results, indent=2) + "\n"
                    )
    finally:
        browser.close()
raise SystemExit(any(record["status"] != "passed" for record in results))
