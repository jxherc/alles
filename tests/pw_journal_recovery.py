"""Owned Journal day-load and unsaved-draft recovery through the real UI."""

import json
import os
import re
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "failed-day",
    "initial-load",
    "draft-return",
    "loading-protection",
    "late-load",
    "save-before-day",
    "newer-edit",
    "lock-during-load",
)


def run(context_factory=None):
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 820, 390):
            for case in CASES:
                context = (
                    context_factory(pw, width)
                    if context_factory
                    else browser.new_context(
                        viewport={"width": width, "height": 900},
                        service_workers="block",
                        reduced_motion="reduce",
                    )
                )
                context.route(
                    "**/*",
                    lambda r: (
                        r.continue_()
                        if urlparse(r.request.url).netloc == urlparse(base).netloc
                        else r.abort()
                    ),
                )
                api = context.request
                page = context.new_page()
                page.set_default_timeout(5000)
                errors, console = [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.clock.install()
                context.tracing.start(screenshots=True, snapshots=True)
                first, second, third = "2026-09-25", "2026-09-26", "2026-09-27"
                content = {
                    day: f"owned entry {day} {width} {case}" for day in (first, second, third)
                }
                assert api.post(base + "/api/setup/dismiss").ok
                for day, value in content.items():
                    assert api.put(base + "/api/journal/" + day, data={"content": value}).ok
                editor = page.locator("#jrnl-text")
                saved = page.locator("#jrnl-saved")
                retry = page.locator("#jrnl-load-retry")

                def url(day):
                    return base + "/api/journal/" + day

                def stored(day):
                    response = api.get(url(day))
                    assert response.ok
                    return response.json()["content"]

                def reject(day, method):
                    page.route(
                        url(day),
                        lambda r: (
                            r.fulfill(status=503, json={"detail": "synthetic journal outage"})
                            if r.request.method == method
                            else r.continue_()
                        ),
                    )

                def hold(day, method="GET"):
                    page.evaluate(
                        """({target, method}) => {
                        const fetch = window.fetch.bind(window);
                        window.fetch = async (url, options) => {
                            const response = await fetch(url, options);
                            if (url === target && (options?.method || 'GET') === method && !window.held) {
                                window.held = true; await new Promise(r => window.releaseEntry = r);
                            }
                            return response;
                        };
                    }""",
                        {"target": "/api/journal/" + day, "method": method},
                    )

                def assert_day(day):
                    expect(editor).to_have_value(content[day])
                    expect(editor).to_be_enabled()
                    assert parse_qs(urlparse(page.url).query)["d"] == [day]

                try:
                    if case == "initial-load":
                        reject(first, "GET")
                    page.goto(base + "/?view=journal&d=" + first, wait_until="networkidle")
                    if case == "initial-load":
                        expect(retry).to_be_visible()
                        expect(editor).to_be_disabled()
                        expect(page.locator("#jrnl-save")).to_be_disabled()
                        assert stored(first) == content[first]
                        page.unroute(url(first))
                        retry.focus()
                        page.keyboard.press("Enter")
                        assert_day(first)
                        expect(editor).to_be_focused()
                    else:
                        assert_day(first)
                        if case == "failed-day":
                            reject(second, "GET")
                            page.locator("#jrnl-next").click()
                            expect(retry).to_be_visible()
                            assert_day(first)
                            expect(page.locator("#jrnl-load-message")).to_contain_text(
                                "previous entry"
                            )
                            page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                            with page.expect_response(
                                lambda r: r.url == url(first) and r.request.method == "PUT"
                            ):
                                page.locator("#jrnl-save").click()
                            assert stored(second) == content[second]
                            page.unroute(url(second))
                            retry.focus()
                            page.keyboard.press("Enter")
                            assert_day(second)
                            expect(editor).to_be_focused()
                        elif case == "newer-edit":
                            hold(first, "PUT")
                            editor.fill("earlier local edit")
                            page.clock.fast_forward(1500)
                            page.wait_for_function("window.held")
                            editor.fill("newer local edit")
                            page.evaluate("window.releaseEntry()")
                            expect(saved).to_have_text("unsaved changes")
                            assert stored(first) == "earlier local edit"
                            page.clock.fast_forward(1500)
                            expect(saved).to_have_text(re.compile(r"^saved "))
                            assert stored(first) == "newer local edit"
                        elif case == "lock-during-load":
                            page.locator("#jrnl-lock").click()
                            page.locator("#jl-new").fill("journal-fixture-long")
                            page.locator("#jl-new2").fill("journal-fixture-long")
                            page.locator("#jl-go").click()
                            assert_day(first)
                            expect(page.locator("#jrnl-lock")).to_contain_text("lock options")
                            hold(second)
                            page.locator("#jrnl-next").click()
                            page.wait_for_function("window.held")
                            page.locator("#jrnl-lock").click()
                            page.locator('.jrnl-lockmenu [data-a="lock"]').click()
                            expect(page.locator("#jl-old")).to_be_visible()
                            page.evaluate("window.releaseEntry()")
                            expect(editor).to_have_count(0)
                            page.locator("#jl-old").fill("journal-fixture-long")
                            page.locator("#jl-go").click()
                            assert_day(second)
                        elif case in {"loading-protection", "late-load"}:
                            hold(second)
                            page.locator("#jrnl-next").click()
                            page.wait_for_function("window.held")
                            expect(editor).to_be_disabled()
                            expect(page.locator("#jrnl-save")).to_be_disabled()
                            expect(saved).to_contain_text("loading")
                            if case == "late-load":
                                page.locator("#jrnl-next").click()
                                assert_day(third)
                            page.evaluate("window.releaseEntry()")
                            assert_day(third if case == "late-load" else second)
                            assert stored(second) == content[second]
                        else:
                            reject(first, "PUT")
                            draft = f"exact unsaved draft {width} {case}\n\nlast line  "
                            editor.fill(draft)
                            with page.expect_response(
                                lambda r: r.url == url(first) and r.request.method == "PUT"
                            ):
                                page.clock.fast_forward(1500)
                            expect(saved).to_contain_text("could not save")
                            expect(editor).to_have_value(draft)
                            page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                            if case == "draft-return":
                                page.clock.fast_forward(31000)
                                page.locator(
                                    '#docs-workbench-view [data-group-section="notes"]'
                                ).click()
                                expect(page.locator("#docs-journal-section")).to_be_hidden()
                                page.locator(
                                    '#docs-workbench-view [data-group-section="journal"]'
                                ).click()
                                expect(editor).to_have_value(draft)
                                expect(saved).to_contain_text("could not save")
                            else:
                                page.locator("#jrnl-next").click()
                                expect(editor).to_have_value(draft)
                                assert parse_qs(urlparse(page.url).query)["d"] == [first]
                            assert stored(first) == content[first]
                            page.unroute(url(first))
                            page.locator("#jrnl-save").click()
                            expect(saved).to_have_text(re.compile(r"^saved "))
                            assert stored(first) == draft
                            page.locator("#jrnl-next").click()
                            assert_day(second)
                    rendered = page.evaluate(
                        "() => ({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth+1,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches})"
                    )
                    assert not errors, errors
                    assert not rendered["overflow"] and rendered["reduced"], rendered
                    assert not [
                        line for line in console if "Failed to load resource" not in line
                    ], console
                    rows.append(
                        {
                            "scenario_id": "journal.recovery." + case,
                            "profile": str(width),
                            "status": "passed",
                            "rendered": rendered,
                            "console": console,
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "journal.recovery." + case,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    if case == "lock-during-load":
                        assert api.post(
                            base + "/api/journal/lock/disable",
                            data={"passcode": "journal-fixture-long"},
                        ).ok
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    print(json.dumps(rows))
    if any(row["status"] != "passed" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
