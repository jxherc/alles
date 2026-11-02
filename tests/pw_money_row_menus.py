"""Money's goal, holding, cap, rule, account and schedule rows keep delete in their more menu (u.10).

for each kind, at ipad landscape and a phone: the menu opens, delete turns the row into
"deleted, undo" with focus on undo, undo brings the row back with focus on its more button and
nothing reached the server, and a second delete that nobody undoes reaches the server after the
wait. an account asks first. a failed delete brings the row back. on a 320px phone a ledger row's
edit, cleared, split and receipt are in its menu, and the row stays inside the first screen.

run through the gate runner, which owns the server and its throwaway data.
"""

import json
import os
import re
from datetime import date, timedelta

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_finance_helpers import pick_money_task

SIZES = {"ipad-landscape": (1180, 820), "phone": (390, 844), "phone-320": (320, 700)}
# kind -> (plan task or None, row selector, menu item attribute, list path, key in a dict reply)
KINDS = {
    "goal": ("goals", ".goal-row", "data-del-goal", "/api/money/goals", "goals"),
    "hold": (None, ".hold-row", "data-del-hold", "/api/money/holdings", "holdings"),
    "budget": ("budgets", ".budget-row", "data-del-budget", "/api/money/budgets", None),
    "rule": (None, ".rules .rule", "data-del-rule", "/api/money/rules", None),
    "rec": ("schedules", ".recur-group", "data-del-rec", "/api/money/recurring", None),
    "acct": ("accounts", ".money-acct", "data-del-acct", "/api/money/accounts", None),
}


def run():
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    day = (date.today() + timedelta(days=9)).isoformat()
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        api = browser.new_context(service_workers="block").request
        assert api.post(base + "/api/setup/dismiss").ok

        def post(path, body):
            reply = api.post(base + path, data=body)
            assert reply.ok, (path, reply.status)
            return reply.json()

        def ids(path, key):
            data = api.get(base + path).json()
            if key:
                data = data[key]
            return {item["id"] for item in data}

        main = post(
            "/api/money/accounts", {"name": "td chequing", "currency": "CAD", "opening": 900}
        )
        for n in range(3):
            post(
                "/api/money/transactions",
                {
                    "account_id": main["id"],
                    "date": date.today().isoformat(),
                    "amount": -10 - n,
                    "category": "food",
                    "payee": "market stall number " + str(n),
                },
            )
        for size, (width, height) in SIZES.items():
            context = browser.new_context(
                viewport={"width": width, "height": height},
                timezone_id="America/Toronto",
                service_workers="block",
                reduced_motion="reduce",
                has_touch=width <= 820,
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_default_timeout(8000)
            tap = width <= 820

            def press(control):
                control.tap() if tap else control.click()

            def open_money():
                page.goto(base + "/?view=money", wait_until="networkidle")
                for name in ("plans", "analytics"):
                    toggle = page.locator(f'[data-money-section="{name}"]')
                    if toggle.get_attribute("aria-expanded") == "false":
                        toggle.click()

            for kind, (task, row_sel, attr, path, key) in KINDS.items():
                if kind == "acct":
                    made = post("/api/money/accounts", {"name": f"spare {size}", "currency": "CAD"})
                elif kind == "goal":
                    made = post("/api/money/goals", {"name": f"trip {size}", "target": 100})
                elif kind == "hold":
                    made = post(
                        "/api/money/holdings",
                        {"symbol": "T" + str(len(SIZES) * width), "qty": 1, "price": 2},
                    )
                elif kind == "budget":
                    made = post("/api/money/budgets", {"category": f"fun {size}", "limit_amt": 10})
                elif kind == "rule":
                    made = post("/api/money/rules", {"match": f"stall {size}", "category": "food"})
                else:
                    made = post(
                        "/api/money/recurring",
                        {
                            "account_id": main["id"],
                            "amount": -5,
                            "payee": f"gym {size}",
                            "next_date": day,
                        },
                    )
                target = made["id"]
                open_money()
                if task:
                    pick_money_task(page, task, tap=tap)
                row = page.locator(f'{row_sel}[data-id="{target}"]')
                more = row.locator(".row-more")
                gone = page.locator(f'.money-row-gone[data-id="{target}"]')
                undo = page.locator(f'[data-undo-del="{target}"]')
                item = page.locator(f"[{attr}='{target}']")
                expect(row).to_be_visible()
                # no visible delete control at rest, and the menu opens on the more button
                expect(item).to_be_hidden()
                press(more)
                expect(item).to_be_visible()
                box = item.bounding_box()
                assert box["height"] >= 44, (kind, box)
                if kind == "acct":
                    # an account takes its transactions with it, so it asks first: cancel keeps it
                    press(item)
                    page.locator("[data-dialog-cancel]").click()
                    expect(gone).to_have_count(0)
                    assert target in ids(path, key)
                    press(more)
                    press(item)
                    page.locator("[data-dialog-confirm]").click()
                else:
                    press(item)
                expect(gone).to_be_visible()
                expect(undo).to_be_focused()
                # undo: the row is back, focus is on its more button, and the server never heard of it
                press(undo)
                expect(row).to_be_visible()
                expect(gone).to_have_count(0)
                expect(more).to_be_focused()
                assert target in ids(path, key), (kind, "deleted before the wait was over")
                # again, and this time nobody undoes it
                press(more)
                press(item)
                if kind == "acct":
                    page.locator("[data-dialog-confirm]").click()
                expect(gone).to_be_visible()
                page.wait_for_timeout(6600)
                expect(gone).to_have_count(0)
                expect(row).to_have_count(0)
                assert target not in ids(path, key), (kind, "still on the server")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            # a failed delete brings the row back with an error
            made = post("/api/money/goals", {"name": f"fails {size}", "target": 100})
            page.route(
                f"**/api/money/goals/{made['id']}",
                lambda route: route.fulfill(status=503, json={"detail": "owned delete refused"}),
            )
            open_money()
            pick_money_task(page, "goals", tap=tap)
            row = page.locator(f'.goal-row[data-id="{made["id"]}"]')
            press(row.locator(".row-more"))
            press(page.locator(f"[data-del-goal='{made['id']}']"))
            expect(page.locator(f'.money-row-gone[data-id="{made["id"]}"]')).to_be_visible()
            expect(row).to_be_visible(timeout=9000)
            expect(page.locator(".toast.error").last).to_be_visible()
            assert made["id"] in ids("/api/money/goals", "goals")
            page.unroute(f"**/api/money/goals/{made['id']}")
            assert not errors, errors[:3]
            context.close()

        # a 320px phone: a ledger row's own actions are in its menu, and the first row fits the first screen
        context = browser.new_context(
            viewport={"width": 320, "height": 700},
            timezone_id="America/Toronto",
            service_workers="block",
            has_touch=True,
        )
        page = context.new_page()
        page.set_default_timeout(8000)
        page.goto(base + "/?view=money", wait_until="networkidle")
        row = page.locator("#txn-rows .txn").first
        expect(row.locator(".tx-actions")).to_have_count(0)
        expect(row.locator("[data-edit-txn]")).to_be_hidden()
        tx = row.get_attribute("data-id")
        more = row.locator(".row-more")
        more.tap()
        items = [
            e.strip() for e in page.locator(f'#menu-txn-{tx} [role="menuitem"]').all_inner_texts()
        ]
        assert (
            items[0] == "edit" and items[-1] == "delete" and "cleared" in items and "split" in items
        ), items
        row.locator("[data-edit-txn]").tap()
        edit = page.locator(f'.txn-edit[data-id="{tx}"]')
        expect(edit).to_be_visible()
        edit.locator("[data-cancel-txn]").tap()
        expect(edit).to_have_count(0)
        expect(more).to_be_focused()
        more.tap()
        row.locator("[data-clear-txn]").tap()
        expect(page.locator(f'.txn[data-id="{tx}"] .row-more')).to_be_visible()
        stored = next(t for t in api.get(base + "/api/money/transactions").json() if t["id"] == tx)
        assert stored["cleared"], stored
        page.locator(f'.txn[data-id="{tx}"] .row-more').tap()
        expect(page.locator(f'.txn[data-id="{tx}"] [data-clear-txn]')).to_have_attribute(
            "aria-label", re.compile(r", on$")
        )
        page.keyboard.press("Escape")
        # growing the window brings the inline actions back, shrinking it takes them in again
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(f'.txn[data-id="{tx}"] .tx-actions')).to_be_visible()
        page.set_viewport_size({"width": 320, "height": 700})
        expect(page.locator(f'.txn[data-id="{tx}"] .tx-actions')).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        context.close()
        browser.close()
    print(json.dumps({"sizes": list(SIZES), "kinds": list(KINDS)}))


if __name__ == "__main__":
    run()
