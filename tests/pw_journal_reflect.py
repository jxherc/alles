"""Journal reflection ownership using synthetic localhost replies, without a model."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "normal",
    "failed-save",
    "failed-reflect",
    "malformed-reflect",
    "changed-day",
    "changed-text",
    "changed-during-save",
    "locked",
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
                page.clock.install()
                context.tracing.start(screenshots=True, snapshots=True)
                errors, console, requests = [], [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                fail_response = case in {"failed-reflect", "malformed-reflect"}

                def respond(route):
                    requests.append(route.request.url)
                    if fail_response:
                        route.fulfill(
                            status=503 if case == "failed-reflect" else 200,
                            json={"detail": "synthetic model unavailable"}
                            if case == "failed-reflect"
                            else {},
                        )
                    else:
                        route.fulfill(
                            status=200,
                            json={"reflection": "**synthetic reflection** for this entry"},
                        )

                page.route("**/api/journal/*/reflect", respond)
                first, second = "2026-09-18", "2026-09-19"
                assert api.post(base + "/api/setup/dismiss").ok
                for day in (first, second):
                    assert api.put(
                        base + "/api/journal/" + day, data={"content": "entry " + day}
                    ).ok
                editor = page.locator("#jrnl-text")
                button = page.locator("#jrnl-reflect")
                box = page.locator("#jrnl-reflection")
                locked = False

                def hold(target, method):
                    page.evaluate(
                        """({target, method}) => {
                        const real = window.fetch.bind(window);
                        window.fetch = async (url, options) => {
                            const response = await real(url, options);
                            if (url === target && (options?.method || 'GET') === method && !window.held) {
                                const payload = await response.clone().json();
                                window.held = true;
                                await new Promise(r => window.releaseHeld = r);
                                response.json = async () => payload;
                                window.delivered = true;
                            }
                            return response;
                        };
                    }""",
                        {"target": target, "method": method},
                    )

                def release():
                    page.evaluate("window.releaseHeld()")
                    page.wait_for_function("window.delivered")

                def reflect():
                    button.focus()
                    page.keyboard.press("Enter")

                def success():
                    expect(box.locator("strong")).to_have_text("synthetic reflection")
                    expect(button).to_be_focused()
                    expect(button).not_to_have_attribute("aria-disabled", "true")

                try:
                    page.goto(base + "/?view=journal&d=" + first, wait_until="networkidle")
                    expect(editor).to_have_value("entry " + first)
                    if case == "locked":
                        page.locator("#jrnl-lock").click()
                        page.locator("#jl-new").fill("journal-fixture-long")
                        page.locator("#jl-new2").fill("journal-fixture-long")
                        page.locator("#jl-go").click()
                        expect(editor).to_have_value("entry " + first)
                        expect(page.locator("#jrnl-lock")).to_contain_text("lock options")
                        locked = True
                    if case == "normal":
                        editor.fill("current draft for reflection")
                        reflect()
                        success()
                        assert (
                            api.get(base + "/api/journal/" + first).json()["content"]
                            == "current draft for reflection"
                        )
                        assert len(requests) == 1 and requests[0].endswith(first + "/reflect")
                        editor.fill("later edit after completed reflection")
                        expect(box).to_have_text("entry changed. choose reflect again.")
                        expect(box.locator("strong")).to_have_count(0)
                    elif case == "failed-save":
                        target = base + "/api/journal/" + first
                        page.route(
                            target,
                            lambda r: (
                                r.fulfill(status=503, json={"detail": "synthetic save outage"})
                                if r.request.method == "PUT"
                                else r.continue_()
                            ),
                        )
                        editor.fill("draft retained before reflection")
                        reflect()
                        expect(box).to_contain_text("could not reflect: save failed")
                        expect(button).to_be_focused()
                        assert not requests
                        assert api.get(target).json()["content"] == "entry " + first
                        expect(editor).to_have_value("draft retained before reflection")
                        box.scroll_into_view_if_needed()
                        page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                        page.unroute(target)
                        reflect()
                        success()
                        assert (
                            api.get(target).json()["content"] == "draft retained before reflection"
                        )
                        assert len(requests) == 1
                    elif case in {"failed-reflect", "malformed-reflect"}:
                        reflect()
                        expect(box).to_contain_text("could not reflect")
                        expect(button).to_be_focused()
                        box.scroll_into_view_if_needed()
                        page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                        fail_response = False
                        reflect()
                        success()
                        assert len(requests) == 2
                    else:
                        during_save = case == "changed-during-save"
                        hold(
                            "/api/journal/" + first + ("" if during_save else "/reflect"),
                            "PUT" if during_save else "POST",
                        )
                        if during_save:
                            editor.fill("first edit before reflection")
                        reflect()
                        page.wait_for_function("window.held")
                        expect(button).to_be_focused()
                        expect(button).to_have_attribute("aria-disabled", "true")
                        page.keyboard.press("Enter")
                        assert len(requests) == (0 if during_save else 1)
                        if case == "changed-day":
                            page.locator("#jrnl-next").click()
                            expect(editor).to_have_value("entry " + second)
                        elif case == "locked":
                            page.locator("#jrnl-lock").click()
                            page.locator('.jrnl-lockmenu [data-a="lock"]').click()
                            expect(page.locator("#jl-old")).to_be_visible()
                        else:
                            editor.fill("newer entry while reflection was pending")
                        release()
                        if case == "locked":
                            expect(box).to_have_count(0)
                            expect(editor).to_have_count(0)
                            page.locator("#jl-old").fill("journal-fixture-long")
                            page.locator("#jl-go").click()
                            expect(editor).to_have_value("entry " + first)
                        elif case == "changed-day":
                            expect(box).to_be_hidden()
                            expect(box).not_to_contain_text("synthetic reflection")
                        else:
                            expect(box).to_have_text("entry changed. choose reflect again.")
                            if during_save:
                                assert not requests
                        reflect()
                        success()
                        expected_day = second if case == "changed-day" else first
                        assert requests[-1].endswith(expected_day + "/reflect")
                        if case in {"changed-text", "changed-during-save"}:
                            assert (
                                api.get(base + "/api/journal/" + first).json()["content"]
                                == "newer entry while reflection was pending"
                            )
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
                            "scenario_id": "journal.reflect." + case,
                            "profile": str(width),
                            "status": "passed",
                            "rendered": rendered,
                            "console": console,
                            "synthetic_reflection_requests": requests,
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "journal.reflect." + case,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    box.scroll_into_view_if_needed() if box.count() and box.is_visible() else None
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    if locked:
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
