"""Real reminder records; synthetic response failures, clock and visibility signals."""

import json
import os
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        endpoint = api.post(
            "/api/models/endpoint",
            data={
                "name": "reminder fixture",
                "base_url": "http://127.0.0.1:1/v1",
                "provider_adapter": "manual",
            },
        ).json()["id"]
        assert api.patch(
            "/api/models/endpoint/" + endpoint, data={"models": ["reminder-fixture"]}
        ).ok
        assert api.patch(
            "/api/settings",
            data={
                "default_endpoint_id": endpoint,
                "default_model": "reminder-fixture",
                "model_roles": {
                    "aide_chat": {"endpoint_id": endpoint, "model": "reminder-fixture"}
                },
            },
        ).ok
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "daily",
                "retry-cancel-race",
                "retry-cancel-lost",
                "retry-ack-lost",
                "started-message",
                "create-lost",
                "create-rejected",
                "create-busy",
                "discard-retry",
                "load-error",
                "load-empty-retry",
                "load-retry-focus",
                "load-stale",
                "load-cancel-error",
                "cancel-error",
                "cancel-focus",
                "cancel-load",
                "cancel-load-focus",
                "cancel-load-retry",
                "cancel-lost",
                "message-no-session",
                "due-ack-retry",
                "hidden-due",
                "schedule-timezone",
                "schedule-override",
                "schedule-lost",
                "schedule-close",
                "schedule-new-session",
                "schedule-new-draft",
                "slash-rejected",
                "slash-lost",
                "slash-send",
                "slash-changed-command",
            ]:
                configured = "America/Toronto" if case == "schedule-override" else ""
                assert api.patch("/api/settings", data={"timezone": configured}).ok
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="Asia/Tokyo",
                    service_workers="block",
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                errors, console, requests = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        requests.append(request.post_data_json)
                        if request.url == base + "/api/reminders" and request.method == "POST"
                        else None
                    ),
                )
                name = f"owned {case} {width}"
                result = {
                    "scenario_id": "reminders.recovery." + case,
                    "feature_id": "plan.reminders",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                results.append(result)
                held = []

                def fail(route):
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def rejected(route):
                    route.fulfill(
                        status=400,
                        content_type="application/json",
                        body='{"detail":"synthetic invalid request"}',
                    )

                def lost(route):
                    response = route.fetch()
                    assert response.ok, response.text()
                    fail(route)

                def hold(route):
                    response = route.fetch()
                    held.append((route, response))

                def wait_held():
                    for _ in range(100):
                        if held:
                            return
                        page.wait_for_timeout(10)
                    assert held, "request was not held"

                def key(locator):
                    expect(locator).to_be_enabled()
                    locator.focus()
                    page.keyboard.press("Enter")

                def rows():
                    return [r for r in api.get("/api/reminders").json() if r["text"] == name]

                def seed(due=False):
                    saved = api.post(
                        "/api/reminders",
                        data={
                            "text": name,
                            "trigger_at": (
                                datetime.now(UTC) + timedelta(minutes=-1 if due else 2880)
                            ).isoformat(),
                        },
                    )
                    assert saved.ok
                    return saved.json()["id"]

                def fill_panel():
                    page.locator("#reminder-text").fill(name)
                    page.locator("#reminder-time").evaluate('(el)=>el.value="2032-06-10T14:30"')

                def refresh_signal():
                    page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')

                try:
                    aide = case.startswith(("schedule-", "slash-"))
                    if aide:
                        sid = ""
                        if case != "schedule-new-session":
                            sid = api.post(
                                "/api/sessions",
                                data={
                                    "name": "schedule fixture",
                                    "model": "reminder-fixture",
                                    "endpoint_id": endpoint,
                                },
                            ).json()["id"]
                        page.goto(
                            base + "/?view=chat" + ("#" + sid if sid else ""),
                            wait_until="networkidle",
                        )
                        ta = page.locator("#composer-ta")
                        expect(ta).to_be_visible()
                        if width == 390 and not page.locator("body").evaluate(
                            "el=>el.classList.contains('sidebar-hidden')"
                        ):
                            key(page.locator("#sidebar-toggle-btn"))
                        box = ta.bounding_box()
                        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, (
                            "composer clipped"
                        )
                    else:
                        if case == "retry-ack-lost":
                            page.route(
                                base + "/api/reminders/due", lambda route: route.fulfill(json=[])
                            )
                        if case in [
                            "load-error",
                            "load-cancel-error",
                            "cancel-error",
                            "cancel-focus",
                            "cancel-load",
                            "cancel-load-focus",
                            "cancel-load-retry",
                            "cancel-lost",
                        ]:
                            rid = seed()
                        if case in ["load-error", "load-empty-retry", "load-retry-focus"]:
                            page.route(base + "/api/reminders", fail)
                        if case in ["due-ack-retry", "hidden-due"]:
                            rid = seed(due=True)
                            ack = base + "/api/reminders/" + rid + "/ack"
                            if case == "due-ack-retry":
                                page.route(ack, fail)
                            else:
                                context.add_init_script(
                                    'Object.defineProperty(document,"hidden",{configurable:true,get:()=>window._hidden!==false});'
                                )
                        page.goto(base + "/?view=reminders", wait_until="networkidle")
                        expect(page.locator("#reminder-text")).to_be_visible()
                    if case in ["retry-cancel-race", "retry-cancel-lost", "retry-ack-lost"]:
                        if case == "retry-ack-lost":
                            page.clock.set_fixed_time(datetime.now(UTC) - timedelta(days=3))
                        fill_panel()
                        if case == "retry-ack-lost":
                            chosen = (
                                (datetime.now(UTC) - timedelta(hours=1))
                                .astimezone(ZoneInfo("Asia/Tokyo"))
                                .replace(tzinfo=None)
                                .isoformat(timespec="minutes")
                            )
                            page.locator("#reminder-time").evaluate(
                                "(el,value)=>el.value=value", chosen
                            )
                        page.route(base + "/api/reminders", lost)
                        key(page.locator("#reminder-add-btn"))
                        expect(page.locator("#reminder-status")).to_contain_text("retry")
                        page.unroute(base + "/api/reminders")
                        page.evaluate(
                            'import("/static/js/reminders.js?v=243").then(m=>m.loadReminders())'
                        )
                        expect(page.locator("[data-reminder-cancel]")).to_be_visible()
                        holding = {"active": True}
                        page.route(
                            base + "/api/reminders",
                            lambda route: (
                                hold(route)
                                if holding["active"] and route.request.method == "POST"
                                else route.continue_()
                            ),
                        )
                        key(page.locator("#reminder-add-btn"))
                        wait_held()
                        rid = rows()[0]["id"]
                        if case == "retry-ack-lost":
                            ack_url = base + "/api/reminders/" + rid + "/ack"
                            page.route(ack_url, lost)
                            page.unroute(base + "/api/reminders/due")
                            with page.expect_response(ack_url) as acked:
                                refresh_signal()
                            assert acked.value.status == 503
                            expect(page.locator(".toast.success")).to_contain_text(
                                "reminder: " + name
                            )
                        else:
                            if case == "retry-cancel-lost":
                                page.route(base + "/api/reminders/" + rid, lost)
                            key(page.locator("[data-reminder-cancel]"))
                            if case == "retry-cancel-lost":
                                expect(page.locator(".toast.error").last).to_contain_text(
                                    "synthetic unavailable"
                                )
                            else:
                                expect(page.locator("[data-reminder-cancel]")).to_have_count(0)
                        assert rows() == []
                        holding["active"] = False
                        pending, held = held[:], []
                        for route, response in pending:
                            route.fulfill(response=response)
                        expect(page.locator("#reminder-add-btn")).to_be_enabled()
                        if case == "retry-ack-lost":
                            expect(page.locator("#reminder-text")).to_have_value("")
                            expect(page.locator(".toast.success").last).to_contain_text(
                                "already delivered"
                            )
                        else:
                            expect(page.locator("#reminder-status")).to_contain_text("cancelled")
                            assert not page.locator(".toast.success").count()
                        expect(page.locator("#reminder-list")).not_to_contain_text(name)
                        assert len(requests) == 3 and requests[0] == requests[1] == requests[2]
                    elif case == "started-message":
                        # A controlled persisted job claim, without contacting any model.
                        import sys

                        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                        from core.database import Reminder, SessionLocal

                        sid = api.post(
                            "/api/sessions",
                            data={
                                "name": "started fixture",
                                "model": "reminder-fixture",
                                "endpoint_id": endpoint,
                            },
                        ).json()["id"]
                        saved = api.post(
                            "/api/reminders",
                            data={
                                "text": name,
                                "trigger_at": "2032-06-10T14:30:00Z",
                                "type": "message",
                                "session_id": sid,
                            },
                        )
                        assert saved.ok
                        rid = saved.json()["id"]
                        with SessionLocal() as db:
                            db.get(Reminder, rid).notified = True
                            db.commit()
                        page.evaluate(
                            'import("/static/js/reminders.js?v=243").then(m=>m.loadReminders())'
                        )
                        expect(page.locator("#reminder-list")).to_contain_text("delivery started")
                        key(page.locator("[data-reminder-cancel]"))
                        expect(page.locator(".toast.error")).to_contain_text("already started")
                        assert rows()[0]["id"] == rid
                        with SessionLocal() as db:
                            db.get(Reminder, rid).fired = True
                            db.commit()
                    elif case in [
                        "daily",
                        "create-lost",
                        "create-rejected",
                        "create-busy",
                        "discard-retry",
                        "message-no-session",
                    ]:
                        fill_panel()
                        if case == "message-no-session":
                            page.locator("#reminder-type-select").evaluate(
                                '(el)=>el.value="message"'
                            )
                        if case in ["create-lost", "discard-retry"]:
                            page.route(
                                base + "/api/reminders",
                                lambda route: (
                                    lost(route)
                                    if route.request.method == "POST"
                                    else route.continue_()
                                ),
                            )
                        if case == "create-rejected":
                            page.route(
                                base + "/api/reminders",
                                lambda route: (
                                    rejected(route)
                                    if route.request.method == "POST"
                                    else route.continue_()
                                ),
                            )
                        if case == "create-busy":
                            page.route(
                                base + "/api/reminders",
                                lambda route: (
                                    hold(route)
                                    if route.request.method == "POST"
                                    else route.continue_()
                                ),
                            )
                        key(page.locator("#reminder-add-btn"))
                        if case == "create-busy":
                            wait_held()
                            expect(page.locator("#reminder-add-btn")).to_be_disabled()
                            page.keyboard.press("Enter")
                            assert len(requests) == 1
                            moved = page.locator('#plan-tabs [data-group-section="tasks"]')
                            moved.focus()
                            for route, response in held:
                                route.fulfill(response=response)
                            held.clear()
                            expect(page.locator("#reminder-add-btn")).to_be_enabled()
                            expect(moved).to_be_focused()
                        if case in [
                            "create-lost",
                            "create-rejected",
                            "discard-retry",
                            "message-no-session",
                        ]:
                            expect(page.locator(".toast.error")).to_be_visible()
                            page.screenshot(
                                path=str(output / f"{case}-{width}-error.png"), full_page=True
                            )
                            expect(page.locator("#reminder-text")).to_have_value(name)
                            assert not page.locator(".toast.success").count()
                            expect(page.locator("#reminder-add-btn")).to_be_focused()
                            if case == "message-no-session":
                                assert rows() == []
                            elif case == "discard-retry":
                                key(page.locator("#reminder-discard"))
                                expect(page.locator("[role=alertdialog]")).to_contain_text(
                                    "may already be saved"
                                )
                                key(page.locator("[data-dialog-cancel]"))
                                expect(page.locator("#reminder-discard")).to_be_visible()
                                key(page.locator("#reminder-discard"))
                                key(page.locator("[data-dialog-confirm]"))
                                expect(page.locator("#reminder-text")).to_have_value("")
                                assert len(rows()) == 1
                            else:
                                if case == "create-lost":
                                    expect(page.locator("#reminder-text")).to_be_disabled()
                                else:
                                    expect(page.locator("#reminder-text")).to_be_enabled()
                                    assert rows() == []
                                page.unroute(base + "/api/reminders")
                                key(page.locator("#reminder-add-btn"))
                        if case not in ["message-no-session", "discard-retry"]:
                            expect(page.locator("#reminder-text")).to_have_value("")
                            assert len(rows()) == 1
                            assert rows()[0]["trigger_at"] == "2032-06-10T05:30:00"
                            if case == "create-lost":
                                assert requests[0] == requests[1]
                            page.reload(wait_until="networkidle")
                            expect(page.locator("#reminder-list")).to_contain_text(name)
                    elif case in ["load-error", "load-empty-retry", "load-retry-focus"]:
                        expect(page.locator("#reminder-list")).to_contain_text(
                            "could not load reminders"
                        )
                        expect(page.locator("#reminder-list")).not_to_contain_text("no reminders")
                        key(page.locator("[data-reminder-retry]"))
                        expect(page.locator("[data-reminder-retry]")).to_be_focused()
                        page.unroute(base + "/api/reminders")
                        if case == "load-retry-focus":
                            page.route(base + "/api/reminders", hold)
                            key(page.locator("[data-reminder-retry]"))
                            wait_held()
                            page.locator("#reminder-text").focus()
                            pending, held = held[:], []
                            for route, _ in pending:
                                fail(route)
                            expect(page.locator("[data-reminder-retry]")).to_be_visible()
                            expect(page.locator("#reminder-text")).to_be_focused()
                        else:
                            key(page.locator("[data-reminder-retry]"))
                            expect(page.locator("#plan-view > .specialist-state")).to_be_hidden()
                            if case == "load-error":
                                expect(page.locator("#reminder-list")).to_contain_text(name)
                                expect(page.locator("[data-reminder-cancel]")).to_be_focused()
                            else:
                                expect(page.locator("#reminder-list")).to_contain_text(
                                    "no reminders"
                                )
                                expect(page.locator("#reminder-text")).to_be_focused()
                    elif case == "load-stale":
                        page.route(
                            base + "/api/reminders",
                            lambda route: (
                                hold(route) if route.request.method == "GET" else route.continue_()
                            ),
                        )
                        page.evaluate(
                            'void(window._oldReminderLoad=import("/static/js/reminders.js?v=243").then(m=>m.loadReminders()))'
                        )
                        wait_held()
                        fill_panel()
                        key(page.locator("#reminder-add-btn"))
                        expect(page.locator("#reminder-text")).to_have_value("")
                        for route, response in held:
                            route.fulfill(response=response)
                        held.clear()
                        page.evaluate("window._oldReminderLoad")
                        expect(page.locator("#reminder-list")).to_contain_text(name)
                    elif case == "load-cancel-error":
                        page.route(base + "/api/reminders", hold)
                        page.evaluate(
                            'void(window._oldReminderLoad=import("/static/js/reminders.js?v=243").then(m=>m.loadReminders()))'
                        )
                        wait_held()
                        expect(page.locator("#reminder-list")).to_contain_text("loading reminders")
                        page.route(base + "/api/reminders/" + rid, fail)
                        button = page.locator("[data-reminder-cancel]")
                        key(button)
                        expect(page.locator(".toast.error")).to_be_visible()
                        pending, held = held[:], []
                        for route, response in pending:
                            route.fulfill(response=response)
                        page.evaluate("window._oldReminderLoad")
                        expect(page.locator("#reminder-list")).not_to_contain_text(
                            "loading reminders"
                        )
                        expect(page.locator("#reminder-list")).to_contain_text(name)
                        expect(button).to_be_enabled()
                        expect(button).to_be_focused()
                        assert any(row["id"] == rid for row in rows())
                    elif case == "cancel-load-retry":
                        page.route(
                            base + "/api/reminders/" + rid,
                            lambda route: held.append((route, None)),
                        )
                        key(page.locator("[data-reminder-cancel]"))
                        wait_held()
                        page.route(base + "/api/reminders", fail)
                        page.evaluate(
                            'import("/static/js/reminders.js?v=243").then(m=>m.loadReminders()).catch(()=>{})'
                        )
                        retry = page.locator("[data-reminder-retry]")
                        expect(retry).to_be_visible()
                        retry.focus()
                        pending, held = held[:], []
                        for route, _ in pending:
                            fail(route)
                        expect(page.locator(".toast.error")).to_be_visible()
                        expect(page.locator("[data-reminder-cancel]")).to_be_enabled()
                        expect(retry).to_be_focused()
                        assert any(row["id"] == rid for row in rows())
                    elif case in ["cancel-load", "cancel-load-focus"]:
                        delete_url = base + "/api/reminders/" + rid
                        page.route(delete_url, lambda route: held.append((route, None)))
                        button = page.locator("[data-reminder-cancel]")
                        key(button)
                        wait_held()
                        expect(button).to_be_disabled()
                        page.route(base + "/api/reminders", hold)
                        page.evaluate(
                            'void(window._oldReminderLoad=import("/static/js/reminders.js?v=243").then(m=>m.loadReminders()))'
                        )
                        expect(page.locator("#reminder-list")).to_contain_text("loading reminders")
                        expect(button).to_be_disabled()
                        if case == "cancel-load-focus":
                            page.locator("#reminder-text").focus()
                        deletes = [
                            (route, response)
                            for route, response in held
                            if route.request.method == "DELETE"
                        ]
                        held = [
                            (route, response)
                            for route, response in held
                            if route.request.method != "DELETE"
                        ]
                        assert len(deletes) == 1
                        for route, _ in deletes:
                            fail(route)
                        expect(page.locator(".toast.error")).to_be_visible()
                        expect(button).to_be_enabled()
                        target = (
                            page.locator("#reminder-text")
                            if case == "cancel-load-focus"
                            else button
                        )
                        expect(target).to_be_focused()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert held
                        pending, held = held[:], []
                        for route, response in pending:
                            route.fulfill(response=response)
                        page.evaluate("window._oldReminderLoad")
                        expect(target).to_be_focused()
                        assert any(row["id"] == rid for row in rows())
                    elif case == "cancel-focus":
                        page.route(
                            base + "/api/reminders/" + rid,
                            lambda route: held.append((route, None)),
                        )
                        key(page.locator("[data-reminder-cancel]"))
                        wait_held()
                        page.locator("#reminder-text").focus()
                        pending, held = held[:], []
                        for route, _ in pending:
                            fail(route)
                        expect(page.locator(".toast.error")).to_be_visible()
                        expect(page.locator("[data-reminder-cancel]")).to_be_enabled()
                        expect(page.locator("#reminder-text")).to_be_focused()
                        assert any(row["id"] == rid for row in rows())
                    elif case.startswith("cancel-"):
                        url = base + "/api/reminders/" + rid
                        page.route(url, fail if case == "cancel-error" else lost)
                        key(page.locator("[data-reminder-cancel]"))
                        expect(page.locator(".toast.error")).to_be_visible()
                        expect(page.locator("#reminder-list")).to_contain_text(name)
                        assert bool(rows()) == (case == "cancel-error")
                        page.unroute(url)
                        key(page.locator("[data-reminder-cancel]"))
                        expect(page.locator("#reminder-list")).not_to_contain_text(name)
                        assert not rows()
                    elif case in ["due-ack-retry", "hidden-due"]:
                        if case == "hidden-due":
                            page.wait_for_timeout(2200)
                            assert any(r["id"] == rid for r in api.get("/api/reminders/due").json())
                            assert not page.locator(".toast.success").count()
                            page.evaluate("window._hidden=false")
                            refresh_signal()
                        else:
                            expect(page.locator(".toast.success")).to_contain_text(name)
                            assert any(r["id"] == rid for r in api.get("/api/reminders/due").json())
                            page.unroute(ack)
                            refresh_signal()
                        for _ in range(100):
                            if not any(
                                r["id"] == rid for r in api.get("/api/reminders/due").json()
                            ):
                                break
                            page.wait_for_timeout(20)
                        assert not rows(), "displayed reminder still pending after acknowledgment"
                        page.reload(wait_until="networkidle")
                        assert not rows()
                    elif case.startswith("schedule-"):
                        ta.fill(name)
                        page.locator("#send-btn").focus()
                        page.keyboard.press("Shift+F10")
                        expect(page.locator("#schedule-when")).to_have_attribute(
                            "data-dp-ready", "1"
                        )
                        page.locator("#schedule-when").evaluate('(el)=>el.value="2032-06-10T14:30"')
                        if case in ["schedule-lost", "schedule-close"]:
                            page.route(base + "/api/reminders", lost)
                        if case == "schedule-new-draft":
                            page.route(base + "/api/reminders", hold)
                        key(page.locator("#schedule-go"))
                        if case == "schedule-new-draft":
                            wait_held()
                            ta.fill("a newer draft")
                            for route, response in held:
                                route.fulfill(response=response)
                            held.clear()
                        if case in ["schedule-lost", "schedule-close"]:
                            expect(page.locator("#schedule-status")).to_contain_text("retry")
                            expect(ta).to_have_value(name)
                            page.screenshot(
                                path=str(output / f"{case}-{width}-error.png"), full_page=True
                            )
                            if case == "schedule-close":
                                key(page.locator("#schedule-cancel"))
                                expect(page.locator("[role=alertdialog]")).to_contain_text(
                                    "may already be scheduled"
                                )
                                key(page.locator("[data-dialog-cancel]"))
                            page.unroute(base + "/api/reminders")
                            key(page.locator("#schedule-go"))
                        expect(page.locator(".schedule-pop")).to_have_count(0)
                        expect(ta).to_have_value(
                            "a newer draft" if case == "schedule-new-draft" else ""
                        )
                        assert len(rows()) == 1
                        assert rows()[0]["trigger_at"] == (
                            "2032-06-10T18:30:00" if configured else "2032-06-10T05:30:00"
                        )
                        assert rows()[0]["session_id"]
                        if case in ["schedule-lost", "schedule-close"]:
                            assert requests[0] == requests[1]
                    else:
                        command = (
                            ("/send" if case == "slash-send" else "/remind") + " in 2h " + name
                        )
                        ta.fill(command)
                        if case == "slash-rejected":
                            page.route(base + "/api/reminders", rejected)
                        elif case in ["slash-lost", "slash-changed-command"]:
                            page.route(base + "/api/reminders", lost)
                        ta.press("Enter")
                        if case != "slash-send":
                            expect(page.locator(".toast.error")).to_be_visible()
                            expect(ta).to_have_value(command)
                            assert not page.locator(".toast.success").count()
                            page.unroute(base + "/api/reminders")
                            if case == "slash-changed-command":
                                ta.fill(command + " changed")
                                ta.press("Enter")
                                expect(page.locator("[role=alertdialog]")).to_contain_text(
                                    "previous reminder"
                                )
                                key(page.locator("[data-dialog-cancel]"))
                                assert len(requests) == 1
                                ta.fill(command)
                            ta.press("Enter")
                        expect(ta).to_have_value("")
                        assert len(rows()) == 1
                        if case in ["slash-lost", "slash-changed-command"]:
                            assert requests[0] == requests[1]
                        if case == "slash-send":
                            assert rows()[0]["type"] == "message" and rows()[0]["session_id"] == sid
                    assert not errors, errors
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
                        "horizontal overflow"
                    )
                    result["status"] = "passed"
                except Exception:
                    result["error"] = traceback.format_exc()
                finally:
                    for route, response in held:
                        route.fulfill(response=response)
                    result["console_errors"] = console
                    result["page_errors"] = errors
                    page.screenshot(path=str(output / f"{case}-{width}.png"), full_page=True)
                    for row in api.get("/api/reminders").json():
                        assert api.delete("/api/reminders/" + row["id"]).ok
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
    print(
        json.dumps(
            {"scenarios": len(results), "failed": [r for r in results if r["status"] != "passed"]},
            indent=2,
        )
    )
    return int(any(r["status"] != "passed" for r in results))


if __name__ == "__main__":
    raise SystemExit(run())
