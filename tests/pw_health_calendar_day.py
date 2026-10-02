"""Health dates, habits, and midnight retries share Home's resolved calendar day."""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    server_day = datetime.now(UTC).date().isoformat()
    profiles = [
        (zone, hour, width, "")
        for zone, hour in [("America/Toronto", 1), ("Asia/Tokyo", 23)]
        for width in [1440, 390]
    ]
    profiles.append(("America/Toronto", 23, 390, "Asia/Tokyo"))
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for zone, hour, width, override in profiles:
            for case in ["measurement", "habit", "import"]:
                effective_zone = override or zone
                instant = datetime.fromisoformat(server_day + f"T{hour:02}:30:00+00:00")
                first_day = instant.astimezone(ZoneInfo(effective_zone)).date().isoformat()
                next_day = (
                    (instant + timedelta(days=1))
                    .astimezone(ZoneInfo(effective_zone))
                    .date()
                    .isoformat()
                )
                assert first_day != server_day, "fixture must cross a UTC calendar day"
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id=zone,
                    service_workers="block",
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                page.clock.set_fixed_time(instant)
                errors, console, posts, reads = [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )

                def observe(req):
                    if req.method == "POST" and req.url in [
                        base + "/api/health",
                        base + "/api/health/import",
                    ]:
                        posts.append(req.post_data_json)
                    if req.method == "GET" and "/api/health/overview?" in req.url:
                        reads.append(req.url)

                page.on("request", observe)
                label = (
                    f"{zone.replace('/', '-')}-{width}-{'override' if override else 'auto'}-{case}"
                )
                result = {
                    "scenario_id": "health.calendar-day." + case,
                    "feature_id": "health.logs-and-habits",
                    "profile": label,
                    "server_day": server_day,
                    "calendar_day": first_day,
                    "status": "failed",
                }
                results.append(result)
                habit = None

                def rows():
                    return context.request.get(base + "/api/health").json()["entries"]

                def lose_post(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.ok, response.text()
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic lost acknowledgment"}',
                    )

                def choose():
                    with page.expect_file_chooser() as chooser:
                        page.locator("#health-import").click()
                    csv = f"date,kind,value,unit\n,weight,74.25,kg\n{server_day},sleep,8,h\n"
                    chooser.value.set_files(
                        {"name": "readings.csv", "mimeType": "text/csv", "buffer": csv.encode()}
                    )

                try:
                    assert context.request.post(base + "/api/setup/dismiss").ok
                    assert context.request.patch(
                        base + "/api/settings", data={"timezone": override}
                    ).ok
                    if case == "habit":
                        response = context.request.post(
                            base + "/api/habits",
                            data={"name": "calendar day fixture", "cadence": "daily"},
                        )
                        assert response.ok, response.text()
                        habit = response.json()
                    page.goto(
                        base + "/?view=" + ("habits" if habit else "health-log"),
                        wait_until="networkidle",
                    )
                    if case == "measurement":
                        endpoint = base + "/api/health"
                        page.locator("#health-add-toggle").click()
                        page.locator("#health-value").fill("74.25")
                        page.locator("#health-note").fill("first reading")
                        page.route(endpoint, lose_post)
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-error")).to_contain_text(
                            "save failed (503)"
                        )
                        expect(page.locator("#health-date")).to_have_value(first_day)
                        assert len(rows()) == 1 and rows()[0]["date"] == first_day
                        page.clock.set_fixed_time(instant + timedelta(days=1))
                        page.unroute(endpoint, lose_post)
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-form")).to_have_count(0)
                        assert len(rows()) == 1 and rows()[0]["date"] == first_day
                        assert (
                            posts[0]["request_id"] == posts[1]["request_id"]
                            and posts[0]["date"] == posts[1]["date"] == first_day
                        )
                        page.locator("#health-add-toggle").click()
                        page.locator("#health-value").fill("75.25")
                        page.locator("#health-note").fill("next reading")
                        page.locator("#health-create").press("Enter")
                        expect(page.locator("#health-entry-form")).to_have_count(0)
                        assert {row["note"]: row["date"] for row in rows()} == {
                            "first reading": first_day,
                            "next reading": next_day,
                        }
                        assert posts[2]["request_id"] != posts[0]["request_id"]
                    elif case == "import":
                        endpoint = base + "/api/health/import"
                        page.route(endpoint, lose_post)
                        choose()
                        expect(page.locator("#health-import-error")).to_contain_text(
                            "may already be saved"
                        )
                        assert {row["kind"]: row["date"] for row in rows()} == {
                            "weight": first_day,
                            "sleep": server_day,
                        }
                        page.clock.set_fixed_time(instant + timedelta(days=1))
                        page.unroute(endpoint, lose_post)
                        page.locator("#health-import-retry").press("Enter")
                        expect(page.locator("#health-import-form")).to_contain_text(
                            "already imported (2 entries)"
                        )
                        assert len(rows()) == 2
                        assert (
                            posts[0]["request_id"] == posts[1]["request_id"]
                            and posts[0]["default_date"] == posts[1]["default_date"] == first_day
                        )
                        page.locator("#health-import-close").press("Enter")
                        choose()
                        expect(page.locator("#health-import-form")).to_contain_text(
                            "imported 2 entries"
                        )
                        assert len(rows()) == 4
                        assert sorted(
                            row["date"] for row in rows() if row["kind"] == "weight"
                        ) == sorted([first_day, next_day])
                        assert all(
                            row["date"] == server_day for row in rows() if row["kind"] == "sleep"
                        )
                        assert (
                            posts[2]["request_id"] != posts[0]["request_id"]
                            and posts[2]["default_date"] == next_day
                        )
                    else:
                        card = page.locator(f'.habit-card[data-id="{habit["id"]}"]')
                        button = card.locator(f'[data-toggle="{first_day}"]')
                        button.press("Enter")
                        expect(button).to_have_class(re.compile(r"\bdone\b"))
                        expect(card.locator(".habit-heat i").last).to_have_attribute(
                            "title", first_day
                        )
                        page.reload(wait_until="networkidle")
                        expect(button).to_have_class(re.compile(r"\bdone\b"))
                        page.get_by_role("tab", name="overview", exact=True).click()
                        expect(
                            page.locator(".specialist-habit-row").filter(
                                has_text="calendar day fixture"
                            )
                        ).to_contain_text("done today")
                        page.clock.set_fixed_time(instant + timedelta(days=1))
                        page.get_by_role("tab", name="habits", exact=True).click()
                        expect(card.locator(f'[data-toggle="{next_day}"]')).not_to_have_class(
                            re.compile(r"\bdone\b")
                        )
                        expect(card.locator(f'[data-toggle="{first_day}"]')).to_have_class(
                            re.compile(r"\bdone\b")
                        )
                        expect(card.locator(".habit-heat i").last).to_have_attribute(
                            "title", next_day
                        )
                    page.reload(wait_until="networkidle")
                    if case != "habit":
                        expect(page.locator(".health-row")).to_have_count(
                            2 if case == "measurement" else 4
                        )
                        assert any("date_q=" + next_day in url for url in reads), reads
                    assert not errors, errors
                    assert len(console) == (0 if case == "habit" else 1) and all(
                        "503" in message for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    page.screenshot(path=str(output / (label + ".png")), full_page=True)
                    result["console_errors"] = console
                    for row in rows():
                        context.request.delete(base + "/api/health/" + str(row["id"]))
                    if habit:
                        context.request.delete(base + "/api/habits/" + habit["id"])
                    context.request.patch(base + "/api/settings", data={"timezone": ""})
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(results, indent=2))
        browser.close()
    print(json.dumps(results, indent=2))
    if any(row["status"] != "passed" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
