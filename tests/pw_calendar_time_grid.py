"""timed events in the day and week grid: tab reaches them in time order, enter and space open
them, escape comes back to the same event, the box keeps the event's real length, and a short
event still has a 44px tap area that never covers a neighbour's box or the empty slots beyond it.

runs against an owned throwaway server like the other gates: PORT and ALLES_TEST_RUN_ID come
from the gate runner.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

EVENTS = [
    ("GRID_Q1", "09:00", "09:15"),
    ("GRID_Q2", "09:15", "09:30"),  # adjacent 15-minute events sit side by side
    ("GRID_SHORT", "11:00", "11:15"),
    ("GRID_LONG", "13:00", "14:30"),
    ("GRID_A", "15:00", "15:30"),
    ("GRID_B", "15:30", "16:00"),  # stacked right under A
]
# the browser's zone is pinned and "today" is counted there, whatever zone the runner has
ZONE = "America/Toronto"
PROFILES = [
    ("chromium", {"width": 1440, "height": 900}, False),
    ("chromium", {"width": 390, "height": 844}, True),
    ("webkit", {"width": 820, "height": 1180}, True),
]


def main():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    today = datetime.now(ZoneInfo(ZONE)).date().isoformat()
    with sync_playwright() as p:
        api = p.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        ids = {}
        for title, start, end in EVENTS:
            made = api.post(
                "/api/calendar",
                data={"title": title, "start_dt": f"{today}T{start}", "end_dt": f"{today}T{end}"},
            )
            ids[title] = made.json()["id"]
        titles = {v: k for k, v in ids.items()}

        for engine, viewport, touch in PROFILES:
            where = f"{engine} {viewport['width']}"
            browser = getattr(p, engine).launch()
            ctx = browser.new_context(
                viewport=viewport,
                has_touch=touch,
                is_mobile=touch and engine == "chromium",
                service_workers="block",
                timezone_id=ZONE,
            )
            ctx.add_init_script("try { localStorage.setItem('cal-view', 'day') } catch {}")
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(base + "/?view=calendar", wait_until="networkidle")
            pg.wait_for_selector(".cal-tev[data-id]")

            def box(title, scroll=True):
                return pg.evaluate(
                    """([id, scroll]) => { const e = document.querySelector(`.cal-tev[data-id="${id}"]`);
                    if (scroll) e.scrollIntoView({ block: 'center' });
                    const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, top: r.y, h: r.height }; }""",
                    [ids[title], scroll],
                )

            def tap(x, y):
                if touch:
                    pg.touchscreen.tap(x, y)
                else:
                    pg.mouse.click(x, y)
                pg.wait_for_timeout(300)
                opened = pg.evaluate(
                    """() => { const t = document.getElementById('cal-title'); if (!t) return null;
                    return document.getElementById('cal-save').textContent.trim() === 'create' ? 'new' : t.value; }"""
                )
                # a keyboard lands after the title; a touch screen focuses the editor's heading so
                # no keyboard pops over the event
                focus = pg.evaluate(
                    """() => { const a = document.activeElement;
                    return a.id === 'cal-title' ? (a.selectionStart === a.value.length ? 'title end' : 'title')
                      : a.id === 'cal-ed-head' ? 'heading' : a.tagName; }"""
                )
                want = "heading" if touch else "title end"
                assert opened is None or focus == want, f"{where}: editor focus {focus}"
                if opened:
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(300)
                return opened

            # the box is as long as the event (30 minutes at least), not kokuen's 44px
            assert abs(box("GRID_SHORT")["h"] - 20) < 1, box("GRID_SHORT")
            assert abs(box("GRID_LONG")["h"] - 64) < 1, box("GRID_LONG")

            q1 = box("GRID_Q1")
            assert tap(q1["x"], q1["top"] + 10) == "GRID_Q1", where
            q2 = box("GRID_Q2")
            assert tap(q2["x"], q2["top"] + 10) == "GRID_Q2", where
            s = box("GRID_SHORT")
            assert tap(s["x"], s["top"] + 10) == "GRID_SHORT", where
            s = box("GRID_SHORT")
            assert tap(s["x"], s["top"] - 9) == "GRID_SHORT", f"{where}: just above a short event"
            s = box("GRID_SHORT")
            assert tap(s["x"], s["top"] + s["h"] + 9) == "GRID_SHORT", f"{where}: just below"
            s = box("GRID_SHORT")
            assert tap(s["x"], s["top"] - 24) == "new", f"{where}: the empty slot above creates"
            s = box("GRID_SHORT")
            assert tap(s["x"], s["top"] + s["h"] + 40) == "new", f"{where}: the slot below creates"
            a = box("GRID_A")
            b = box("GRID_B", scroll=False)
            assert abs(b["top"] - (a["top"] + a["h"]) - 2) < 1, (a, b)
            # each box wins over the neighbour's tap area that reaches into it
            assert tap(a["x"], a["top"] + a["h"] - 3) == "GRID_A", where
            b = box("GRID_B")
            assert tap(b["x"], b["top"] + 3) == "GRID_B", where

            # keyboard: tab walks the events in time order
            pg.evaluate("() => document.getElementById('cal-today').focus()")
            seen = []
            for _ in range(60):
                pg.keyboard.press("Tab")
                eid = pg.evaluate(
                    "() => document.activeElement.matches('.cal-tev') ? document.activeElement.dataset.id : null"
                )
                if eid in titles and titles[eid] not in seen:
                    seen.append(titles[eid])
                if len(seen) == len(EVENTS):
                    break
            assert seen == [t for t, _, _ in EVENTS], f"{where}: tab order {seen}"

            pg.evaluate("() => document.activeElement.blur()")
            rest = pg.evaluate(
                "() => [...document.querySelectorAll('.cal-tev, .cal-tev-box')].map(e => JSON.stringify(e.getBoundingClientRect()))"
            )
            pg.evaluate(
                '(id) => document.querySelector(`.cal-tev[data-id="${id}"]`).focus({ preventScroll: true })',
                ids["GRID_Q2"],
            )
            name = pg.evaluate("() => document.activeElement.getAttribute('aria-label')")
            assert name.startswith("GRID_Q2, ") and " – " in name, name
            ring = pg.evaluate(
                "() => { const s = getComputedStyle(document.activeElement, '::before'); return [s.outlineWidth, s.top, s.zIndex]; }"
            )
            assert ring == ["2px", "-1px", "3"], f"{where}: focus ring {ring}"
            focused = pg.evaluate(
                "() => [...document.querySelectorAll('.cal-tev, .cal-tev-box')].map(e => JSON.stringify(e.getBoundingClientRect()))"
            )
            assert rest == focused, f"{where}: focus moved the layout"

            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.getElementById('cal-title')?.value") == "GRID_Q2"
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)
            back = pg.evaluate(
                "() => [document.activeElement.dataset.id, !!document.getElementById('cal-title')]"
            )
            assert back == [ids["GRID_Q2"], False], f"{where}: escape left focus on {back}"
            pg.keyboard.press(" ")
            pg.wait_for_timeout(300)
            assert pg.evaluate("() => document.getElementById('cal-title')?.value") == "GRID_Q2"
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(300)

            if viewport["width"] < 600:
                # a narrow week can't fit events side by side: an overlap group is one stack
                pg.click('#cal-view [data-view="week"]')
                pg.wait_for_selector(".cal-tstack")
                stack = pg.evaluate(
                    """() => { const s = document.querySelector('.cal-tstack'); s.scrollIntoView({ block: 'center' });
                    const r = s.getBoundingClientRect(), a = getComputedStyle(s, '::after');
                    return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width,
                      hit: r.width - parseFloat(a.left) - parseFloat(a.right), label: s.getAttribute('aria-label'),
                      first: s.dataset.first }; }"""
                )
                assert stack["w"] >= 40 and stack["hit"] >= 43.5, stack  # 44 less subpixel rounding
                assert stack["label"].startswith("2 events, "), stack
                assert stack["first"] == ids["GRID_Q1"], stack
                alone = pg.evaluate(
                    '(id) => !!document.querySelector(`.cal-tev[data-id="${id}"]`)',
                    ids["GRID_SHORT"],
                )
                assert alone, f"{where}: an event on its own keeps its box"
                pg.touchscreen.tap(stack["x"], stack["y"])
                pg.wait_for_timeout(400)
                assert pg.evaluate("() => localStorage.getItem('cal-view')") == "day", where
                assert pg.evaluate(
                    "(id) => document.activeElement.dataset.id === id", ids["GRID_Q1"]
                )

            if not touch:
                # the tap area doesn't get in the way of dragging the box itself
                drag = api.post(
                    "/api/calendar",
                    data={
                        "title": "GRID_DRAG",
                        "start_dt": f"{today}T20:00",
                        "end_dt": f"{today}T20:15",
                    },
                ).json()["id"]
                pg.reload(wait_until="networkidle")
                pg.wait_for_selector(f'.cal-tev[data-id="{drag}"]')
                ids["GRID_DRAG"] = drag
                d = box("GRID_DRAG")
                pg.mouse.move(d["x"], d["top"] + 5)  # the bottom 6px resize instead
                pg.mouse.down()
                pg.mouse.move(d["x"], d["top"] + 30, steps=5)
                pg.mouse.move(d["x"], d["top"] + 49, steps=5)
                pg.mouse.up()
                pg.wait_for_timeout(800)
                moved = next(e for e in api.get("/api/calendar").json() if e["id"] == drag)
                # an hour later and still 15 minutes long, though its box draws 30
                assert (moved["start_dt"], moved["end_dt"]) == (
                    f"{today}T21:00",
                    f"{today}T21:15",
                ), moved
                assert pg.evaluate("() => !document.getElementById('cal-title')"), (
                    "a drag opened it"
                )
            assert not errors, errors
            browser.close()
            print(f"PASS: {where}")

        for eid in ids.values():
            api.delete(f"/api/calendar/{eid}")
    print("PASS: timed events open by tap and keyboard, keep their length and their 44px")


if __name__ == "__main__":
    main()
