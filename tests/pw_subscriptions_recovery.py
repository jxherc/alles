"""Local renewal workflows, uncertain writes and history recovery on isolated data."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "daily",
                "create-lost",
                "create-close",
                "detected",
                "create-rejected",
                "load-first",
                "load-draft",
                "history-error",
                "history-focus",
                "undo-focus",
                "undo-during-load",
                "undo-lost",
                "paid-lost",
                "write-rejected",
                "stale-history",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="UTC",
                    service_workers="block",
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(7000)
                api = context.request
                errors, console, posts = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                page.on(
                    "request",
                    lambda req: (
                        posts.append(req.post_data_json)
                        if req.url == base + "/api/subscriptions" and req.method == "POST"
                        else None
                    ),
                )
                result = {
                    "scenario_id": "subscriptions.recovery." + case,
                    "feature_id": "finance.actual-ledger",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                results.append(result)
                name = f"renewal {case} {width}"
                today = date.today().isoformat()
                future = (date.today() + timedelta(days=2)).isoformat()
                sid = None
                account = None

                def reject(route):
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def lost(route):
                    response = route.fetch()
                    assert response.ok, response.text()
                    reject(route)

                def key(locator):
                    expect(locator).to_be_enabled()
                    locator.focus()
                    page.keyboard.press("Enter")

                def subscriptions():
                    return api.get(base + "/api/subscriptions?advance=false").json()[
                        "subscriptions"
                    ]

                def seed(due=future):
                    response = api.post(
                        base + "/api/subscriptions",
                        data={
                            "name": name,
                            "price": 10,
                            "currency": "CAD",
                            "cycle": "monthly",
                            "next_due": due,
                        },
                    )
                    assert response.ok, response.text()
                    return response.json()["id"]

                def set_control(locator, value):
                    locator.evaluate(
                        '(el,value)=>{el.value=value;el.dispatchEvent(new Event("change",{bubbles:true}));}',
                        value,
                    )

                def open_form():
                    page.locator("#sub-name").fill(name)
                    page.locator("#sub-price").fill("10")
                    set_control(page.locator("#sub-due"), future)

                def history():
                    return api.get(base + f"/api/subscriptions/{sid}/payments").json()

                def paid_seed():
                    assert api.patch(
                        base + f"/api/subscriptions/{sid}", data={"next_due": today}
                    ).ok
                    assert api.post(base + f"/api/subscriptions/{sid}/paid").ok

                try:
                    assert api.post(base + "/api/setup/dismiss").ok
                    if case not in [
                        "daily",
                        "create-lost",
                        "create-rejected",
                        "create-close",
                        "detected",
                    ]:
                        sid = seed()
                    if case in [
                        "history-error",
                        "history-focus",
                        "undo-focus",
                        "undo-during-load",
                        "undo-lost",
                        "stale-history",
                    ]:
                        assert api.patch(
                            base + f"/api/subscriptions/{sid}",
                            data={"next_due": (date.today() - timedelta(days=40)).isoformat()},
                        ).ok
                        assert api.post(base + f"/api/subscriptions/{sid}/paid").ok
                        paid_seed()
                        assert len(history()) == 2
                    if case == "paid-lost":
                        assert api.patch(
                            base + f"/api/subscriptions/{sid}", data={"next_due": today}
                        ).ok
                    if case == "load-first":
                        page.route(base + "/api/subscriptions", reject)
                    if case == "detected":
                        page.route(
                            base + "/api/subscriptions/detect",
                            lambda route: route.fulfill(
                                status=200,
                                content_type="application/json",
                                body=json.dumps(
                                    {
                                        "candidates": [
                                            {"payee": name, "amount": -10, "cycle": "monthly"}
                                        ]
                                    }
                                ),
                            ),
                        )
                    page.goto(base + "/?view=subs", wait_until="networkidle")
                    row = page.locator(f'.sub-item[data-id="{sid}"]') if sid else None
                    if case == "detected":
                        key(page.locator("[data-adopt]"))
                        expect(page.locator("#sub-name")).to_have_value(name)
                        expect(page.locator("#sub-price")).to_have_value("10")
                        assert posts == [] and subscriptions() == []
                        key(page.locator("#sub-add-btn"))
                        expect(page.locator("#sub-name")).to_have_value("")
                        assert len(subscriptions()) == 1
                        sid = subscriptions()[0]["id"]
                    elif case == "create-close":
                        open_form()
                        page.route(base + "/api/subscriptions", lost)
                        key(page.locator("#sub-add-btn"))
                        expect(page.locator("#sub-create-status [role=alert]")).to_be_visible()
                        page.unroute(base + "/api/subscriptions")
                        key(page.locator("[data-close-create]"))
                        expect(page.locator(".dialog-overlay")).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(page.locator("#sub-name")).to_have_value(name)
                        key(page.locator("[data-close-create]"))
                        key(page.locator("[data-dialog-confirm]"))
                        expect(page.locator("#sub-name")).to_have_value("")
                        expect(page.locator("#subs-list .sub-item")).to_have_count(1)
                        open_form()
                        key(page.locator("#sub-add-btn"))
                        expect(page.locator("#subs-list .sub-item")).to_have_count(2)
                        assert len(subscriptions()) == 2
                        assert posts[0]["request_id"] != posts[1]["request_id"]
                    elif case in ["daily", "create-lost", "create-rejected"]:
                        open_form()
                        if case == "create-lost":
                            page.route(base + "/api/subscriptions", lost)
                        elif case == "create-rejected":
                            page.route(base + "/api/subscriptions", reject)
                        key(page.locator("#sub-add-btn"))
                        if case != "daily":
                            expect(page.locator("#sub-create-status [role=alert]")).to_contain_text(
                                "could not confirm"
                            )
                            expect(page.locator("#sub-name")).to_have_value(name)
                            expect(page.locator("#sub-name")).to_be_disabled()
                            assert len(subscriptions()) == (1 if case == "create-lost" else 0)
                            page.screenshot(
                                path=str(output / f"{case}-{width}-error.png"), full_page=True
                            )
                            page.unroute(base + "/api/subscriptions")
                            key(page.locator("#sub-add-btn"))
                        expect(page.locator("#sub-name")).to_have_value("")
                        saved = next(s for s in subscriptions() if s["name"] == name)
                        sid = saved["id"]
                        row = page.locator(f'.sub-item[data-id="{sid}"]')
                        expect(row).to_be_visible()
                        assert len(subscriptions()) == 1
                        if case != "daily":
                            assert posts[0]["request_id"] == posts[1]["request_id"]
                        if case == "daily":
                            account = api.post(
                                base + "/api/money/accounts",
                                data={
                                    "name": "renewal checking",
                                    "opening": 100,
                                    "currency": "CAD",
                                },
                            ).json()["id"]
                            page.reload(wait_until="networkidle")
                            key(row.locator(".btn[data-act=edit]"))
                            row.locator("[data-f=name]").fill(name + " corrected")
                            row.locator("[data-f=price]").fill("12.50")
                            set_control(row.locator("[data-f=account_id]"), account)
                            set_control(row.locator("[data-f=next_due]"), today)
                            key(row.locator("[data-act=save]"))
                            expect(row.locator(".sub-name")).to_have_text(name + " corrected")
                            key(row.locator("[data-act=toggle]"))
                            expect(row).to_have_class("sub-item paused")
                            key(row.locator("[data-act=toggle]"))
                            expect(row).to_have_class("sub-item")
                            key(row.locator("[data-act=paid]"))
                            expect(row.locator("[data-act=history]")).to_be_visible()
                            balances = api.get(base + "/api/money/accounts").json()
                            assert (
                                next(a["balance"] for a in balances if a["id"] == account) == 87.5
                            )
                            key(row.locator("[data-act=history]"))
                            key(page.locator(".sub-hist-pop [data-act=undo-last]"))
                            expect(page.locator(".sub-hist-empty")).to_have_text("no payments yet")
                            assert history() == []
                            balances = api.get(base + "/api/money/accounts").json()
                            assert next(a["balance"] for a in balances if a["id"] == account) == 100
                    elif case == "load-first":
                        expect(page.locator("#subs-list [role=alert]")).to_contain_text(
                            "could not load subscriptions"
                        )
                        expect(page.locator("#subs-list")).not_to_contain_text(
                            "nothing tracked yet"
                        )
                        assert len(subscriptions()) == 1
                        page.unroute(base + "/api/subscriptions")
                        key(page.locator("[data-refresh-subs]"))
                        expect(row).to_be_visible()
                    elif case == "load-draft":
                        key(row.locator(".btn[data-act=edit]"))
                        row.locator("[data-f=name]").fill("retained correction")
                        page.route(base + "/api/subscriptions", reject)
                        page.evaluate('() => { window._navigateTo("subs"); }')
                        expect(page.locator("#subs-list [role=alert]")).to_contain_text(
                            "could not load subscriptions"
                        )
                        expect(row.locator("[data-f=name]")).to_have_value("retained correction")
                        page.unroute(base + "/api/subscriptions")
                        key(page.locator("[data-refresh-subs]"))
                        expect(page.locator("#subs-list [role=alert]")).to_have_count(0)
                        expect(row.locator("[data-f=name]")).to_have_value("retained correction")
                        key(row.locator("[data-act=save]"))
                        expect(row.locator(".sub-name")).to_have_text("retained correction")
                    elif case == "history-focus":
                        url = base + f"/api/subscriptions/{sid}/payments"
                        held = []
                        page.route(url, lambda route: held.append(route))
                        key(row.locator("[data-act=history]"))
                        expect(page.locator(".sub-hist-pop [role=status]")).to_contain_text(
                            "loading"
                        )
                        page.locator("#sub-name").fill("typing a new subscription")
                        expect(page.locator("#sub-name")).to_be_focused()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert held
                        for route in held:
                            route.fulfill(response=route.fetch())
                        page.unroute(url)
                        expect(page.locator(".sub-hist-row")).to_have_count(2)
                        expect(page.locator("#sub-name")).to_be_focused()
                        assert len(history()) == 2
                    elif case == "undo-focus":
                        key(row.locator("[data-act=history]"))
                        expect(page.locator(".sub-hist-row")).to_have_count(2)
                        url = base + f"/api/subscriptions/{sid}/payments/undo"
                        held = []
                        page.route(url, lambda route: held.append(route))
                        key(page.locator(".sub-hist-pop [data-act=undo-last]"))
                        navigation = page.locator(
                            '[data-specialist-sidebar-toggle][aria-controls="finance-tabs"]'
                        )
                        expect(navigation).to_be_visible()
                        navigation.focus()
                        expect(navigation).to_be_focused()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert held
                        for route in held:
                            reject(route)
                        page.unroute(url)
                        expect(page.locator(".sub-hist-pop [role=alert]")).to_contain_text(
                            "could not confirm"
                        )
                        expect(navigation).to_be_focused()
                        assert len(history()) == 2
                    elif case == "undo-during-load":
                        key(row.locator("[data-act=history]"))
                        expect(page.locator(".sub-hist-row")).to_have_count(2)
                        held = []
                        page.route(base + "/api/subscriptions", lambda route: held.append(route))
                        page.evaluate('() => { window._navigateTo("subs"); }')
                        expect(page.locator("#subs-list > [role=status]")).to_contain_text(
                            "loading"
                        )
                        page.route(base + f"/api/subscriptions/{sid}/payments/undo", reject)
                        key(page.locator(".sub-hist-pop [data-act=undo-last]"))
                        expect(page.locator(".sub-hist-pop [role=alert]")).to_contain_text(
                            "could not confirm"
                        )
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert held
                        for route in held:
                            route.fulfill(response=route.fetch())
                        page.unroute(base + "/api/subscriptions")
                        expect(page.locator("#subs-list > [role=status]")).to_have_count(0)
                        assert len(history()) == 2
                    elif case == "history-error":
                        url = base + f"/api/subscriptions/{sid}/payments"
                        page.route(url, reject)
                        key(row.locator("[data-act=history]"))
                        expect(page.locator(".sub-hist-pop [role=alert]")).to_contain_text(
                            "could not load payments"
                        )
                        expect(page.locator(".sub-hist-empty")).to_have_count(0)
                        page.screenshot(
                            path=str(output / f"{case}-{width}-error.png"), full_page=True
                        )
                        page.unroute(url)
                        key(page.locator("[data-history-retry]"))
                        expect(page.locator(".sub-hist-row")).to_have_count(2)
                        page.keyboard.press("Escape")
                        expect(page.locator(".sub-hist-pop")).to_have_count(0)
                        expect(row.locator("[data-act=history]")).to_be_focused()
                    elif case in ["undo-lost", "stale-history"]:
                        original = history()
                        key(row.locator("[data-act=history]"))
                        expect(page.locator(".sub-hist-row")).to_have_count(2)
                        url = base + f"/api/subscriptions/{sid}/payments/undo"
                        if case == "undo-lost":
                            page.route(url, lost)
                        else:
                            paid_seed()
                        key(page.locator(".sub-hist-pop [data-act=undo-last]"))
                        expect(page.locator(".sub-hist-pop [role=alert]")).to_be_visible()
                        if case == "undo-lost":
                            assert len(history()) == 1
                            page.unroute(url)
                            key(page.locator(".sub-hist-pop [data-act=undo-last]"))
                            expect(page.locator(".sub-hist-pop [role=alert]")).to_contain_text(
                                "no longer"
                            )
                            assert len(history()) == 1
                            assert history()[0]["id"] == next(
                                p["id"] for p in original if not p["can_undo"]
                            )
                        else:
                            expect(page.locator(".sub-hist-pop [role=alert]")).to_contain_text(
                                "newer payment"
                            )
                            assert len(history()) == 3
                        key(page.locator("[data-history-retry]"))
                        expect(page.locator(".sub-hist-pop [role=alert]")).to_have_count(0)
                    elif case == "paid-lost":
                        url = base + f"/api/subscriptions/{sid}/paid"
                        page.route(url, lost)
                        key(row.locator("[data-act=paid]"))
                        expect(page.locator("#subs-list [role=alert]")).to_contain_text(
                            "could not confirm"
                        )
                        assert len(history()) == 1
                        page.unroute(url)
                        key(page.locator("[data-retry-paid]"))
                        expect(page.locator("#subs-list [role=alert]")).to_have_count(0)
                        assert len(history()) == 1
                    elif case == "write-rejected":
                        url = base + f"/api/subscriptions/{sid}"
                        for action in ["toggle", "save", "del"]:
                            if action == "save":
                                key(row.locator(".btn[data-act=edit]"))
                                row.locator("[data-f=name]").fill("kept draft")
                            page.route(url, reject)
                            key(row.locator(f"[data-act={action}]"))
                            if action == "del":
                                key(page.locator("[data-dialog-confirm]"))
                            expect(page.locator("#subs-list [role=alert]")).to_contain_text(
                                "could not confirm"
                            )
                            assert len(subscriptions()) == 1
                            if action == "save":
                                expect(row.locator("[data-f=name]")).to_have_value("kept draft")
                            page.unroute(url)
                            key(row.locator(f"[data-act={action}]"))
                            if action == "del":
                                key(page.locator("[data-dialog-confirm]"))
                                expect(row).to_have_count(0)
                            else:
                                expect(page.locator("#subs-list [role=alert]")).to_have_count(0)
                    assert not errors, errors
                    assert all(
                        any(str(code) in message for code in [404, 409, 503]) for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
                        "horizontal overflow"
                    )
                    page.screenshot(path=str(output / f"{case}-{width}.png"), full_page=True)
                    page.reload(wait_until="networkidle")
                    assert not errors, errors
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                    page.screenshot(path=str(output / f"{case}-{width}-failed.png"), full_page=True)
                finally:
                    for sub in subscriptions():
                        api.delete(base + "/api/subscriptions/" + sub["id"])
                    if account:
                        api.delete(base + "/api/money/accounts/" + account)
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
    print(json.dumps(results, indent=2))
    raise SystemExit(any(result["status"] != "passed" for result in results))


if __name__ == "__main__":
    run()
