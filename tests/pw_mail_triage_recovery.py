"""Owned triage workflows; live local writes, controlled provider bodies/archive ack."""

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
actions = ["flag", "label", "mute", "snooze", "unread", "vip", "archive"]
cases = [
    mode + "-" + action for mode in ["success", "lost", "offline", "reject"] for action in actions
] + ["folder-flag", "late-unread", "double-flag", "negative-flag"]
if len(sys.argv) > 1:
    cases = [c for c in cases if c in sys.argv[1:]]
assert cases
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    aid = account["id"]
    assert api.post("/api/setup/dismiss").ok
    from core.database import CachedMessage, SessionLocal

    def reset():
        with SessionLocal() as db:
            db.query(CachedMessage).filter_by(account_id=aid).delete()
            for uid, folder, title in [
                ("701", "INBOX", "Receipt 中文"),
                ("702", "INBOX", "Other message"),
                ("701", "Work", "Receipt in work"),
            ]:
                db.add(
                    CachedMessage(
                        account_id=aid,
                        folder=folder,
                        uid=uid,
                        sender="Receipts <receipts@example.invalid>",
                        subject=title,
                        date="2026-09-25",
                        date_ts=time.time() - int(uid),
                        seen=True,
                    )
                )
            db.commit()
        assert api.post(
            "/api/mail/vips", data={"email": "receipts@example.invalid", "add": False}
        ).ok

    def state(folder="INBOX"):
        with SessionLocal() as db:
            r = (
                db.query(CachedMessage)
                .filter_by(account_id=aid, folder=folder, uid="701")
                .one_or_none()
            )
            return (
                None
                if r is None
                else {
                    "seen": r.seen,
                    "flagged": r.flagged,
                    "muted": r.muted,
                    "until": r.snoozed_until,
                    "labels": r.labels,
                }
            )

    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in cases:
            reset()
            mode, action = case.split("-", 1)
            held = []
            writes = []
            errors = []
            console = []
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="allow" if mode == "offline" else "block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(7000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: console.append(e.text) if e.type == "error" else None)
            result = {
                "scenario_id": "inbox.triage." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)
            endpoint_action = {"label": "labels", "unread": "read", "vip": "vips"}.get(
                action, action
            )
            endpoint = (
                base + "/api/mail/" + endpoint_action + ("" if action == "vip" else "/" + aid)
            )
            folder = "Work" if mode == "folder" else "INBOX"

            def row():
                return page.locator(
                    f'.mail-row[data-aid="{aid}"][data-uid="701"][data-folder="{folder}"]'
                )

            def message(route):
                q = parse_qs(urlparse(route.request.url).query)
                uid = q["uid"][0]
                route.fulfill(
                    json={
                        "uid": uid,
                        "from": "Receipts <receipts@example.invalid>",
                        "to": "me@example.invalid",
                        "subject": "read " + uid,
                        "date": "2026-09-25",
                        "text": "body " + uid,
                        "html": "",
                    }
                )

            def archive(route):
                payload = route.request.post_data_json
                assert payload["require_server"] is True
                with SessionLocal() as db:
                    n = (
                        db.query(CachedMessage)
                        .filter_by(account_id=aid, folder=payload["folder"], uid=payload["uid"])
                        .delete()
                    )
                    db.commit()
                return {"archived": n, "moved_on_server": True}

            def write(route):
                if route.request.method != "POST":
                    return route.continue_()
                if action == "unread" and parse_qs(urlparse(route.request.url).query).get(
                    "uid"
                ) != ["701"]:
                    return route.continue_()
                writes.append({"url": route.request.url, "body": route.request.post_data_json})
                if mode == "negative":
                    return route.fulfill(
                        json={"ok": False, "flagged": True, "error": "owned missing row"}
                    )
                if mode == "reject":
                    return route.fulfill(status=503, json={"detail": "owned rejected write"})
                response = archive(route) if action == "archive" else route.fetch()
                if action != "archive":
                    assert response.ok, response.text()
                if mode in {"late", "double"}:
                    held.append((route, response))
                    return
                if mode == "lost":
                    route.fulfill(status=503, json={"detail": "owned lost reply"})
                elif action == "archive":
                    route.fulfill(json=response)
                else:
                    route.fulfill(response=response)

            try:
                page.route(base + "/api/mail/message/*", message)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.wait_for_load_state("networkidle")
                if mode == "offline":
                    page.wait_for_function("()=>navigator.serviceWorker.controller", timeout=15000)
                if mode == "folder":
                    page.locator("#mail-search").fill("Receipt")
                    page.locator("#mail-search").press("Enter")
                    page.wait_for_load_state("networkidle")
                    expect(row()).to_be_visible()
                if action in {"unread", "vip"}:
                    row().locator(".mail-open").click()
                    expect(page.locator("#mail-unread")).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    # The automatic read must settle before the deliberate triage
                    # action. Network idleness alone does not prove pane readiness.
                    expect(page.locator("#mail-" + action)).to_have_attribute(
                        "aria-disabled", "false"
                    )
                if width <= 1100 and action in {"unread", "vip"}:
                    expect(row()).to_be_hidden()
                    expect(row()).to_have_count(1)
                else:
                    expect(row()).to_be_visible()
                expect(page.locator("#mail-list")).to_have_attribute("aria-busy", "false")
                if mode != "offline":
                    page.route(endpoint + "*", write)
                page.evaluate(
                    """url=>{const fetch=window.fetch;window.__triageDone=false;window.fetch=async(...a)=>{const match=new URL(String(a[0]),location.href).href.startsWith(url)&&a[1]?.method==='POST'&&(!new URL(String(a[0]),location.href).searchParams.has('uid')||new URL(String(a[0]),location.href).searchParams.get('uid')==='701');try{const r=await fetch(...a);if(match){const json=r.json.bind(r);r.json=async()=>{try{return await json()}finally{setTimeout(()=>window.__triageDone=true,0)}}}return r}catch(error){if(match)setTimeout(()=>window.__triageDone=true,0);throw error}}}""",
                    endpoint,
                )
                if mode == "offline":
                    context.set_offline(True)
                if action == "label":
                    row().locator("[data-label]").click()
                    page.get_by_role("dialog").locator("input").fill("work")
                    page.get_by_role("dialog").get_by_role("button", name="ok", exact=True).click()
                else:
                    btn = (
                        page.locator("#mail-" + action)
                        if action in {"unread", "vip"}
                        else row().locator("[data-" + action + "]")
                    )
                    btn.focus()
                    expect(btn).to_be_focused()
                    page.keyboard.press("Enter")
                if mode in {"late", "double"}:
                    deadline = time.monotonic() + 5
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(30)
                    assert len(held) == 1
                    if mode == "late":
                        return_to_mail_list(page)
                        page.locator('.mail-row[data-uid="702"] .mail-open').click()
                        expect(page.locator(".mail-reader-subject")).to_have_text("read 702")
                        page.wait_for_timeout(100)
                    else:
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(100)
                        assert len(writes) == 1
                    route, response = held.pop()
                    route.fulfill(response=response)
                page.wait_for_function("window.__triageDone===true")
                page.wait_for_timeout(50)
                if mode in {"offline", "reject"}:
                    if mode == "offline":
                        queue = page.evaluate(
                            """()=>new Promise((resolve,reject)=>{const c=new MessageChannel();const t=setTimeout(()=>reject(new Error('worker timeout')),5000);c.port1.onmessage=e=>{clearTimeout(t);resolve(e.data)};navigator.serviceWorker.controller.postMessage({type:'alles-outbox-list'},[c.port2])})"""
                        )
                        assert queue["ok"] and queue["items"] == [], queue
                    assert state() == {
                        "seen": True,
                        "flagged": False,
                        "muted": False,
                        "until": "",
                        "labels": "",
                    }
                    if width <= 1100 and action in {"unread", "vip"}:
                        expect(row()).to_be_hidden()
                        expect(row()).to_have_count(1)
                    else:
                        expect(row()).to_be_visible()
                    if action == "flag":
                        assert (
                            not row()
                            .locator("[data-flag]")
                            .evaluate("e=>e.classList.contains('on')")
                        )
                    if action == "label":
                        expect(row().locator('[data-labelfilter="work"]')).to_have_count(0)
                    if action == "unread":
                        expect(row()).not_to_have_class(re.compile(r".*\bunread\b.*"))
                    if action == "vip":
                        expect(page.locator("#mail-vip")).not_to_have_class(
                            re.compile(r".*\bon\b.*")
                        )
                elif mode == "negative":
                    assert not state()["flagged"]
                    assert (
                        not row().locator("[data-flag]").evaluate("e=>e.classList.contains('on')")
                    )
                else:
                    saved = state(folder)
                    if action == "flag":
                        assert saved["flagged"]
                    elif action == "label":
                        assert saved["labels"] == "work"
                    elif action == "mute":
                        assert saved["muted"]
                    elif action == "snooze":
                        assert saved["until"] and saved["until"].startswith("20")
                    elif action == "unread":
                        assert not saved["seen"]
                    elif action == "vip":
                        assert (
                            "receipts@example.invalid" in api.get("/api/mail/vips").json()["vips"]
                        )
                    else:
                        assert saved is None
                    if mode == "folder":
                        assert not state("INBOX")["flagged"]
                    if mode == "late":
                        expect(page.locator(".mail-reader-subject")).to_have_text("read 702")
                    if mode == "lost":
                        if action in {"archive", "mute", "snooze"}:
                            expect(row()).to_be_visible()
                        elif action == "flag":
                            assert (
                                not row()
                                .locator("[data-flag]")
                                .evaluate("e=>e.classList.contains('on')")
                            )
                        page.locator("#mail-refresh-btn").click()
                        page.wait_for_load_state("networkidle")
                    if action in {"archive", "mute", "snooze"}:
                        expect(row()).to_have_count(0)
                    elif action == "flag":
                        expect(row().locator("[data-flag]")).to_have_class("mail-flag on")
                    elif action == "label":
                        chip = row().get_by_role("button", name="work", exact=True)
                        expect(chip).to_be_visible()
                        chip.focus()
                        page.keyboard.press("Tab")
                        page.keyboard.press("Shift+Tab")
                        expect(chip).to_be_focused()
                        assert chip.evaluate(
                            """b=>{const s=getComputedStyle(b);const r=b.getBoundingClientRect();const p=b.parentElement.getBoundingClientRect();const outer=Math.max(0,parseFloat(s.outlineOffset)+parseFloat(s.outlineWidth));return b.matches(':focus-visible')&&r.top-outer>=p.top&&r.bottom+outer<=p.bottom}"""
                        )
                        page.keyboard.press("Enter")
                        expect(page.locator(".mail-row[data-aid]")).to_have_count(1)
                        expect(row()).to_be_visible()
                    elif action == "unread":
                        expect(row()).to_have_class(re.compile(r".*\bunread\b.*"))
                    elif mode != "lost":
                        expect(page.locator("#mail-vip")).to_have_class("btn on")
                if width <= 1100 and action in {"unread", "vip"}:
                    return_to_mail_list(page)
                    expect(row()).to_be_visible()
                assert not errors, errors
                assert not [
                    line
                    for line in console
                    if not any(
                        expected in line
                        for expected in ["503", "ERR_INTERNET_DISCONNECTED", "Failed to fetch"]
                    )
                ], console
                assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
                sizes = page.locator(
                    ".mail-row-acts button, .mail-label-chip, #mail-unread, #mail-vip"
                ).evaluate_all(
                    "buttons=>buttons.filter(b=>b.getClientRects().length).map(b=>{const r=b.getBoundingClientRect();return [r.width,r.height]})"
                )
                assert all(w >= 44 and h >= 44 for w, h in sizes), sizes
                result.update(
                    status="passed", writes=len(writes), console_errors=console, page_errors=errors
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
                for route, response in held:
                    try:
                        route.fulfill(response=response)
                    except Exception:
                        pass
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(r["status"] != "passed" for r in results))
