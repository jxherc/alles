"""Calendar saved-value, recovery, recurrence, keyboard and shared-picker workflows."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        for profile, theme in [("desktop", "dark"), ("phone", "light"), ("phone", "dark")]:
            label = f"{profile}-{theme}"
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440 if profile == "desktop" else 390, "height": 900},
                timezone_id="America/Toronto",
                locale="en-US",
                reduced_motion="reduce",
                service_workers="block",
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(12000)
            events, proof, expected_http, expected_network = [], [], [], []
            active = None
            page.on(
                "console",
                lambda message: (
                    events.append(
                        {
                            "console": message.type,
                            "text": message.text,
                            "url": message.location.get("url", ""),
                        }
                    )
                    if message.type in {"warning", "error"}
                    else None
                ),
            )
            page.on("pageerror", lambda error: events.append({"pageerror": str(error)}))
            page.on(
                "requestfailed",
                lambda request: events.append(
                    {"failed": request.url, "method": request.method, "failure": request.failure}
                ),
            )

            def response(result):
                if result.status >= 400 or (
                    "/api/" in result.url and result.request.method != "GET"
                ):
                    try:
                        body = result.text()
                    except Exception:
                        body = "unavailable"
                    events.append(
                        {
                            "url": result.url,
                            "method": result.request.method,
                            "status": result.status,
                            "request": result.request.post_data,
                            "body": body,
                        }
                    )

            page.on("response", response)

            def begin(name):
                nonlocal active
                active = {
                    "id": f"calendar.{name}.{label}",
                    "scenario_id": f"calendar.{name}",
                    "status": "failed",
                    "profile": label,
                }
                records.append(active)

            def passed(**evidence):
                active.update(status="passed", **evidence)
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))

            def shot(name):
                page.screenshot(path=str(output / f"{label}-{name}.png"), full_page=True)

            def rows():
                result = context.request.get(base + "/api/calendar")
                assert result.ok, result.text()
                return result.json()

            def saved(eid):
                return next(row for row in rows() if row["id"] == eid)

            def remember(name, value):
                proof.append({"case": name, "value": value})

            def calendar(reload=False):
                if reload:
                    page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="calendar", exact=True).click()
                expect(page.locator("#cal-new-btn")).to_be_visible()
                if page.locator("#cal-load-error").is_visible():
                    return
                months = "January February March April May June July August September October November December".split()
                for _ in range(120):
                    month, year = page.locator("#cal-month-label").inner_text().split()
                    current = int(year) * 12 + months.index(month)
                    target = 2026 * 12 + 8
                    if current == target:
                        break
                    page.locator("#cal-next" if current < target else "#cal-prev").click()
                else:
                    raise AssertionError("fixture month was not reachable")

            def new(title):
                page.locator("#cal-new-btn").click()
                page.locator("#cal-title").fill(title)

            def set_date(
                selector, day, hour=None, minute=None, *, target_year=2026, target_month=9
            ):
                page.locator(selector).click()
                months = "January February March April May June July August September October November December".split()
                for _ in range(120):
                    month, year = page.locator(".date-panel .dp-head span").inner_text().split()
                    current = int(year) * 12 + months.index(month)
                    target = target_year * 12 + target_month - 1
                    if current == target:
                        break
                    step = 1 if current < target else -1
                    page.locator(f'.date-panel [data-nav="{step}"]').click()
                else:
                    raise AssertionError("fixture picker month was not reachable")
                page.locator(f'.date-panel .dp-day[data-d="{day}"]').click()
                if hour is not None:
                    if not page.locator(".date-panel").count():
                        page.locator(selector).click()
                    for step, target, index in [("h1", hour, 0), ("mi1", minute, 1)]:
                        for _ in range(60):
                            if (
                                int(page.locator(".date-panel .dp-tv").nth(index).inner_text())
                                == target
                            ):
                                break
                            page.locator(f'.date-panel [data-step="{step}"]').click()
                        else:
                            raise AssertionError("time target not reached")
                    page.keyboard.press("Escape")

            def save():
                page.locator("#cal-save").click()
                expect(page.locator("#cal-title")).to_have_count(0)

            def open_event(eid, occurrence=None):
                selector = f'.cal-chip[data-id="{eid}"]'
                if occurrence:
                    selector += f'[data-occ="{occurrence}"]'
                page.locator(selector).first.click()
                expect(page.locator("#cal-title")).to_be_visible()

            def scope(value):
                page.get_by_role("dialog", name="edit recurring event").get_by_role(
                    "button", name=value, exact=True
                ).click()

            def simulate(method, status=503, payload=None, abort=False):
                def handler(route):
                    if (
                        route.request.method != method
                        or "/attendees" in route.request.url
                        or (
                            method in {"GET", "POST"}
                            and urlsplit(route.request.url).path != "/api/calendar"
                        )
                    ):
                        route.continue_()
                    elif abort:
                        expected_network.append(route.request.url)
                        route.abort("failed")
                    else:
                        if status >= 400:
                            expected_http.append({"url": route.request.url, "status": status})
                        route.fulfill(
                            status=status, content_type="application/json", body=json.dumps(payload)
                        )

                page.route("**/api/calendar{,/**,?**}", handler)
                return handler

            def stop_simulation(handler):
                page.unroute("**/api/calendar{,/**,?**}", handler)

            def tab_to(selector):
                for _ in range(100):
                    page.keyboard.press("Tab")
                    if page.locator(selector).evaluate("e => e === document.activeElement"):
                        return
                raise AssertionError("unreachable by Tab: " + selector)

            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                page.locator("#today-settings").click()
                page.locator('.s-nav-item[data-pane="themes"]').click()
                page.wait_for_function(
                    't => document.querySelector(`[data-theme-mode="${t}"]`)?.dataset.bound === "1"',
                    arg=theme,
                )
                with page.expect_response(
                    lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                ) as changed:
                    page.locator(f'[data-theme-mode="{theme}"]').click()
                assert changed.value.ok
                page.locator("#settings-modal-close").click()
                page.goto(base + "/?view=plan", wait_until="networkidle")
                calendar()
                begin("empty-and-search")
                expect(page.locator("#cal-search")).to_be_visible()
                shot("empty")
                passed()

                begin("overnight-create-edit-reload")
                title = label + " overnight 跨日"
                new(title)
                set_date("#cal-start", 26, 23, 45)
                set_date("#cal-end", 27, 0, 30)
                page.locator("#cal-desc").fill("Original text")
                save()
                event = next(row for row in rows() if row["title"] == title)
                eid = event["id"]
                assert (
                    event["start_dt"] == "2026-09-26T23:45"
                    and event["end_dt"] == "2026-09-27T00:30"
                )
                calendar(reload=True)
                open_event(eid)
                expect(page.locator("#cal-end")).to_have_attribute("data-value", "2026-09-27T00:30")
                page.locator("#cal-desc").fill("Only description changed")
                save()
                calendar(reload=True)
                assert saved(eid)["end_dt"] == event["end_dt"]
                remember("overnight exact values", saved(eid))
                passed()

                begin("keyboard-event-and-move")
                page.locator("#cal-search").fill("跨日")
                expect(page.locator(f'.cal-chip[data-id="{eid}"]')).to_be_visible()
                page.locator("#cal-search").click()
                tab_to(f'.cal-chip[data-id="{eid}"]')
                page.keyboard.press("Enter")
                expect(page.locator("#cal-title")).to_have_value(title)
                set_date("#cal-start", 28, 23, 45)
                set_date("#cal-end", 29, 0, 30)
                save()
                calendar(reload=True)
                assert saved(eid)["start_dt"] == "2026-09-28T23:45"
                assert saved(eid)["end_dt"] == "2026-09-29T00:30"
                page.locator(f'.cal-chip[data-id="{eid}"]').first.scroll_into_view_if_needed()
                targets = page.locator(".cal-chip").evaluate_all("""elements => elements.map(e => {
                    const b = e.getBoundingClientRect(), p = e.closest('.cal-cell').getBoundingClientRect();
                    return {width:b.width,height:b.height,left:b.left,right:b.right,cellLeft:p.left,cellRight:p.right};
                })""")
                for target in targets:
                    assert target["width"] >= 44 and target["height"] >= 44, target
                    assert target["left"] >= target["cellLeft"] - 1, target
                    assert target["right"] <= target["cellRight"] + 1, target
                remember("unclipped event target bounds", targets)
                shot("populated")
                passed()

                begin("create-failure-retry")
                new(label + " create retry")
                page.locator("#cal-desc").fill("Do not lose this draft")
                handler = simulate("POST", payload={"detail": "simulated write unavailable"})
                page.locator("#cal-save").click()
                expect(page.locator("#cal-save-error")).to_contain_text(
                    "simulated write unavailable"
                )
                expect(page.locator("#cal-desc")).to_have_value("Do not lose this draft")
                assert not any(row["title"] == label + " create retry" for row in rows())
                shot("failed-draft")
                stop_simulation(handler)
                save()
                retry = next(row for row in rows() if row["title"] == label + " create retry")
                calendar(reload=True)
                assert saved(retry["id"])["description"] == "Do not lose this draft"
                passed()

                for kind, payload in [
                    ("null", None),
                    ("empty-object", {}),
                    ("invalid-id", {"id": "", "title": "wrong", "start_dt": "wrong"}),
                ]:
                    begin("malformed-ack-" + kind)
                    new(label + " malformed")
                    handler = simulate("POST", status=200, payload=payload)
                    page.locator("#cal-save").click()
                    expect(page.locator("#cal-save-error")).to_contain_text("did not confirm")
                    expect(page.locator("#cal-title")).to_have_value(label + " malformed")
                    stop_simulation(handler)
                    page.locator("#cal-back").click()
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="confirm", exact=True
                    ).click()
                    expect(page.locator("#cal-title")).to_have_count(0)
                    passed()

                begin("network-retry-and-single-pending-save")
                new(label + " network retry")
                handler = simulate("POST", abort=True)
                page.locator("#cal-save").click()
                expect(page.locator("#cal-save-error")).to_contain_text("Check your connection")
                stop_simulation(handler)
                pending = []

                def hold(route):
                    if route.request.method == "POST":
                        pending.append(route)
                    else:
                        route.continue_()

                page.route("**/api/calendar", hold)
                button = page.locator("#cal-save")
                button.click()
                expect(button).to_be_disabled()
                rect = button.bounding_box()
                page.mouse.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
                page.wait_for_timeout(150)
                assert len(pending) == 1
                pending[0].continue_()
                expect(page.locator("#cal-title")).to_have_count(0)
                page.unroute("**/api/calendar", hold)
                calendar(reload=True)
                assert sum(row["title"] == label + " network retry" for row in rows()) == 1
                passed()

                begin("edit-and-delete-recovery")
                open_event(eid)
                page.locator("#cal-desc").fill("Recovered edit")
                handler = simulate("PATCH", payload={"detail": "simulated edit unavailable"})
                page.locator("#cal-save").click()
                expect(page.locator("#cal-save-error")).to_contain_text(
                    "simulated edit unavailable"
                )
                assert saved(eid)["description"] == "Only description changed"
                stop_simulation(handler)
                save()
                calendar(reload=True)
                assert saved(eid)["description"] == "Recovered edit"
                open_event(eid)
                handler = simulate("DELETE", payload={"detail": "simulated delete unavailable"})
                page.locator("#cal-del").click()
                expect(page.locator("#cal-save-error")).to_contain_text(
                    "simulated delete unavailable"
                )
                assert saved(eid)["id"] == eid
                stop_simulation(handler)
                page.locator("#cal-del").click()
                expect(page.locator("#cal-title")).to_have_count(0)
                calendar(reload=True)
                assert not any(row["id"] == eid for row in rows())
                passed()

                begin("dirty-back-and-list-retry")
                new(label + " dirty")
                page.locator("#cal-desc").fill("Keep while canceling")
                page.locator("#cal-back").click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(page.locator("#cal-desc")).to_have_value("Keep while canceling")
                page.locator("#cal-back").click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                handler = simulate("GET", payload={"detail": "simulated calendar unavailable"})
                calendar(reload=True)
                expect(page.locator("#cal-load-error")).to_contain_text("Could not load calendar")
                shot("list-error")
                stop_simulation(handler)
                page.locator("#cal-load-error").get_by_role("button", name="retry").click()
                expect(page.locator("#cal-load-error")).to_have_count(0)
                expect(page.locator(".cal-chip").first).to_be_visible()
                calendar(reload=True)
                passed()

                begin("keyboard-choices-and-picker-bounds")
                new(label + " choices")
                set_date("#cal-start", 25, 9, 0)
                set_date("#cal-end", 26, 9, 0)
                date_bounds = page.locator("#cal-start,#cal-end").evaluate_all("""elements => elements.map(e => {
                    const b = e.getBoundingClientRect(), label = e.querySelector('.date-input-label');
                    return {id:e.id,left:b.left,right:b.right,width:b.width,height:b.height,labelWidth:label.clientWidth,labelContentWidth:label.scrollWidth};
                })""")
                for bounds in date_bounds:
                    assert bounds["left"] >= 0 and bounds["right"] <= page.viewport_size["width"], (
                        bounds
                    )
                    assert bounds["width"] >= 44 and bounds["height"] >= 44, bounds
                    assert bounds["labelContentWidth"] <= bounds["labelWidth"] + 1, bounds
                remember("populated editor date field bounds", date_bounds)
                page.locator("#cal-start").scroll_into_view_if_needed()
                shot("date-fields")
                page.locator("#cal-title").click()
                tab_to("#cal-allday")
                page.keyboard.press("Space")
                expect(page.locator("#cal-allday")).to_have_attribute("aria-checked", "true")
                page.locator("#cal-recur").click()
                page.get_by_role("option", name="weekly", exact=True).click()
                page.locator("#cal-title").click()
                tab_to('.cal-dow-b[data-i="1"]')
                page.keyboard.press("Space")
                expect(page.locator('.cal-dow-b[data-i="1"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                tab_to('.cal-rem[data-m="60"]')
                page.keyboard.press("Space")
                tab_to('.cal-sw[data-c="tomato"]')
                page.keyboard.press("Space")
                expect(page.locator('.cal-sw[data-c="tomato"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                for control in page.locator(
                    "#cal-allday,.cal-dow-b,.cal-rem,#cal-colors .cal-sw"
                ).all():
                    rect = control.bounding_box()
                    assert rect["width"] >= 44 and rect["height"] >= 44, rect
                page.locator("#cal-title").click()
                tab_to("#cal-end")
                page.keyboard.press("Enter")
                panel = page.locator(".date-panel")
                expect(panel).to_be_visible()
                for _ in range(panel.locator("button").count() + 2):
                    page.keyboard.press("Tab")
                    assert panel.evaluate("e => e.contains(document.activeElement)")
                for control in panel.locator("button").all():
                    rect = control.bounding_box()
                    assert rect["x"] >= 0 and rect["y"] >= 0
                    assert rect["x"] + rect["width"] <= page.viewport_size["width"] + 1
                    assert rect["y"] + rect["height"] <= page.viewport_size["height"] + 1
                shot("picker")
                page.locator('.date-panel .dp-day[data-d="26"]').click()
                page.keyboard.press("Escape")
                expect(page.locator("#cal-end")).to_be_focused()
                assert (
                    page.locator("#cal-end").get_attribute("data-value").startswith("2026-09-26T")
                )
                page.locator("#cal-save").scroll_into_view_if_needed()
                shot("editor-actions")
                save()
                calendar(reload=True)
                choices = next(row for row in rows() if row["title"] == label + " choices")
                assert choices["all_day"] is True
                assert choices["recur_byday"] == "MO,FR"
                assert choices["reminders"] == [10, 60]
                assert choices["color"] == "tomato"
                assert choices["start_dt"] == "2026-09-25T09:00"
                assert choices["end_dt"] == "2026-09-26T09:00"
                open_event(choices["id"])
                expect(page.locator("#cal-allday")).to_have_attribute("aria-checked", "true")
                expect(page.locator('.cal-dow-b[data-i="1"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(page.locator('.cal-rem[data-m="60"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(page.locator('.cal-sw[data-c="tomato"]')).to_have_attribute(
                    "aria-pressed", "true"
                )
                remember("keyboard choices persisted after reload", choices)
                page.locator("#cal-del").click()
                page.get_by_role("dialog", name="delete recurring event").get_by_role(
                    "button", name="All events", exact=True
                ).click()
                expect(page.locator("#cal-title")).to_have_count(0)
                calendar(reload=True)
                assert not any(row["id"] == choices["id"] for row in rows())
                passed()

                begin("recurrence-origin-scope-cancel-and-failures")
                new(label + " weekly")
                set_date("#cal-start", 25, 9, 0)
                set_date("#cal-end", 25, 10, 0)
                page.locator("#cal-recur").click()
                page.get_by_role("option", name="weekly", exact=True).click()
                page.locator("#cal-count").fill("3")
                save()
                series = next(row for row in rows() if row["title"] == label + " weekly")
                sid = series["id"]
                page.locator("#cal-next").click()
                open_event(sid, "2026-10-02")
                page.locator("#cal-desc").fill("Same series origin")
                page.locator("#cal-save").click()
                dialog = page.get_by_role("dialog", name="edit recurring event")
                expect(dialog).to_be_visible()
                assert dialog.evaluate("e => e.contains(document.activeElement)")
                for _ in range(6):
                    page.keyboard.press("Tab")
                    assert dialog.evaluate("e => e.contains(document.activeElement)")
                shot("scope")
                page.keyboard.press("Escape")
                expect(page.locator("#cal-save")).to_be_focused()
                assert saved(sid) == series
                page.locator("#cal-save").click()
                scope("All events")
                expect(page.locator("#cal-title")).to_have_count(0)
                calendar(reload=True)
                assert saved(sid)["start_dt"] == series["start_dt"]
                assert saved(sid)["end_dt"] == series["end_dt"]
                assert saved(sid)["recur_count"] == 3
                for which, occurrence in [
                    ("This event", "2026-10-02"),
                    ("This and following", "2026-10-09"),
                ]:
                    page.locator("#cal-next").click()
                    open_event(sid, occurrence)
                    page.locator("#cal-desc").fill(which + " revised")
                    before = rows()
                    handler = simulate(
                        "PATCH", payload={"detail": "simulated atomic edit unavailable"}
                    )
                    page.locator("#cal-save").click()
                    scope(which)
                    expect(page.locator("#cal-save-error")).to_contain_text(
                        "simulated atomic edit unavailable"
                    )
                    assert rows() == before
                    stop_simulation(handler)
                    page.locator("#cal-save").click()
                    scope(which)
                    expect(page.locator("#cal-title")).to_have_count(0)
                    calendar(reload=True)
                    remember(which, rows())
                master = saved(sid)
                assert master["start_dt"] == series["start_dt"]
                assert master["recur_except"] == ["2026-10-02"]
                assert master["recur_until"] == "2026-10-08"
                tail = next(
                    row for row in rows() if row["description"] == "This and following revised"
                )
                assert tail["recur_count"] == 1
                passed()

                begin("scoped-write-lost-ack-retry-no-duplicate")
                for scope_label in ["This event", "This and following"]:
                    response = context.request.post(
                        base + "/api/calendar",
                        data={
                            "title": label + " lost acknowledgment " + scope_label,
                            "start_dt": "2026-09-25T09:00",
                            "end_dt": "2026-09-25T10:00",
                            "recurrence": "weekly",
                            "recur_byday": "FR",
                            "recur_count": 3,
                        },
                    )
                    assert response.ok, response.text()
                    original = response.json()
                    calendar(reload=True)
                    page.locator("#cal-next").click()
                    open_event(original["id"], "2026-10-02")
                    description = label + " saved despite lost acknowledgment " + scope_label
                    page.locator("#cal-desc").fill(description)
                    committed = []

                    def lose_ack(route):
                        if route.request.method != "PATCH":
                            route.continue_()
                            return
                        result = route.fetch()
                        assert result.ok, result.text()
                        committed.append({"url": route.request.url, "body": result.json()})
                        expected_network.append(route.request.url)
                        route.abort("failed")

                    page.route("**/api/calendar/**", lose_ack)
                    page.locator("#cal-save").click()
                    scope(scope_label)
                    expect(page.locator("#cal-save-error")).to_contain_text("Check your connection")
                    assert len(committed) == 1
                    child = committed[0]["body"]
                    after_commit = rows()
                    assert child["description"] == description
                    assert child["start_dt"] == "2026-10-02T09:00"
                    page.unroute("**/api/calendar/**", lose_ack)
                    expected_http.append({"url": committed[0]["url"], "status": 409})
                    page.locator("#cal-save").click()
                    scope(scope_label)
                    expect(page.locator("#cal-save-error")).to_contain_text(
                        "no longer in the series"
                    )
                    expect(page.locator("#cal-desc")).to_have_value(description)
                    assert rows() == after_commit
                    shot("lost-ack-" + ("this" if scope_label == "This event" else "following"))
                    calendar(reload=True)
                    assert rows() == after_commit
                    remember(
                        "lost acknowledgment exact retry " + scope_label,
                        {
                            "committed": committed[0],
                            "retry_status": 409,
                            "persisted_rows": after_commit,
                            "limitation": "The saved result is recovered by reload; an exact retry reports a stale occurrence and retains the draft.",
                        },
                    )
                passed(
                    recovery_limit="Lost acknowledgments require reload to inspect the saved result; exact retries return 409 without duplicate writes."
                )

                begin("aware-and-all-day-exact-reload")
                aware = context.request.post(
                    base + "/api/calendar",
                    data={
                        "title": label + " aware",
                        "start_dt": "2026-09-26T02:30:00Z",
                        "end_dt": "2026-09-26T03:30:15Z",
                    },
                ).json()
                calendar(reload=True)
                open_event(aware["id"])
                expect(page.locator("#cal-start")).to_have_attribute(
                    "data-value", "2026-09-25T22:30"
                )
                page.locator("#cal-desc").fill("Aware unchanged")
                save()
                calendar(reload=True)
                assert saved(aware["id"])["start_dt"] == aware["start_dt"]
                assert saved(aware["id"])["end_dt"] == aware["end_dt"]
                new(label + " all day")
                set_date("#cal-start", 27, 9, 0)
                set_date("#cal-end", 29, 9, 0)
                page.locator("#cal-allday").click()
                save()
                all_day = next(row for row in rows() if row["title"] == label + " all day")
                calendar(reload=True)
                expect(page.locator(f'.cal-chip[data-id="{all_day["id"]}"]')).to_have_count(3)
                open_event(all_day["id"])
                expect(page.locator("#cal-end")).to_have_attribute("data-value", "2026-09-29T09:00")
                page.locator("#cal-desc").fill("Preserve all three dates")
                save()
                calendar(reload=True)
                assert saved(all_day["id"])["end_dt"] == all_day["end_dt"]
                shot("all-day")
                passed()

                begin("aware-recurrence-spring-and-fall-boundaries")
                for (
                    case,
                    start,
                    end,
                    occurrence,
                    shown_end,
                    expected_start,
                    expected_end,
                    weekday,
                ) in [
                    (
                        "spring",
                        "2026-03-01T06:30:00Z",
                        "2026-03-01T07:30:00Z",
                        "2026-03-08",
                        "2026-03-08T03:30",
                        "2026-03-08T06:30:00.000Z",
                        "2026-03-08T07:30:00.000Z",
                        "SU",
                    ),
                    (
                        "fall",
                        "2026-11-01T03:30:05.123Z",
                        "2026-11-01T07:30:05.123Z",
                        "2026-11-07",
                        "2026-11-08T03:30",
                        "2026-11-08T04:30:05.123Z",
                        "2026-11-08T08:30:05.123Z",
                        "SA",
                    ),
                ]:
                    response = context.request.post(
                        base + "/api/calendar",
                        data={
                            "title": label + " " + case + " boundary",
                            "start_dt": start,
                            "end_dt": end,
                            "recurrence": "weekly",
                            "recur_byday": weekday,
                            "recur_count": 2,
                        },
                    )
                    assert response.ok, response.text()
                    original = response.json()
                    calendar(reload=True)
                    delta = int(occurrence[5:7]) - 9
                    for _ in range(abs(delta)):
                        page.locator("#cal-next" if delta > 0 else "#cal-prev").click()
                    open_event(original["id"], occurrence)
                    expect(page.locator("#cal-end")).to_have_attribute("data-value", shown_end)
                    description = label + " " + case + " prose only"
                    page.locator("#cal-desc").fill(description)
                    page.locator("#cal-save").click()
                    scope("This event")
                    expect(page.locator("#cal-title")).to_have_count(0)
                    calendar(reload=True)
                    child = next(row for row in rows() if row["description"] == description)
                    assert child["start_dt"] == expected_start, child
                    assert child["end_dt"] == expected_end, child
                    assert saved(original["id"])["start_dt"] == start
                    assert saved(original["id"])["recur_except"] == [occurrence]
                    remember(case + " boundary saved occurrence", child)
                passed()

                begin("shared-picker-countdown-and-reminder")
                page.get_by_role("tab", name="countdowns", exact=True).click()
                page.locator("#day-name").fill(label + " countdown")
                set_date("#day-date", 30)
                page.locator("#day-add-btn").click()
                expect(page.locator("#days-grid")).to_contain_text(label + " countdown")
                result = context.request.get(base + "/api/days").json()
                remember("shared date-only picker", result)
                assert any(
                    row["name"] == label + " countdown" and row["date"] == "2026-09-30"
                    for row in result["events"]
                )
                page.get_by_role("tab", name="reminders", exact=True).click()
                page.locator("#reminder-text").fill(label + " reminder")
                reminder_time = (
                    datetime.now(ZoneInfo("America/Toronto")) + timedelta(days=1)
                ).replace(hour=9, minute=0, second=0, microsecond=0)
                set_date(
                    "#reminder-time",
                    reminder_time.day,
                    reminder_time.hour,
                    reminder_time.minute,
                    target_year=reminder_time.year,
                    target_month=reminder_time.month,
                )
                page.locator("#reminder-add-btn").click()
                expect(page.locator("#reminder-list")).to_contain_text(label + " reminder")
                result = context.request.get(base + "/api/reminders").json()
                remember("shared datetime picker", result)
                reminder = next(row for row in result if row["text"] == label + " reminder")
                assert reminder["trigger_at"].startswith(
                    reminder_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
                )
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="reminders", exact=True).click()
                expect(page.locator("#reminder-list")).to_contain_text(label + " reminder")
                shot("shared-picker-consumer")
                passed()

                for row in rows():
                    assert context.request.delete(base + "/api/calendar/" + row["id"]).ok
                errors = [event for event in events if event.get("pageerror")]
                assert not errors, errors
                unexpected_http = [
                    event
                    for event in events
                    if event.get("status", 0) >= 400
                    and {"url": event["url"], "status": event["status"]} not in expected_http
                ]
                assert not unexpected_http, unexpected_http
                unexpected_network = [
                    event
                    for event in events
                    if event.get("failed") and event["failed"] not in expected_network
                ]
                assert not unexpected_network, unexpected_network
                allowed_console = {
                    (
                        item["url"],
                        f"Failed to load resource: the server responded with a status of {item['status']} ({HTTPStatus(item['status']).phrase})",
                    )
                    for item in expected_http
                }
                allowed_console.update(
                    (url, "Failed to load resource: net::ERR_FAILED") for url in expected_network
                )
                unexpected_console = [
                    event
                    for event in events
                    if event.get("console") == "error"
                    and (event["url"], event["text"]) not in allowed_console
                ]
                assert not unexpected_console, unexpected_console
            except Exception as error:
                if active:
                    active.update(status="failed", error=str(error))
                shot("failure")
                raise
            finally:
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                (output / f"{label}-events.json").write_text(json.dumps(events, indent=2))
                (output / f"{label}-saved-results.json").write_text(json.dumps(proof, indent=2))
                context.tracing.stop(path=str(output / f"{label}.zip"))
                context.close()
                browser.close()
    print(json.dumps({"passed": len(records), "artifacts": str(output)}))


if __name__ == "__main__":
    run()
