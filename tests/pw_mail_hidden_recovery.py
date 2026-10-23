"""Hidden-mail restoration through the real local API, including uncertain writes."""

import json
import os
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
cases = [
    mode + "-" + action
    for mode in ["success", "lost", "reject", "offline", "reload", "folder"]
    for action in ["mute", "snooze"]
] + ["timezone-snooze", "both-mute", "cross-mute", "cross-snooze"]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    aid = account["id"]
    assert api.post("/api/setup/dismiss").ok
    from core.database import CachedMessage, SessionLocal

    def state(folder="INBOX"):
        with SessionLocal() as db:
            r = db.query(CachedMessage).filter_by(account_id=aid, folder=folder, uid="701").one()
            return {"muted": r.muted, "until": r.snoozed_until}

    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            mode, action = case.split("-")
            folder = "Work" if mode == "folder" else "INBOX"
            hidden = "muted" if action == "mute" else "snoozed"
            with SessionLocal() as db:
                db.query(CachedMessage).filter_by(account_id=aid).delete()
                for f, title in [("INBOX", "Receipt"), ("Work", "Project in work")]:
                    db.add(
                        CachedMessage(
                            account_id=aid,
                            folder=f,
                            uid="701",
                            subject=title,
                            sender="sender@example.invalid",
                            date="2026-09-25",
                            date_ts=time.time(),
                            seen=True,
                            muted=action == "mute" and not (mode == "success" and f == "INBOX"),
                            snoozed_until=(
                                (datetime.now(UTC) + timedelta(hours=1))
                                .replace(tzinfo=None)
                                .isoformat()
                                if mode == "timezone"
                                else "2035-01-01T12:00:00"
                            )
                            if (action == "snooze" or mode == "both")
                            and not (mode == "success" and f == "INBOX")
                            else "",
                        )
                    )
                db.commit()
            context = browser.new_context(
                timezone_id="Asia/Tokyo" if mode == "timezone" else "America/Toronto",
                viewport={"width": width, "height": 900},
                service_workers="allow" if mode == "offline" else "block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            errors = []
            console = []
            writes = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.hidden." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)
            endpoint = base + "/api/mail/" + action + "/" + aid

            def row():
                return page.locator(
                    f'.mail-row[data-aid="{aid}"][data-folder="{folder}"][data-uid="701"]'
                )

            def restore():
                button = row().get_by_role(
                    "button", name="unmute thread" if action == "mute" else "end snooze", exact=True
                )
                button.focus()
                page.keyboard.press("Enter")

            def handler(route):
                writes.append(route.request.post_data_json)
                assert (
                    writes[-1].get("muted") is False
                    if action == "mute"
                    else writes[-1]["until"] == ""
                )
                if len(writes) == 1 and mode == "reject":
                    return route.fulfill(status=503, json={"detail": "owned rejected restore"})
                response = route.fetch()
                assert response.ok
                if len(writes) == 1 and mode == "lost":
                    route.fulfill(status=503, json={"detail": "owned lost restore"})
                else:
                    route.fulfill(response=response)

            try:
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if mode == "success":
                    expect(row()).to_be_visible()
                    row().locator("[data-" + action + "]").focus()
                    page.keyboard.press("Enter")
                    expect(row()).to_have_count(0)
                    saved = state()
                    assert saved["muted"] if action == "mute" else saved["until"]
                nav = page.locator(f'.mail-nav-item[data-filter="{hidden}"]')
                nav.click()
                expect(row()).to_be_visible()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if mode == "reload":
                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    nav.click()
                    expect(row()).to_be_visible()
                    expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if mode == "cross":
                    added = "snooze" if action == "mute" else "mute"
                    row().locator("[data-" + added + "]").click()
                    expect(
                        page.get_by_text(
                            "snoozed until tomorrow" if added == "snooze" else "thread muted",
                            exact=True,
                        )
                    ).to_be_visible()
                    assert state()["muted"] and state()["until"]
                    expect(row()).to_be_visible()
                    row().get_by_role(
                        "button",
                        name="end snooze" if added == "snooze" else "unmute thread",
                        exact=True,
                    ).click()
                    expect(
                        page.get_by_text(
                            "snooze ended" if added == "snooze" else "thread unmuted", exact=True
                        )
                    ).to_be_visible()
                    expect(row()).to_be_visible()
                    stored = state()
                    assert (
                        stored["muted"] and not stored["until"]
                        if action == "mute"
                        else stored["until"] and not stored["muted"]
                    )
                if mode == "offline":
                    page.wait_for_function("()=>navigator.serviceWorker.controller")
                    context.set_offline(True)
                else:
                    page.route(endpoint, handler)
                restore()
                if mode in ["lost", "reject", "offline"]:
                    failure = (
                        "could not confirm unmute"
                        if action == "mute"
                        else "could not confirm ending snooze"
                    )
                    expect(page.get_by_text(failure, exact=False)).to_be_visible()
                    expect(row()).to_be_visible()
                    stored = state(folder)
                    expected_hidden = mode != "lost"
                    assert (
                        stored["muted"] == expected_hidden
                        if action == "mute"
                        else bool(stored["until"]) == expected_hidden
                    )
                    if mode == "offline":
                        queue = page.evaluate(
                            """()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2])})"""
                        )
                        assert queue["ok"] and queue["items"] == []
                        context.set_offline(False)
                    restore()
                expect(row()).to_have_count(0)
                stored = state(folder)
                assert not stored["muted"] if action == "mute" else stored["until"] == ""
                other = state("INBOX" if folder == "Work" else "Work")
                assert other["muted"] if action == "mute" else other["until"]
                if mode == "both":
                    page.locator('.mail-nav-item[data-filter="inbox"]').click()
                    expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                    expect(row()).to_have_count(0)
                    page.locator('.mail-nav-item[data-filter="snoozed"]').click()
                    expect(row()).to_be_visible()
                    row().get_by_role("button", name="end snooze", exact=True).click()
                    expect(row()).to_have_count(0)
                    assert state()["until"] == ""
                page.locator('.mail-nav-item[data-filter="inbox"]').click()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if folder == "INBOX":
                    expect(row()).to_be_visible()
                else:
                    expect(row()).to_have_count(0)
                    page.locator("#mail-search").fill("Project in work")
                    page.locator("#mail-search").press("Enter")
                    expect(row()).to_be_visible()
                assert not errors, errors
                assert not [
                    line
                    for line in console
                    if not any(
                        x in line for x in ["503", "ERR_INTERNET_DISCONNECTED", "Failed to fetch"]
                    )
                ], console
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
                sizes = page.locator(".mail-row-acts button,.mail-nav-item").evaluate_all(
                    "buttons=>buttons.filter(b=>b.getClientRects().length).map(b=>{const r=b.getBoundingClientRect();return [r.width,r.height]})"
                )
                assert all(w >= 44 and h >= 44 for w, h in sizes), sizes
                result.update(
                    status="passed", writes=writes, page_errors=errors, console_errors=console
                )
            except Exception as e:
                result.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    writes=writes,
                    page_errors=errors,
                    console_errors=console,
                )
            finally:
                context.set_offline(False)
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
