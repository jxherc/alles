"""Countdown mutation, draft ownership, and read recovery on isolated local storage."""

import json
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy

BASE = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, theme in [(1440, "dark"), (390, "light")]:
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            has_touch=width == 390,
            service_workers="block",
            reduced_motion="reduce",
            timezone_id="UTC",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(6000)
        errors, console, external = [], [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)

        def boundary(route):
            if urlsplit(route.request.url).netloc == urlsplit(BASE).netloc:
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", boundary)
        context.route_web_socket("**/*", lambda s: s.close())
        api = context.request
        api.post(BASE + "/api/setup/dismiss")
        assert api.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok

        def click(target):
            target.tap() if width == 390 else target.click()

        def shot(name):
            page.screenshot(path=str(OUT / f"{width}-{name}.png"))

        def record(name, passed=True, **details):
            rows.append(
                {
                    "scenario_id": name,
                    "profile": f"{width}-{theme}",
                    "status": "passed" if passed else "failed",
                    **details,
                }
            )
            (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2))

        def wait_count(items, number):
            for _ in range(100):
                if len(items) >= number:
                    return
                page.wait_for_timeout(10)
            assert len(items) >= number

        try:
            today = date.today()
            seeded = []
            for suffix, offset in [("today", 0), ("trip", 3), ("since", -5)]:
                r = api.post(
                    BASE + "/api/days",
                    data={
                        "name": f"{suffix} {width}",
                        "date": str(today + timedelta(days=offset)),
                        "notify_days": -1,
                    },
                )
                assert r.ok
                seeded.append(r.json())
            held = []
            day_state = {"mode": "load-hold", "edit_fail": False}

            def days_route(route):
                path = urlsplit(route.request.url).path
                method = route.request.method
                mode = day_state["mode"]
                if method == "GET" and path == "/api/days" and mode == "load-hold":
                    held.append(route)
                    return
                if method == "GET" and path == "/api/days" and mode == "load-fail":
                    route.fulfill(
                        status=503, json={"detail": "synthetic countdown list unavailable"}
                    )
                    return
                if method == "POST" and path == "/api/days" and mode == "create-fail":
                    route.fulfill(status=503, json={"detail": "synthetic countdown create failed"})
                    return
                if method == "POST" and path == "/api/days" and mode == "create-hold":
                    held.append(route)
                    return
                if method == "PATCH" and mode == "edit-hold":
                    held.append(route)
                    return
                if method == "DELETE" and mode == "delete-fail":
                    route.fulfill(status=503, json={"detail": "synthetic deletion unavailable"})
                    return
                if method == "DELETE" and mode == "delete-malformed":
                    route.fulfill(json={})
                    return
                if method == "PATCH" and day_state["edit_fail"]:
                    route.fulfill(status=503, json={"detail": "synthetic countdown edit failed"})
                    return
                route.continue_()

            page.route(BASE + "/api/days**", days_route)
            page.goto(BASE + "/?view=days", wait_until="domcontentloaded")
            wait_count(held, 1)
            shot("days-loading")
            day_state["mode"] = "normal"
            held.pop().continue_()
            expect(page.locator(".day-card").filter(has_text=f"trip {width}")).to_be_visible()
            expect(page.locator("#days-grid")).to_contain_text("counting up")
            shot("days-populated")
            record("days.populated-load", labels=["today", "upcoming", "counting up"])
            page.locator("#day-add-btn").press("Enter")
            expect(page.locator(".toast.error").last).to_contain_text("what are we counting")
            page.locator("#day-name").fill(f"new countdown {width}")
            page.locator("#day-date").press("Enter")
            page.locator(".dp-now").press("Enter")
            day_state["mode"] = "create-fail"
            page.locator("#day-add-btn").press("Enter")
            expect(page.locator(".toast.error").last).to_contain_text(
                "synthetic countdown create failed"
            )
            expect(page.locator("#day-name")).to_have_value(f"new countdown {width}")
            day_state["mode"] = "normal"
            page.locator("#day-add-btn").press("Enter")
            card = page.locator(".day-card").filter(has_text=f"new countdown {width}")
            expect(card).to_be_visible()
            identity = card.get_attribute("data-id")
            saved = next(
                x for x in api.get(BASE + "/api/days").json()["events"] if x["id"] == identity
            )
            assert saved["name"] == f"new countdown {width}"
            record(
                "days.create-validation-refusal-retry",
                persisted_id=identity,
                keyboard_date_picker=True,
            )
            card.locator('[data-act="edit"]').press("Enter")
            editor = page.locator(".day-card.editing")
            editor.locator('[data-f="name"]').fill("cancelled countdown draft")
            editor.locator('[data-act="cancel"]').press("Enter")
            expect(
                page.locator(".day-card").filter(has_text=f"new countdown {width}")
            ).to_be_visible()
            card = page.locator(f'.day-card[data-id="{identity}"]')
            card.locator('[data-act="edit"]').press("Enter")
            page.locator('.day-card.editing [data-f="name"]').fill(f"edited countdown {width}")
            endpoint = BASE + "/api/days/" + identity
            day_state["edit_fail"] = True
            page.locator('.day-card.editing [data-act="save"]').press("Enter")
            expect(page.locator(".toast.error").last).to_contain_text(
                "synthetic countdown edit failed"
            )
            expect(page.locator('.day-card.editing [data-f="name"]')).to_have_value(
                f"edited countdown {width}"
            )
            day_state["edit_fail"] = False
            page.locator('.day-card.editing [data-act="save"]').press("Enter")
            expect(page.locator(f'.day-card[data-id="{identity}"] .day-name')).to_have_text(
                f"edited countdown {width}"
            )
            card = page.locator(f'.day-card[data-id="{identity}"]')
            card.locator('[data-act="pin"]').press("Enter")
            expect(card.locator('[data-act="pin"]')).to_have_attribute("title", "unpin")
            card.locator('[data-act="del"]').press("Enter")
            page.get_by_role("alertdialog").get_by_role("button", name="cancel", exact=True).press(
                "Enter"
            )
            expect(card).to_be_visible()
            card.locator('[data-act="del"]').press("Enter")
            page.get_by_role("alertdialog").get_by_role("button", name="confirm", exact=True).press(
                "Enter"
            )
            expect(card).to_have_count(0)
            record(
                "days.edit-pin-delete-cancel-retry",
                exact_backend_deleted=not any(
                    x["id"] == identity for x in api.get(BASE + "/api/days").json()["events"]
                ),
            )

            identity = seeded[1]["id"]
            card = page.locator(f'.day-card[data-id="{identity}"]')
            card.locator('[data-act="edit"]').press("Enter")
            page.locator('.day-card.editing [data-f="name"]').fill(f"first saved edit {width}")
            held = []
            day_state["mode"] = "edit-hold"
            page.locator('.day-card.editing [data-act="save"]').press("Enter")
            wait_count(held, 1)
            expect(page.locator('.day-card.editing [data-act="save"]')).to_be_disabled()
            page.locator('.day-card.editing [data-f="name"]').fill(f"newer unsaved edit {width}")
            route = held.pop()
            reply = route.fetch()
            assert reply.ok
            day_state["mode"] = "normal"
            route.fulfill(response=reply)
            expect(page.locator('.day-card.editing [data-f="name"]')).to_have_value(
                f"newer unsaved edit {width}"
            )
            expect(page.locator('.day-card.editing [data-act="save"]')).to_be_enabled()
            assert (
                next(
                    x for x in api.get(BASE + "/api/days").json()["events"] if x["id"] == identity
                )["name"]
                == f"first saved edit {width}"
            )
            page.locator('.day-card.editing [data-act="save"]').press("Enter")
            expect(card.locator(".day-name")).to_have_text(f"newer unsaved edit {width}")
            record("days.newer-edit-during-save", persisted_first_then_newer=True)
            for mode in ["delete-fail", "delete-malformed"]:
                day_state["mode"] = mode
                card.locator('[data-act="del"]').press("Enter")
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).press("Enter")
                expect(page.locator(".toast.error").last).to_contain_text(
                    "synthetic deletion unavailable" if mode == "delete-fail" else "not confirmed"
                )
                expect(card).to_be_visible()
                expect(card.locator('[data-act="del"]')).to_be_enabled()
                assert any(
                    x["id"] == identity for x in api.get(BASE + "/api/days").json()["events"]
                )
            day_state["mode"] = "normal"
            card.locator('[data-act="del"]').press("Enter")
            page.get_by_role("alertdialog").get_by_role("button", name="confirm", exact=True).press(
                "Enter"
            )
            expect(card).to_have_count(0)
            assert not any(
                x["id"] == identity for x in api.get(BASE + "/api/days").json()["events"]
            )
            record(
                "days.delete-refused-malformed-retry", real_backend_deleted_only_after_retry=True
            )

            held = []
            day_state["mode"] = "create-hold"
            page.locator("#day-name").fill(f"pending countdown {width}")
            page.locator("#day-add-btn").press("Enter")
            wait_count(held, 1)
            pending_enabled = page.locator("#day-add-btn").is_enabled()
            if pending_enabled:
                page.locator("#day-add-btn").press("Enter")
                wait_count(held, 2)
            page.locator("#day-name").fill("newer countdown draft must remain")
            calls = len(held)
            for route in list(held):
                response = route.fetch()
                assert response.ok
                route.fulfill(response=response)
            day_state["mode"] = "normal"
            expect(
                page.locator(".day-name").filter(has_text=f"pending countdown {width}")
            ).to_have_count(calls)
            page.wait_for_timeout(100)
            newer = page.locator("#day-name").input_value()
            persisted = sum(
                x["name"] == f"pending countdown {width}"
                for x in api.get(BASE + "/api/days").json()["events"]
            )
            shot("days-pending-result")
            record(
                "days.pending-create-ownership",
                calls == 1 and newer == "newer countdown draft must remain",
                requests=calls,
                persisted_count=persisted,
                newer_input=newer,
                pending_button_enabled=pending_enabled,
            )
            day_state["mode"] = "load-fail"
            page.reload(wait_until="networkidle")
            text = page.locator("#days-grid").inner_text()
            shot("days-load-error")
            record(
                "days.failed-list-state",
                "unavailable" in text or "retry" in text,
                visible_text=text,
                stored_events=len(api.get(BASE + "/api/days").json()["events"]),
            )
            day_state["mode"] = "normal"
            page.locator("#days-retry").press("Enter")
            expect(page.locator(".day-card").first).to_be_visible()
            expect(page.locator("#days-retry")).to_have_count(0)
            day_state["mode"] = "load-hold"
            held = []
            page.get_by_role("tab", name="tasks", exact=True).press("Enter")
            page.get_by_role("tab", name="countdowns", exact=True).press("Enter")
            wait_count(held, 1)
            older = held.pop()
            snapshot = older.fetch()
            assert snapshot.ok
            day_state["mode"] = "normal"
            identity = seeded[0]["id"]
            assert api.patch(
                BASE + "/api/days/" + identity, data={"name": f"newer navigation state {width}"}
            ).ok
            page.get_by_role("tab", name="tasks", exact=True).press("Enter")
            page.get_by_role("tab", name="countdowns", exact=True).press("Enter")
            expect(page.locator(f'.day-card[data-id="{identity}"] .day-name')).to_have_text(
                f"newer navigation state {width}"
            )
            older.fulfill(response=snapshot)
            page.wait_for_timeout(100)
            expect(page.locator(f'.day-card[data-id="{identity}"] .day-name')).to_have_text(
                f"newer navigation state {width}"
            )
            record("days.stale-navigation-read", newer_record_preserved=True)

        except Exception as error:
            record("days.driver", False, error=str(error), traceback=traceback.format_exc())
            shot("days-driver-failure")

        record(
            "browser-boundary",
            not errors and not external,
            page_errors=errors,
            console_errors=console,
            external=external,
        )
        context.tracing.stop(path=str(OUT / f"{width}-trace.zip"))
        context.close()
    browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
