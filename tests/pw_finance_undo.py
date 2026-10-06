"""Owned local transaction undo, lost replies and retained drafts; Actual UI is simulated."""

import base64
import json
import os
import struct
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from pw_finance_helpers import show_money_sections  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [
        (width, theme, False) for width in (1440, 820, 390, 320) for theme in ("light", "dark")
    ]
    profiles += [(1440, theme, True) for theme in ("light", "dark")]
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    viewport={"width": width, "height": 844},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    timezone_id="UTC",
                )
                if zoom:
                    root = Path(os.environ["ALLES_DATA"]) / ("undo-zoom-" + theme)
                    extension = root / "extension"
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
                        root / "browser",
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
                errors, console, external, creates, reversals = [], [], [], [], []
                state = {
                    "undo": "normal",
                    "hold_save": False,
                    "canonical": False,
                    "fail_summary": False,
                }
                held_undo, held_save = [], []
                page = context.new_page()
                page.set_default_timeout(8000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )

                def guard(route):
                    url = urlsplit(route.request.url)
                    if (url.scheme, url.netloc) != ("http", urlsplit(base).netloc):
                        external.append(route.request.url)
                        return route.abort()
                    if url.path == "/api/money/summary":
                        if state["fail_summary"]:
                            return route.fulfill(
                                status=503, json={"detail": "owned balance read unavailable"}
                            )
                        if state["canonical"]:
                            result = route.fetch().json()
                            result["ledger"] = "actual"
                            return route.fulfill(json=result)
                    if url.path == "/api/money/transactions" and route.request.method == "POST":
                        creates.append(route.request.post_data_json)
                        if state["canonical"]:
                            # No provider or native ledger write: only the unavailable-capability UI.
                            return route.fulfill(
                                json={**route.request.post_data_json, "id": uuid.uuid4().hex}
                            )
                        if state["hold_save"]:
                            held_save.append(route)
                            return
                    if url.path.endswith("/undo") and route.request.method == "POST":
                        reversals.append({"path": url.path, "body": route.request.post_data_json})
                        if state["undo"] == "held":
                            held_undo.append(route)
                            return
                        if state["undo"] == "lost":
                            result = route.fetch()
                            assert result.ok
                            return route.fulfill(
                                status=503, json={"detail": "owned reply lost after reversal"}
                            )
                    if (
                        url.path.endswith("/undo")
                        and route.request.method == "GET"
                        and state.get("fail_saved_read")
                    ):
                        return route.fulfill(
                            status=503, json={"detail": "owned saved result read unavailable"}
                        )
                    route.continue_()

                def tracked_guard(route):
                    state["active_routes"] = state.get("active_routes", 0) + 1
                    try:
                        guard(route)
                    finally:
                        state["active_routes"] -= 1

                context.route("**/*", tracked_guard)
                context.route_web_socket("**/*", lambda socket: socket.close())
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(
                    base + "/api/settings", data={"timezone": "UTC", "language": "en"}
                ).ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                for account in api.get(base + "/api/money/accounts").json():
                    assert api.delete(base + "/api/money/accounts/" + account["id"]).ok
                account = api.post(
                    base + "/api/money/accounts",
                    data={"name": "owned checking", "currency": "CAD", "opening": 100},
                ).json()
                month = datetime.now(UTC).strftime("%Y-%m")
                today = datetime.now(UTC).date().isoformat()
                keep = api.post(
                    base + "/api/money/transactions",
                    data={
                        "account_id": account["id"],
                        "date": today,
                        "amount": -7,
                        "payee": "keep this expense",
                    },
                ).json()
                record = {"profile": label, "status": "failed"}
                records.append(record)

                def capture(name):
                    png = base64.b64decode(
                        context.new_cdp_session(page).send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )["data"]
                    )
                    assert struct.unpack(">II", png[16:24]) == (width, 844)
                    (out / (label + "-" + name + ".png")).write_bytes(png)

                def open_entry():
                    if page.locator("#money-entry-fields").is_hidden():
                        page.locator("#money-entry-action").press("Enter")

                def quota_blocks_undo(button, expected_state):
                    pointers = page.evaluate(
                        "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                    )
                    pointer = next(item for item in pointers if item["id"] == first["id"])
                    assert pointer["state"] == expected_state
                    open_entry()
                    page.locator("#tx-payee").fill("quota draft 草稿")
                    page.locator("#tx-amt").fill("21.35")
                    page.evaluate(
                        """() => {
                          const ownedStorageSetItem = Storage.prototype.setItem;
                          Storage.prototype.setItem = function(key, value) {
                            if (key === 'alles:finance-saved-transactions' && window.ownedReceiptQuota) {
                              throw new DOMException('owned synthetic quota', 'QuotaExceededError');
                            }
                            return ownedStorageSetItem.call(this, key, value);
                          };
                          window.ownedReceiptQuota = true;
                        }"""
                    )
                    before = len(reversals)
                    button.focus()
                    button.press("Enter")
                    page.wait_for_timeout(100)
                    assert len(reversals) == before, "undo submitted without durable recovery"
                    expect(
                        page.get_by_text(
                            "couldn't save undo recovery in this browser. this attempt wasn't sent. try again.",
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(button).to_be_focused()
                    expect(button).to_be_enabled()
                    expect(page.locator("#tx-payee")).to_have_value("quota draft 草稿")
                    expect(page.locator("#tx-amt")).to_have_value("21.35")
                    assert (
                        page.evaluate(
                            "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                        )
                        == pointers
                    )
                    if expected_state == "uncertain":
                        expect(
                            page.locator(f'[data-dismiss-saved="{first["id"]}"]')
                        ).to_be_disabled()
                        expect(page.locator(f'[data-saved-txn="{first["id"]}"]')).to_contain_text(
                            "undo not confirmed"
                        )
                    else:
                        expect(
                            page.locator(f'[data-dismiss-saved="{first["id"]}"]')
                        ).to_be_enabled()
                        assert any(
                            row["id"] == first["id"]
                            for row in api.get(base + "/api/money/transactions").json()
                        )
                    capture("quota-" + expected_state)
                    page.evaluate("window.ownedReceiptQuota = false")

                def save(payee, amount):
                    open_entry()
                    page.locator("#tx-payee").fill(payee)
                    page.locator("#tx-cat").fill("owned category")
                    page.locator("#tx-amt").fill(amount)
                    with page.expect_response(
                        lambda response: (
                            urlsplit(response.url).path == "/api/money/transactions"
                            and response.request.method == "POST"
                        )
                    ) as response:
                        page.locator("#tx-add").focus()
                        page.locator("#tx-add").press("Enter")
                    assert response.value.ok
                    saved = response.value.json()
                    expect(page.locator(f'[data-saved-txn="{saved["id"]}"]')).to_be_visible()
                    return saved

                try:
                    page.goto(base + "/?view=money&m=" + month, wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base)); await chrome.tabs.setZoom(tab.id,2); return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function(
                            "innerWidth===720 && innerHeight===422 && devicePixelRatio===2"
                        )
                    first = save("first owned expense", "12.50")
                    undo = page.locator(f'[data-undo-saved="{first["id"]}"]')
                    expect(undo).to_be_focused()
                    assert undo.bounding_box()["height"] >= 44
                    capture("saved")
                    quota_blocks_undo(undo, "ready")
                    state["undo"] = "lost"
                    undo.press("Enter")
                    retry = page.locator(f'[data-undo-saved="{first["id"]}"]')
                    expect(retry).to_have_text("retry undo")
                    expect(page.locator(f'[data-saved-txn="{first["id"]}"]')).to_contain_text(
                        "undo not confirmed"
                    )
                    assert [
                        row["id"] for row in api.get(base + "/api/money/transactions").json()
                    ] == [keep["id"]]
                    expect(page.locator(f'[data-dismiss-saved="{first["id"]}"]')).to_be_disabled()
                    state["fail_saved_read"] = True
                    page.reload(wait_until="networkidle")
                    expect(page.locator(f'[data-saved-txn="{first["id"]}"]')).to_contain_text(
                        "undo not confirmed"
                    )
                    quota_blocks_undo(
                        page.locator(f'[data-undo-saved="{first["id"]}"]'), "uncertain"
                    )
                    state.update(fail_saved_read=False, undo="normal")
                    page.locator(f'[data-undo-saved="{first["id"]}"]').press("Enter")
                    expect(page.locator(f'[data-saved-txn="{first["id"]}"]')).to_contain_text(
                        "already removed"
                    )
                    # A second saved transaction exercises a held reversal and newer month/drafts.
                    second = save("second owned expense", "6.25")
                    state["undo"] = "held"
                    page.locator(f'[data-undo-saved="{second["id"]}"]').press("Enter")
                    assert len(held_undo) == 1
                    page.locator("#money-next").press("Enter")
                    page.wait_for_load_state("networkidle")
                    newer_month = page.url.split("m=")[1].split("&")[0]
                    open_entry()
                    page.locator("#tx-payee").fill("newer entry 草稿")
                    page.locator("#tx-amt").fill("44.25")
                    page.locator("#txn-search").fill("keep")
                    show_money_sections(page, task="accounts")
                    if page.locator("#af-name").count() == 0:
                        page.locator("#money-add-acct").click()
                    page.locator("#af-name").fill("newer account 草稿")
                    page.locator("#af-open").fill("77.25")
                    page.locator("#af-name").focus()
                    page.evaluate(
                        "window.newerAccountDraft = document.querySelector('#money-acct-form-wrap')"
                    )
                    pending = held_undo.pop()
                    pending.fulfill(response=pending.fetch())
                    expect(page.locator(f'[data-saved-txn="{second["id"]}"]')).to_contain_text(
                        "transaction undone"
                    )
                    expect(page.locator("#af-name")).to_be_focused()
                    expect(page.locator("#af-name")).to_have_value("newer account 草稿")
                    expect(page.locator("#af-open")).to_have_value("77.25")
                    expect(page.locator("#tx-payee")).to_have_value("newer entry 草稿")
                    expect(page.locator("#tx-amt")).to_have_value("44.25")
                    expect(page.locator("#txn-search")).to_have_value("keep")
                    assert page.url.split("m=")[1].split("&")[0] == newer_month
                    assert page.evaluate(
                        "window.newerAccountDraft === document.querySelector('#money-acct-form-wrap')"
                    )
                    assert api.get(base + "/api/money/accounts").json()[0]["balance"] == 93
                    capture("newer-drafts")
                    pointers = page.evaluate(
                        "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                    )
                    assert all(
                        set(pointer) == {"id", "request_id", "state"} for pointer in pointers
                    )
                    # Return deliberately; an edited saved transaction must refuse direct undo.
                    page.locator("#money-prev").press("Enter")
                    page.wait_for_load_state("networkidle")
                    changed = save("changed owned expense", "3.00")
                    assert api.patch(
                        base + f"/api/money/transactions/{changed['id']}", data={"cleared": True}
                    ).ok
                    state["undo"] = "normal"
                    page.locator(f'[data-undo-saved="{changed["id"]}"]').press("Enter")
                    expect(page.locator(f'[data-saved-txn="{changed["id"]}"]')).to_contain_text(
                        "transaction changed"
                    )
                    changed_row = page.locator(f'.txn[data-id="{changed["id"]}"]')
                    for action in ("edit", "clear", "split", "receipt", "del"):
                        expect(changed_row.locator(f"[data-{action}-txn]")).to_be_enabled()
                    assert (
                        next(
                            row
                            for row in api.get(base + "/api/money/transactions").json()
                            if row["id"] == changed["id"]
                        )["cleared"]
                        is True
                    )
                    # A delayed create reply must retain a newer entry and account form.
                    open_entry()
                    page.locator("#tx-payee").fill("delayed owned expense")
                    page.locator("#tx-cat").fill("owned category")
                    page.locator("#tx-amt").fill("9.00")
                    state["hold_save"] = True
                    page.locator("#tx-add").press("Enter")
                    for _ in range(100):
                        if held_save:
                            break
                        page.wait_for_timeout(10)
                    assert len(held_save) == 1
                    page.locator("#tx-payee").fill("newer after save 草稿")
                    page.locator("#tx-amt").fill("51.75")
                    show_money_sections(page, task="accounts")
                    if page.locator("#af-name").count() == 0:
                        page.locator("#money-add-acct").click()
                    page.locator("#af-name").fill("newer during save 草稿")
                    page.locator("#af-name").focus()
                    pending = held_save.pop()
                    result = pending.fetch()
                    assert result.ok
                    delayed = result.json()
                    state["fail_summary"] = True
                    pending.fulfill(response=result)
                    expect(
                        page.get_by_role("button", name="retry balances", exact=True)
                    ).to_be_visible()
                    expect(page.locator("#tx-payee")).to_have_value("newer after save 草稿")
                    expect(page.locator("#af-name")).to_be_focused()
                    state["fail_summary"] = False
                    page.get_by_role("button", name="retry balances", exact=True).press("Enter")
                    expect(
                        page.get_by_role("button", name="retry balances", exact=True)
                    ).to_have_count(0)
                    expect(page.locator("#tx-payee")).to_have_value("newer after save 草稿")
                    expect(page.locator("#tx-amt")).to_have_value("51.75")
                    expect(page.locator("#af-name")).to_have_value("newer during save 草稿")
                    assert len(creates) == 4
                    assert len({body["request_id"] for body in creates}) == 4
                    assert [
                        row["id"] for row in api.get(base + "/api/money/transactions").json()
                    ] == [delayed["id"], changed["id"], keep["id"]]
                    assert reversals[0]["body"]["request_id"] == first["undo"]["request_id"]
                    assert reversals[1]["body"]["request_id"] == first["undo"]["request_id"]
                    assert reversals[2]["body"]["request_id"] == second["undo"]["request_id"]
                    # Capability failure is labelled honestly; no real Actual call or local write.
                    state.update(canonical=True, hold_save=False)
                    page.reload(wait_until="networkidle")
                    unsupported = save("simulated Actual expense", "2.00")
                    receipt = page.locator(f'[data-saved-txn="{unsupported["id"]}"]')
                    expect(receipt).to_contain_text("undo is unavailable for Actual")
                    expect(receipt.locator("[data-undo-saved]")).to_have_count(0)
                    capture("unsupported")
                    while page.locator("[data-dismiss-saved]").count():
                        dismiss = page.locator("[data-dismiss-saved]").first
                        dismiss.focus()
                        dismiss.press("Enter")
                    expect(page.locator("#money-entry-action")).to_be_focused()
                    page.wait_for_load_state("networkidle")
                    assert (
                        page.evaluate(
                            "JSON.parse(sessionStorage.getItem('alles:finance-saved-transactions'))"
                        )
                        == []
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    assert not errors and not external, (errors, external)
                    assert all(
                        "the server responded with a status of 503" in message
                        or "the server responded with a status of 409" in message
                        for message in console
                    ), console
                    record.update(
                        status="passed",
                        exact_reversal=True,
                        lost_reply_reload=True,
                        newer_month_drafts_focus=True,
                        changed_record_refused=True,
                        delayed_create_drafts=True,
                        failed_balance_retry=True,
                        pointer_only_storage=True,
                        quota_ready_no_submit=True,
                        quota_uncertain_no_submit=True,
                        quota_recovery_same_id=True,
                        simulated_actual_unavailable=True,
                    )
                finally:
                    record.update(page_errors=errors, console_errors=console, external=external)
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
                    for _ in range(500):
                        if not state.get("active_routes", 0):
                            break
                        page.wait_for_timeout(10)
                    assert not state.get("active_routes", 0), "owned browser routes did not settle"
                    context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    run()
