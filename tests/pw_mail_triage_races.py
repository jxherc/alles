"""Review-triggered triage races against owned local mail state."""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from mail_browser_layout import return_to_mail_list
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = ["lost-label-next-add", "pending-flag-open", "unread-return", "label-dialog-other-row"] + [
    "vip-reader-" + mode + "-" + action
    for mode in ["success", "lost", "reject"]
    for action in ["add", "remove"]
]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    aid = account["id"]
    assert api.post("/api/setup/dismiss").ok
    from core.database import CachedMessage, SessionLocal

    def state(uid="701"):
        with SessionLocal() as db:
            r = db.query(CachedMessage).filter_by(account_id=aid, folder="INBOX", uid=uid).one()
            return {"seen": r.seen, "flagged": r.flagged, "labels": r.labels}

    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            adding = case.endswith("add")
            mode = case.split("-")[-2]
            assert api.post(
                "/api/mail/vips",
                data={
                    "email": "sender@example.invalid",
                    "add": not adding if case.startswith("vip-reader-") else False,
                },
            ).ok
            with SessionLocal() as db:
                for r in db.query(CachedMessage).filter_by(account_id=aid):
                    r.seen = case not in {"pending-flag-open", "unread-return"}
                    r.flagged = False
                    r.labels = ""
                db.commit()
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            held = []
            writes = []
            errors = []
            console = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.triage." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def vip():
                return page.locator("#mail-vip")

            def row(uid="701"):
                return page.locator(
                    f'.mail-row[data-aid="{aid}"][data-folder="INBOX"][data-uid="{uid}"]'
                )

            def hold(route):
                response = route.fetch()
                assert response.ok
                held.append((route, response))

            def held_one():
                until = time.monotonic() + 5
                while not held and time.monotonic() < until:
                    page.wait_for_timeout(20)
                assert len(held) == 1

            def label(value):
                row().locator("[data-label]").click()
                dlg = page.get_by_role("dialog")
                dlg.locator("input").fill(value)
                dlg.get_by_role("button", name="ok", exact=True).click()

            try:

                def message(route):
                    uid = parse_qs(urlparse(route.request.url).query)["uid"][0]
                    route.fulfill(
                        json={
                            "uid": uid,
                            "from": "sender@example.invalid",
                            "subject": "read " + uid,
                            "to": "me@example.invalid",
                            "date": "2026-09-25",
                            "text": "body " + uid,
                            "html": "",
                        }
                    )

                page.route(base + "/api/mail/message/*", message)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(row()).to_be_visible()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                endpoint = base + "/api/mail/labels/" + aid
                if case.startswith("vip-reader-"):
                    row("701").locator(".mail-open").click()
                    expect(vip()).to_have_attribute("aria-disabled", "false")
                    expect(vip()).to_have_text("+ VIP" if adding else "VIP ★")

                    def delay(route):
                        if route.request.method == "POST":
                            held.append((route, None))
                        else:
                            route.continue_()

                    page.route(base + "/api/mail/vips", delay)
                    vip().focus()
                    page.keyboard.press("Enter")
                    until = time.monotonic() + 5
                    while not held and time.monotonic() < until:
                        page.wait_for_timeout(20)
                    assert len(held) == 1
                    return_to_mail_list(page)
                    row("702").locator(".mail-open").click()
                    expect(page.locator(".mail-reader-subject")).to_have_text("read 702")
                    page.wait_for_timeout(150)
                    busy = vip().get_attribute("aria-disabled")
                    route, _ = held.pop()
                    if mode == "reject":
                        route.fulfill(status=503, json={"detail": "owned rejected VIP"})
                    else:
                        response = route.fetch()
                        assert response.ok
                        if mode == "lost":
                            route.fulfill(status=503, json={"detail": "owned lost VIP reply"})
                        else:
                            route.fulfill(response=response)
                    expect(vip()).to_have_attribute("aria-disabled", "false")
                    final = not adding if mode == "reject" else adding
                    expect(vip()).to_have_text("VIP ★" if final else "+ VIP")
                    assert (
                        "sender@example.invalid" in api.get("/api/mail/vips").json()["vips"]
                    ) == final
                    assert busy == "true", (
                        "new reader exposed an enabled VIP control while its sender change was pending"
                    )
                elif case == "lost-label-next-add":

                    def lost_first(route):
                        writes.append(route.request.post_data_json)
                        response = route.fetch()
                        assert response.ok
                        if len(writes) == 1:
                            route.fulfill(status=503, json={"detail": "owned lost label reply"})
                        else:
                            route.fulfill(response=response)

                    page.route(endpoint, lost_first)
                    label("work")
                    expect(
                        page.get_by_text(
                            "could not confirm label. owned lost label reply", exact=True
                        )
                    ).to_be_visible()
                    assert state()["labels"] == "work"
                    label("personal")
                    expect(page.get_by_text("labeled", exact=True)).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    assert set(state()["labels"].split(",")) == {"work", "personal"}, (
                        "second label overwrote the committed first label"
                    )
                elif case == "pending-flag-open":
                    page.route(base + "/api/mail/flag/*", hold)
                    row().locator("[data-flag]").click()
                    held_one()
                    row().locator(".mail-open").click()
                    expect(page.locator(".mail-reader-subject")).to_have_text("read 701")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.wait_for_load_state("networkidle")
                    expect(row()).not_to_have_class(re.compile(r".*\bunread\b.*"))
                    assert state()["seen"], (
                        "opening mail while flag was pending dropped automatic read marking"
                    )
                    assert state()["flagged"]
                elif case == "unread-return":
                    page.locator('.mail-nav-item[data-filter="unread"]').click()
                    expect(row()).to_be_visible()
                    row().locator(".mail-open").click()
                    expect(page.locator(".mail-reader-subject")).to_have_text("read 701")
                    expect(row()).to_have_count(0)
                    page.locator("#mail-unread").click()
                    expect(page.get_by_text("marked unread", exact=True)).to_be_visible()
                    assert not state()["seen"]
                    return_to_mail_list(page)
                    expect(row()).to_be_visible()
                else:
                    page.route(base + "/api/mail/flag/*", hold)
                    row("702").locator("[data-flag]").click()
                    held_one()
                    row().locator("[data-label]").click()
                    dlg = page.get_by_role("dialog")
                    dlg.locator("input").fill("work")
                    route, response = held.pop()
                    route.fulfill(response=response)
                    expect(row("702").locator("[data-flag]")).to_have_class("mail-flag on")

                    def record(route):
                        writes.append(route.request.post_data_json)
                        route.continue_()

                    page.route(endpoint, record)
                    dlg.get_by_role("button", name="ok", exact=True).click()
                    expect(dlg).not_to_be_visible()
                    page.wait_for_load_state("networkidle")
                    expect(row().get_by_role("button", name="work", exact=True)).to_be_visible()
                    assert len(writes) == 1, (
                        "label dialog silently dropped after another row rerendered"
                    )
                    assert state()["labels"] == "work"
                assert not errors, errors
                assert not [line for line in console if "503" not in line], console
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
                result.update(status="passed", page_errors=errors, console_errors=console)
            except Exception as e:
                result.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                for route, response in held:
                    try:
                        if response is None:
                            route.fulfill(status=503, json={"detail": "owned cleanup"})
                        else:
                            route.fulfill(response=response)
                    except Exception:
                        pass
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
