"""Taps to log the most common entry per habit, counted on the real screens (ux laws, c.05).

a done check is 1 tap, a repeat gym set 1 tap (prefilled, confirm), a changed weight 2, and a
count, reading, duration or distance day 2 (open, prefilled from the last day, save). run through
the gate runner, which owns the server and its throwaway data.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    old_day = (today - timedelta(days=20)).isoformat()  # the strip two weeks back
    rows = []
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        for width, height in [(1180, 820), (390, 844)]:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                timezone_id="America/Toronto",
                service_workers="block",
                reduced_motion="reduce",
            )
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            for row in api.get(base + "/api/habits/overview").json()["habits"]:
                assert api.delete(base + "/api/habits/" + row["id"]).ok

            def habit(body, logs=()):
                made = api.post(base + "/api/habits", data=body).json()
                for day, data in logs:
                    assert api.post(
                        base + f"/api/habits/{made['id']}/toggle", data={"date": day, "data": data}
                    ).ok
                return made

            check = habit({"name": "stretch"})
            sets = [{"weight": 60, "unit": "lb", "reps": 10, "status": "done", "count": 1}]
            gym = habit(
                {"name": "workout", "kind": "workout"},
                [
                    (
                        today.isoformat(),
                        {
                            "v": 2,
                            "entries": [{"values": {"exercises": [{"name": "row", "sets": sets}]}}],
                        },
                    ),
                    (
                        old_day,
                        {
                            "v": 2,
                            "entries": [
                                {
                                    "values": {
                                        "muscles": ["chest"],
                                        "exercises": [{"name": "old press", "sets": sets}],
                                    }
                                },
                                {
                                    "note": "arms after a break",
                                    "values": {
                                        "muscles": ["arm"],
                                        "exercises": [{"name": "old curl", "sets": sets}],
                                    },
                                },
                            ],
                        },
                    ),
                ],
            )
            loggers = {
                "count": habit(
                    {"name": "water", "kind": "count", "unit": "glasses"},
                    [(yesterday, {"amount": 6})],
                ),
                "reading": habit(
                    {"name": "read", "kind": "reading"},
                    [(yesterday, {"amount": 24, "unit": "pages", "book": "dune"})],
                ),
                "duration": habit(
                    {"name": "meditate", "kind": "duration"}, [(yesterday, {"minutes": 15})]
                ),
                "distance": habit(
                    {"name": "run", "kind": "distance"},
                    [(yesterday, {"distance": 5, "unit": "km", "minutes": 28})],
                ),
            }
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            taps = {"n": 0}

            def tap(locator):
                taps["n"] += 1
                locator.click()

            def counted(name, steps, expected):
                taps["n"] = 0
                try:
                    steps()
                except Exception:
                    page.screenshot(path=str(output / f"failed-{width}.png"), full_page=True)
                    raise
                rows.append(
                    {"entry": name, "width": width, "taps": taps["n"], "expected": expected}
                )
                assert taps["n"] <= expected, rows[-1]

            def logs(item):
                found = next(
                    h
                    for h in api.get(base + "/api/habits/overview").json()["habits"]
                    if h["id"] == item["id"]
                )
                return found.get("days", {}), found.get("logs", {})

            page.goto(base + "/?view=habits", wait_until="networkidle")
            row = page.locator(f'.habit-row[data-id="{check["id"]}"]')

            def done_check():
                tap(row.locator(".habit-today"))
                expect(row.locator(".habit-today")).to_have_attribute("aria-pressed", "true")

            counted("check, done today", done_check, 1)

            # the gym logger: open the habit (not counted: it's where the logger lives)
            page.locator(f'.habit-row[data-id="{gym["id"]}"] [data-act="open"]').click()
            log = page.locator(".gym-log-btn")
            expect(log).to_be_visible()
            listed = page.locator(".gym-set")

            def repeat_set():
                before = listed.count()
                tap(log)
                expect(listed).to_have_count(before + 1)

            counted("gym, repeat set", repeat_set, 1)

            def changed_weight():
                before = listed.count()
                tap(page.locator('.gym-editor .k-stepper[data-key="weight"] [data-d="1"]').first)
                tap(log)
                expect(listed).to_have_count(before + 1)

            counted("gym, changed weight", changed_weight, 2)
            days, _ = logs(gym)
            weights = [
                s.get("weight")
                for e in days[today.isoformat()]["entries"]
                for x in e["values"]["exercises"]
                for s in x["sets"]
            ]
            assert weights == [60, 60, 65], weights

            # an older session opens from the strip's earlier week arrow, never typed
            def old_session():
                later = page.locator('[data-week="-1"]')
                expect(later).to_be_disabled()
                for _ in range(2):
                    tap(page.locator('[data-week="1"]'))
                expect(later).to_be_enabled()
                tap(page.locator(f'.habit-day[data-toggle="{old_day}"]'))
                expect(page.locator(".gym-host")).to_contain_text("old press")

            counted("gym, a session 20 days back", old_session, 3)
            # two sessions that day: both show, with their note, and a set goes to its own one
            host = page.locator(".gym-host")
            expect(host).to_contain_text("old curl")
            expect(page.locator(".gym-session-name")).to_have_text(["chest", "arm"])
            expect(page.locator(".gym-session-note")).to_have_text("arms after a break")
            before = listed.count()
            log.click()  # the last exercise, old curl, is the open one
            expect(listed).to_have_count(before + 1)
            page.locator('.gym-ex[data-ex="0"] [data-gym="activate"]').click()
            page.locator(".gym-log-btn").click()
            expect(listed).to_have_count(before + 2)
            page.wait_for_timeout(500)
            cards = api.get(base + f"/api/habits/overview?date_q={old_day}").json()["habits"]
            entries = next(c for c in cards if c["id"] == gym["id"])["days"][old_day]["entries"]
            names = [
                [(x["name"], len(x["sets"])) for x in e["values"]["exercises"]] for e in entries
            ]
            assert names == [[("old press", 2)], [("old curl", 2)]], names
            assert entries[1]["note"] == "arms after a break", entries[1]
            page.locator('[data-act="back"]').click()

            for kind, item in loggers.items():
                # the row's today opens the habit on today's log, like every other kind; the
                # form starts from yesterday, so log is the second and last tap
                def prefilled(item=item):
                    tap(page.locator(f'.habit-row[data-id="{item["id"]}"] .habit-today'))
                    tap(page.locator(".dlog-log"))
                    expect(page.locator(".dlog-entry")).to_have_count(1)
                    expect(
                        page.locator(f'.habit-day[data-toggle="{today.isoformat()}"]')
                    ).to_have_attribute("aria-pressed", "true")

                counted(f"{kind}, same as last time", prefilled, 2)
                page.wait_for_timeout(300)
                _, saved = logs(item)
                assert saved.get(today.isoformat()) == saved.get(yesterday), (kind, saved)
                page.locator('[data-act="back"]').click()
            # every other kind: its own day log, built from its fields. today starts from the last
            # entry, so "same as last time" is one tap on log (open is where the logger lives)
            if width == 1180:
                kinds = api.get(base + "/api/habits/kinds").json()["kinds"]
                legacy = {"check", "count", "duration", "distance", "workout", "reading"}
                seeded = {
                    kind: habit(
                        {"name": kind, "kind": kind},
                        [(yesterday, {"v": 2, "entries": [{"values": {}, "note": "as usual"}]})],
                    )
                    for kind in kinds
                    if kind not in legacy
                }
                page.goto(base + "/?view=habits", wait_until="networkidle")
                for kind, own in seeded.items():
                    page.locator(f'.habit-row[data-id="{own["id"]}"] [data-act="open"]').click()
                    expect(page.locator(".dlog-form")).to_be_visible()

                    def same_as_last_time():
                        tap(page.locator(".dlog-log"))
                        expect(page.locator(".dlog-entry")).to_have_count(1)

                    counted(f"{kind}, same as last time", same_as_last_time, 1)
                    page.wait_for_timeout(300)
                    days, _ = logs(own)
                    assert days.get(today.isoformat(), {}).get("entries"), (kind, days)
                    page.locator('[data-act="back"]').click()
            page.screenshot(path=str(output / f"taps-{width}.png"), full_page=True)
            assert not errors, errors
            context.close()
        browser.close()
    (output / "taps.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    run()
