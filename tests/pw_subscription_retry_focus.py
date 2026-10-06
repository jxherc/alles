"""Payment-history retry retains keyboard ownership in the real subscriptions app."""

import json
import os
import tempfile
import time
import uuid
from datetime import date, timedelta
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
cases = (
    "success",
    "empty",
    "error",
    "newer-input-success",
    "newer-input-error",
    "newer-navigation",
    "close-pending",
    "superseded-history",
)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width in (1440, 390):
            for case in cases:
                context = browser.new_context(
                    viewport={"width": width, "height": 844 if width == 390 else 900},
                    service_workers="block",
                    reduced_motion="reduce",
                    timezone_id="UTC",
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                errors, console, blocked, held, ids = [], [], [], [], []
                state = {"mode": "fail", "history_url": ""}
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
                    parsed = urlsplit(route.request.url)
                    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                        blocked.append(route.request.url)
                        return route.abort()
                    if route.request.url == state["history_url"] and route.request.method == "GET":
                        if state["mode"] == "fail":
                            return route.fulfill(
                                status=503, json={"detail": "owned history read unavailable"}
                            )
                        if state["mode"] == "hold":
                            held.append(route)
                            return None
                    return route.continue_()

                context.route("**/*", guard)
                context.route_web_socket("**/*", lambda socket: socket.close())
                api = context.request

                def create():
                    response = api.post(
                        base + "/api/subscriptions",
                        data={
                            "name": "history focus " + uuid.uuid4().hex,
                            "currency": "CAD",
                            "price": 10,
                            "cycle": "custom",
                            "cycle_days": 20,
                            "next_due": (date.today() - timedelta(days=40)).isoformat(),
                        },
                        max_redirects=0,
                    )
                    assert response.ok, response.text()
                    sid = response.json()["id"]
                    ids.append(sid)
                    assert api.post(base + f"/api/subscriptions/{sid}/paid", max_redirects=0).ok
                    return sid

                def history(sid):
                    response = api.get(base + f"/api/subscriptions/{sid}/payments", max_redirects=0)
                    assert response.ok
                    return response.json()

                def wait_held():
                    deadline = time.monotonic() + 6
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "history route callback did not arrive"

                def release(fail=False):
                    state["mode"] = "pass"
                    with page.expect_response(state["history_url"]) as response:
                        if fail:
                            held.pop().fulfill(
                                status=503, json={"detail": "owned retry still unavailable"}
                            )
                        else:
                            held.pop().continue_()
                    assert response.value.status == (503 if fail else 200)
                    page.wait_for_load_state("networkidle")

                try:
                    assert api.post(base + "/api/setup/dismiss", max_redirects=0).ok
                    assert api.patch(
                        base + "/api/settings",
                        data={"language": "en", "timezone": "UTC"},
                        max_redirects=0,
                    ).ok
                    sid = create()
                    second_id = create() if case == "superseded-history" else None
                    before = history(sid)
                    assert len(before) == 1
                    state["history_url"] = base + f"/api/subscriptions/{sid}/payments"
                    page.goto(base + "/?view=subs", wait_until="networkidle")
                    row = page.locator(f'.sub-item[data-id="{sid}"]')
                    launcher = row.locator('[data-act="history"]')
                    launcher.press("Enter")
                    retry = row.locator("[data-history-retry]")
                    expect(retry).to_be_focused()
                    expect(row.locator('.sub-hist-pop [role="alert"]')).to_contain_text(
                        "could not load payments"
                    )
                    state["mode"] = "hold"
                    retry.press("Enter")
                    wait_held()
                    expect(retry).to_have_count(0)
                    close = row.locator("[data-history-close]")
                    expect(row.locator('.sub-hist-pop [role="status"]')).to_contain_text("loading")
                    record["pending_focus"] = page.evaluate("document.activeElement.outerHTML")
                    if case in ("success", "empty", "error"):
                        expect(close).to_be_focused()
                    if case.startswith("newer-input"):
                        draft = page.locator("#sub-name")
                        draft.fill("  newer subscription 草稿  ")
                        draft.evaluate("el => el.setSelectionRange(2, 10, 'backward')")
                        page.evaluate(
                            'window.subscriptionDraftNode = document.getElementById("sub-name")'
                        )
                    elif case == "newer-navigation":
                        navigation = page.locator(
                            '[data-specialist-sidebar-toggle][aria-controls="finance-tabs"]'
                        )
                        expect(navigation).to_be_visible()
                        navigation.focus()
                    elif case == "close-pending":
                        close.press("Enter")
                        expect(launcher).to_be_focused()
                        expect(row.locator(".sub-hist-pop")).to_have_count(0)
                    elif case == "superseded-history":
                        other = page.locator(f'.sub-item[data-id="{second_id}"]')
                        other.locator('[data-act="history"]').press("Enter")
                        expect(other.locator('[data-act="undo-last"]')).to_be_focused()
                    elif case == "empty":
                        # A real second client removes the sole payment before the held read.
                        assert api.post(
                            base + f"/api/subscriptions/{sid}/payments/undo",
                            data={"payment_id": before[0]["id"]},
                            max_redirects=0,
                        ).ok
                        assert history(sid) == []
                    fail = case in ("error", "newer-input-error")
                    release(fail)
                    if case.startswith("newer-input"):
                        expect(draft).to_be_focused()
                        expect(draft).to_have_value("  newer subscription 草稿  ")
                        assert draft.evaluate(
                            "el => [el.selectionStart,el.selectionEnd,el.selectionDirection]"
                        ) == [2, 10, "backward"]
                        assert page.evaluate(
                            'window.subscriptionDraftNode === document.getElementById("sub-name")'
                        )
                        expect(
                            row.locator(
                                "[data-history-retry]" if fail else '[data-act="undo-last"]'
                            )
                        ).to_be_visible()
                    elif case == "newer-navigation":
                        expect(navigation).to_be_focused()
                        expect(row.locator('[data-act="undo-last"]')).to_be_visible()
                    elif case == "close-pending":
                        expect(launcher).to_be_focused()
                        expect(row.locator(".sub-hist-pop")).to_have_count(0)
                    elif case == "superseded-history":
                        expect(other.locator('[data-act="undo-last"]')).to_be_focused()
                        expect(row.locator(".sub-hist-pop")).to_have_count(0)
                        assert len(history(second_id)) == 1
                    elif case == "empty":
                        expect(row.locator(".sub-hist-empty")).to_have_text("no payments yet")
                        expect(close).to_be_focused()
                    else:
                        if case == "error":
                            expect(retry).to_be_focused()
                            state["mode"] = "hold"
                            retry.press("Enter")
                            wait_held()
                            expect(close).to_be_focused()
                            release()
                        undo = row.locator('[data-act="undo-last"]')
                        expect(undo).to_be_focused()
                        assert history(sid) == before
                        undo.press("Enter")
                        expect(row.locator(".sub-hist-empty")).to_have_text("no payments yet")
                        assert history(sid) == []
                    expected = [] if case in ("success", "empty", "error") else before
                    assert history(sid) == expected
                    # Reload the actual page and verify saved state independently of its focus result.
                    page.reload(wait_until="networkidle")
                    assert history(sid) == expected
                    record["saved_payments"] = expected
                    assert not errors and not blocked, (errors, blocked)
                    assert all("503" in message for message in console), console
                    record["status"] = "passed"
                except Exception as error:
                    record["error"] = repr(error)
                finally:
                    record.update(page_errors=errors, console=console, blocked=blocked)
                    try:
                        page.screenshot(
                            path=str(out / f"subscriptions-{width}-{case}.png"), full_page=True
                        )
                    except Exception as error:
                        record.update(status="failed", screenshot_error=repr(error))
                    try:
                        for route in held:
                            route.abort()
                        for sid in ids:
                            assert api.delete(
                                base + f"/api/subscriptions/{sid}", max_redirects=0
                            ).ok
                    except Exception as error:
                        record.update(status="failed", cleanup_error=repr(error))
                    finally:
                        context.close()
                    (out / "subscription-retry-focus.json").write_text(
                        json.dumps(results, indent=2) + "\n"
                    )
    finally:
        browser.close()
raise SystemExit(any(record["status"] != "passed" for record in results))
