"""Label and unread controls retain their contract while read marking is pending."""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from mail_browser_layout import return_to_mail_list, split_mail_panes
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = ["label-read-pending", "label-unread-pending", "label-unread-settled", "unread-row-pending"]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    aid = account["id"]
    assert api.post("/api/setup/dismiss").ok
    from core.database import CachedMessage, SessionLocal

    def state():
        with SessionLocal() as db:
            r = db.query(CachedMessage).filter_by(account_id=aid, folder="INBOX", uid="701").one()
            return {"seen": r.seen, "labels": r.labels}

    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            with SessionLocal() as db:
                for r in db.query(CachedMessage).filter_by(account_id=aid):
                    r.seen = False
                    r.labels = ""
                    r.flagged = False
                db.commit()
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            body = []
            pending = []
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

            def row():
                return page.locator(
                    f'.mail-row[data-aid="{aid}"][data-folder="INBOX"][data-uid="701"]'
                )

            def wait_one(items):
                until = time.monotonic() + 5
                while not items and time.monotonic() < until:
                    page.wait_for_timeout(20)
                assert len(items) == 1

            def payload(route):
                uid = parse_qs(urlparse(route.request.url).query)["uid"][0]
                return {
                    "uid": uid,
                    "from": "sender@example.invalid",
                    "to": "me@example.invalid",
                    "subject": "read " + uid,
                    "date": "2026-09-25",
                    "text": "body " + uid,
                    "html": "",
                }

            def message(route):
                if case.startswith("label"):
                    body.append(route)
                else:
                    route.fulfill(json=payload(route))

            try:
                page.route(base + "/api/mail/message/*", message)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(row()).to_be_visible()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if case.startswith("label-unread"):
                    page.locator('.mail-nav-item[data-filter="unread"]').click()
                    expect(row()).to_be_visible()
                    expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                row().locator(".mail-open").click()
                if case.startswith("label"):
                    wait_one(body)
                    with split_mail_panes(page):
                        row().locator("[data-label]").click()
                    dlg = page.get_by_role("dialog")
                    dlg.locator("input").fill("work")
                    page.route(base + "/api/mail/read/*", lambda route: pending.append(route))
                    route = body.pop()
                    route.fulfill(json=payload(route))
                    wait_one(pending)

                    def labels(route):
                        writes.append(route.request.post_data_json)
                        route.continue_()

                    page.route(base + "/api/mail/labels/" + aid, labels)
                    if case == "label-unread-settled":
                        route = pending.pop()
                        response = route.fetch()
                        assert response.ok
                        route.fulfill(response=response)
                        expect(row()).to_have_count(0)
                    dlg.get_by_role("button", name="ok", exact=True).click()
                    expect(dlg).not_to_be_visible()
                    if pending:
                        route = pending.pop()
                        response = route.fetch()
                        assert response.ok
                        route.fulfill(response=response)
                    expect(page.get_by_text("labeled", exact=True)).to_be_visible()
                    assert state()["labels"] == "work"
                    assert len(writes) == 1
                    return_to_mail_list(page)
                    page.locator('.mail-nav-item[data-filter="inbox"]').click()
                    expect(row().get_by_role("button", name="work", exact=True)).to_be_visible()
                else:
                    expect(page.locator("#mail-unread")).to_have_attribute("aria-disabled", "false")
                    expect(row()).not_to_have_class(re.compile(r".*\bunread\b.*"))
                    page.route(base + "/api/mail/flag/*", lambda route: pending.append(route))
                    with split_mail_panes(page):
                        row().locator("[data-flag]").click()
                    wait_one(pending)
                    expect(page.locator("#mail-unread")).to_have_attribute("aria-disabled", "true")
                    page.locator("#mail-unread").focus()
                    page.keyboard.press("Enter")
                    assert state()["seen"]
                    route = pending.pop()
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(response=response)
                    expect(page.locator("#mail-unread")).to_have_attribute("aria-disabled", "false")
                    page.keyboard.press("Enter")
                    expect(row()).to_have_class(re.compile(r".*\bunread\b.*"))
                    assert not state()["seen"]
                assert not errors, errors
                assert not console, console
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
                for route in body + pending:
                    try:
                        route.fulfill(status=503, json={"detail": "owned cleanup"})
                    except Exception:
                        pass
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
