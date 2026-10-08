"""Exact Home records survive delayed loads, drafts, retries and scoped event edits."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    today = datetime.now(UTC).date().isoformat()
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    results = []
    cases = [
        "selection-old-first",
        "selection-new-first",
        "unrelated-draft",
        "calendar-retry",
        "calendar-shell-retry",
        "calendar-metadata",
        "calendar-overlay",
        "saved-occurrence",
        "saved-following",
        "saved-all",
        "saved-all-moved",
        "saved-all-excluded",
        "saved-all-weekday-excluded",
        "deleted-occurrence",
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, case in ((width, case) for width in (1440, 390) for case in cases):
            label = f"{case}-{width}"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                timezone_id="UTC",
                service_workers="block",
                reduced_motion="reduce",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            cleanup, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

            def create(endpoint, body):
                response = context.request.post(base + "/api/" + endpoint, data=body)
                assert response.ok, response.text()
                value = response.json()
                cleanup.append((endpoint, value["id"]))
                return value

            def home():
                page.goto(base + "/?app=home", wait_until="networkidle")
                if page.locator("#setup-wizard").is_visible():
                    page.locator("#setup-skip").click()

            def task(name):
                return create("tasks", {"title": name, "due_date": today})

            def event():
                return create(
                    "calendar",
                    {
                        "title": "original series",
                        "start_dt": yesterday + "T09:00",
                        "end_dt": yesterday + "T10:00",
                        "recurrence": "daily",
                    },
                )

            def assert_record(item_id):
                assert parse_qs(urlparse(page.url).query)["record"] == [item_id], page.url

            def move_date(selector, day):
                page.locator(selector).click()
                months = "January February March April May June July August September October November December".split()
                for _ in range(12):
                    month, year = page.locator(".date-panel .dp-head span").inner_text().split()
                    current = int(year) * 12 + months.index(month)
                    target = day.year * 12 + day.month - 1
                    if current == target:
                        break
                    step = 1 if current < target else -1
                    page.locator(f'.date-panel [data-nav="{step}"]').click()
                page.locator(f'.date-panel .dp-day[data-d="{day.day}"]').click()
                page.keyboard.press("Escape")

            try:
                if case.startswith("selection-"):
                    a, b = task("first selection"), task("latest selection")
                    home()
                    held = []

                    def hold(route):
                        held.append(route)
                        page.evaluate(
                            "(count)=>document.documentElement.dataset.heldTreeRequests=count",
                            str(len(held)),
                        )

                    page.route("**/api/tasks/tree", hold)
                    page.locator(f'[data-record="{a["id"]}"]').click()
                    expect(page.locator("html")).to_have_attribute("data-held-tree-requests", "1")
                    page.go_back(wait_until="domcontentloaded")
                    expect(page.locator("#today-view")).to_be_visible()
                    page.locator(f'[data-record="{b["id"]}"]').click()
                    expect(page.locator("html")).to_have_attribute("data-held-tree-requests", "2")
                    for index in [0, 1] if case == "selection-old-first" else [1, 0]:
                        with page.expect_response("**/api/tasks/tree"):
                            held[index].fulfill(response=held[index].fetch())
                    page.unroute("**/api/tasks/tree")
                    expect(page.locator("#te-title")).to_have_value("latest selection")
                    assert_record(b["id"])
                    page.locator("#te-title").fill("latest saved")
                    page.locator("#te-save").click()
                    expect(page.locator("#te-title")).to_have_count(0)
                    saved = {
                        item["id"]: item for item in context.request.get(base + "/api/tasks").json()
                    }
                    assert saved[b["id"]]["title"] == "latest saved"
                    assert saved[a["id"]]["title"] == "first selection"
                elif case == "unrelated-draft":
                    a, b = task("draft a"), task("target b")
                    home()
                    page.locator(f'[data-record="{a["id"]}"]').click()
                    page.locator("#te-title").fill("unsaved a")
                    home()
                    page.locator(f'[data-record="{b["id"]}"]').click()
                    expect(page.locator("#te-title")).to_have_value("target b")
                    assert_record(b["id"])
                    page.locator("#te-title").fill("unsaved b")
                    home()
                    page.locator(f'[data-record="{b["id"]}"]').click()
                    expect(page.locator("#te-title")).to_have_value("unsaved b")
                    home()
                    page.locator(f'[data-record="{a["id"]}"]').click()
                    expect(page.locator("#te-title")).to_have_value("unsaved a")
                    assert_record(a["id"])
                elif case.startswith("calendar-"):
                    item = event()
                    home()
                    endpoint = (
                        "calendars"
                        if case == "calendar-metadata"
                        else "calendar/tasks"
                        if case == "calendar-overlay"
                        else "calendar"
                    )
                    pattern = "**/api/" + endpoint
                    page.route(pattern, lambda route: route.fulfill(status=503, body="unavailable"))
                    page.locator(f'[data-record="{item["id"]}"]').click()
                    if case in ["calendar-metadata", "calendar-overlay"]:
                        expect(page.locator("#te-title")).to_have_count(0)
                        expect(page.locator("#cal-title")).to_have_value("original series")
                        expect(page.locator("#plan-view > .specialist-state")).to_have_attribute(
                            "data-state", "partial"
                        )
                    else:
                        expect(page.locator("#cal-load-error")).to_be_visible()
                        expect(page.locator("#cal-title")).to_have_count(0)
                    assert_record(item["id"])
                    assert errors and all("503" in error for error in errors), errors
                    errors.clear()
                    page.unroute(pattern)
                    if case == "calendar-metadata":
                        page.locator("#cal-title").fill("retained event draft")
                        page.locator("#cal-metadata-error button").click()
                        expect(page.locator("#cal-metadata-error")).to_have_count(0)
                        expect(page.locator("#cal-title")).to_have_value("retained event draft")
                    elif case != "calendar-overlay":
                        selector = (
                            "#cal-load-error button"
                            if case == "calendar-retry"
                            else "#plan-view > .specialist-state .specialist-state-retry"
                        )
                        page.locator(selector).click()
                        expect(page.locator("#cal-title")).to_have_value("original series")
                    assert_record(item["id"])
                elif case.startswith("saved-all"):
                    item = event()
                    home()
                    page.locator(f'[data-record="{item["id"]}"]').click()
                    selected = datetime.now(UTC).date()
                    if case == "saved-all-moved":
                        selected += timedelta(days=1)
                        move_date("#cal-start", selected)
                        move_date("#cal-end", selected)
                    if case == "saved-all-excluded":
                        page.locator("#cal-count").fill("1")
                    if case == "saved-all-weekday-excluded":
                        page.locator("#cal-recur").click()
                        page.get_by_role("option", name="weekly", exact=True).click()
                        # Neither the old series start nor the selected occurrence remains.
                        next_weekday = (selected.weekday() + 2) % 7
                        for button in page.locator('#cal-dow [aria-pressed="true"]').all():
                            button.click()
                        page.locator(f'#cal-dow [data-i="{next_weekday}"]').click()
                    page.locator("#cal-title").fill("whole series saved")
                    page.locator("#cal-save").click()
                    page.get_by_role("button", name="All events", exact=True).click()
                    expect(page.locator("#cal-title")).to_have_count(0)
                    assert_record(item["id"])
                    if case in {"saved-all-excluded", "saved-all-weekday-excluded"}:
                        assert "occurrence" not in parse_qs(urlparse(page.url).query)
                        selected = datetime.fromisoformat(yesterday).date()
                    else:
                        assert parse_qs(urlparse(page.url).query)["occurrence"] == [str(selected)]
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#cal-title")).to_have_value("whole series saved")
                    expect(page.locator("#cal-start")).to_have_attribute(
                        "data-value", str(selected) + "T09:00"
                    )
                    # The next scoped edit must affect the selected day, not the series start.
                    page.locator("#cal-title").fill("selected day saved")
                    page.locator("#cal-save").click()
                    if case == "saved-all-weekday-excluded":
                        expect(
                            page.get_by_role("button", name="This event", exact=True)
                        ).to_have_count(0)
                        page.get_by_role("button", name="All events", exact=True).click()
                        expect(page.locator("#cal-title")).to_have_count(0)
                        assert_record(item["id"])
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#cal-title")).to_have_value("selected day saved")
                        page.locator("#cal-del").click()
                        expect(
                            page.get_by_role("button", name="This event", exact=True)
                        ).to_have_count(0)
                        page.get_by_role("button", name="cancel", exact=True).click()
                    else:
                        page.get_by_role("button", name="This event", exact=True).click()
                        expect(page.locator("#cal-title")).to_have_count(0)
                        child = next(
                            row
                            for row in context.request.get(base + "/api/calendar").json()
                            if row["title"] == "selected day saved"
                        )
                        cleanup.append(("calendar", child["id"]))
                        assert child["start_dt"].startswith(str(selected))
                        assert_record(child["id"])
                else:
                    item = event()
                    home()
                    page.locator(f'[data-record="{item["id"]}"]').click()
                    stale_link = page.url
                    if case == "deleted-occurrence":
                        # A second client removes this occurrence while its link is retained.
                        response = context.request.delete(
                            base + f"/api/calendar/{item['id']}?scope=this&occ={today}"
                        )
                        assert response.ok, response.text()
                    else:
                        page.locator("#cal-title").fill("saved occurrence")
                        page.locator("#cal-save").click()
                        scope = "This and following" if case == "saved-following" else "This event"
                        page.get_by_role("dialog", name="edit recurring event").get_by_role(
                            "button", name=scope, exact=True
                        ).click()
                        expect(page.locator("#cal-title")).to_have_count(0)
                        saved = next(
                            value
                            for value in context.request.get(base + "/api/calendar").json()
                            if value["title"] == "saved occurrence"
                        )
                        cleanup.append(("calendar", saved["id"]))
                        assert_record(saved["id"])
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#cal-title")).to_have_value("saved occurrence")
                        assert_record(saved["id"])
                    page.goto(stale_link, wait_until="networkidle")
                    expect(page.locator("#cal-title")).to_have_count(0)
                    expect(page.locator("#toast-container .toast.error").last).to_contain_text(
                        "could not open this item"
                    )
                assert not errors, errors
                results.append({"case": case, "width": width, "status": "passed"})
            except Exception as error:
                results.append(
                    {
                        "case": case,
                        "width": width,
                        "status": "failed",
                        "error": str(error),
                        "url": page.url,
                    }
                )
            finally:
                page.screenshot(path=str(out / (label + ".png")), full_page=True)
                for endpoint, item_id in reversed(cleanup):
                    context.request.delete(base + "/api/" + endpoint + "/" + item_id)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
    print(json.dumps(results, indent=2))
    raise SystemExit(any(result["status"] == "failed" for result in results))


if __name__ == "__main__":
    run()
