"""Owned Journal search, keyboard opening and current-draft export recovery."""

import json
import os
import re
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

CASES = (
    "normal",
    "search-error",
    "search-late",
    "search-clear",
    "search-lock",
    "export-draft",
    "export-error",
    "export-save-error",
    "export-malformed",
    "export-newer-edit",
    "export-lock",
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
                        accept_downloads=True,
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
                page = context.new_page()
                page.set_default_timeout(5000)
                page.clock.install()
                api = context.request
                errors, console, downloads, exports = [], [], [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.on("download", lambda download: downloads.append(download))
                page.on(
                    "request",
                    lambda r: (
                        exports.append(r.url) if r.url.endswith("/api/journal/export") else None
                    ),
                )
                context.tracing.start(screenshots=True, snapshots=True)
                first, second = "2026-09-21", "2026-09-22"
                content = {
                    first: "needle entry for exact search",
                    second: "different journal entry",
                }
                assert api.post(base + "/api/setup/dismiss").ok
                for day, value in content.items():
                    assert api.put(
                        base + "/api/journal/" + day, data={"content": value, "tags": "owned"}
                    ).ok
                editor = page.locator("#jrnl-text")
                search = page.locator("#jrnl-search")
                box = page.locator("#jrnl-results")
                export = page.locator("#jrnl-export")
                status = page.locator("#jrnl-export-status")
                locked = False

                def query(value):
                    search.fill(value)
                    page.clock.fast_forward(300)

                def hold(target, method="GET"):
                    page.evaluate(
                        """({target, method}) => {
                        const real = window.fetch.bind(window);
                        window.fetch = async (url, options) => {
                            const response = await real(url, options);
                            if (url === target && (options?.method || 'GET') === method && !window.held) {
                                window.held = true;
                                await new Promise(r => window.releaseHeld = r);
                                const json = response.json.bind(response);
                                response.json = async () => {const value = await json(); window.heldParsed = true; return value;};
                            }
                            return response;
                        };
                    }""",
                        {"target": target, "method": method},
                    )

                def release():
                    page.evaluate("window.releaseHeld()")
                    page.wait_for_function("window.heldParsed")

                def download_current(text):
                    with page.expect_download() as downloaded:
                        export.focus()
                        page.keyboard.press("Enter")
                    expect(status).to_have_text("journal export downloaded")
                    result = downloaded.value
                    assert result.suggested_filename == "journal.md"
                    assert text in Path(result.path()).read_text()
                    expect(export).to_be_focused()
                    return Path(result.path()).read_text()

                def lock_now():
                    page.locator("#jrnl-lock").click()
                    page.locator('.jrnl-lockmenu [data-a="lock"]').click()
                    expect(page.locator("#jl-old")).to_be_visible()

                try:
                    page.goto(base + "/?view=journal&d=" + first, wait_until="networkidle")
                    expect(editor).to_have_value(content[first])
                    if case.endswith("-lock"):
                        page.locator("#jrnl-lock").click()
                        page.locator("#jl-new").fill("journal-fixture-long")
                        page.locator("#jl-new2").fill("journal-fixture-long")
                        page.locator("#jl-go").click()
                        expect(editor).to_have_value(content[first])
                        expect(page.locator("#jrnl-lock")).to_contain_text("lock options")
                        locked = True
                    if case == "normal":
                        query("different")
                        result = box.get_by_role("button")
                        expect(result).to_contain_text(second)
                        page.locator("#jrnl-lock").focus()
                        page.keyboard.press("Tab")
                        expect(result).to_be_focused()
                        page.keyboard.press("Enter")
                        expect(editor).to_have_value(content[second])
                        expect(editor).to_be_focused()
                        assert parse_qs(urlparse(page.url).query)["d"] == [second]
                        editor.fill("edited after finding exact day")
                        page.clock.fast_forward(1250)
                        expect(page.locator("#jrnl-saved")).to_have_text(re.compile(r"^saved "))
                        download_current("edited after finding exact day")
                        page.reload(wait_until="networkidle")
                        expect(editor).to_have_value("edited after finding exact day")
                    elif case == "search-error":
                        query("needle")
                        expect(box).to_contain_text(first)
                        target = base + "/api/journal/search?q=different"
                        page.route(
                            target,
                            lambda r: r.fulfill(status=503, json={"detail": "synthetic outage"}),
                        )
                        query("different")
                        expect(box).to_contain_text("could not search")
                        expect(box).not_to_contain_text(first)
                        page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                        page.unroute(target)
                        hold("/api/journal/search?q=different")
                        retry = box.get_by_role("button", name="retry search")
                        retry.focus()
                        page.keyboard.press("Enter")
                        page.wait_for_function("window.held")
                        expect(retry).to_be_focused()
                        expect(retry).to_have_attribute("aria-disabled", "true")
                        release()
                        expect(box.get_by_role("button")).to_contain_text(second)
                        expect(box.get_by_role("button")).to_be_focused()
                        page.keyboard.press("Enter")
                        expect(editor).to_have_value(content[second])
                        expect(editor).to_be_focused()
                    elif case.startswith("search-"):
                        hold("/api/journal/search?q=needle")
                        query("needle")
                        page.wait_for_function("window.held")
                        if case == "search-late":
                            query("different")
                            expect(box).to_contain_text(second)
                        elif case == "search-clear":
                            query("")
                            expect(box).to_be_empty()
                        else:
                            lock_now()
                        release()
                        if case == "search-late":
                            expect(box).to_contain_text(second)
                            expect(box).not_to_contain_text(first)
                        elif case == "search-clear":
                            expect(box).to_be_empty()
                        else:
                            expect(box).to_have_count(0)
                            expect(editor).to_have_count(0)
                    elif case == "export-lock":
                        hold("/api/journal/export")
                        export.click()
                        page.wait_for_function("window.held")
                        lock_now()
                        release()
                        assert not downloads
                        page.locator("#jl-old").fill("journal-fixture-long")
                        page.locator("#jl-go").click()
                        expect(editor).to_have_value(content[first])
                        download_current(content[first])
                    elif case == "export-newer-edit":
                        hold("/api/journal/" + first, "PUT")
                        editor.fill("first edited snapshot")
                        export.click()
                        page.wait_for_function("window.held")
                        expect(export).to_have_attribute("aria-disabled", "true")
                        assert not exports and not downloads
                        editor.fill("newer edit while preparing export")
                        with page.expect_download() as downloaded:
                            release()
                        assert (
                            "newer edit while preparing export"
                            in Path(downloaded.value.path()).read_text()
                        )
                        assert len(exports) == 1 and len(downloads) == 1
                        assert (
                            api.get(base + "/api/journal/" + first).json()["content"]
                            == "newer edit while preparing export"
                        )
                    elif case == "export-draft":
                        editor.fill("newest draft must reach export")
                        page.locator("#jrnl-tags").fill("current tag")
                        data = download_current("newest draft must reach export")
                        assert "current tag" in data
                        assert (
                            api.get(base + "/api/journal/" + first).json()["content"]
                            == "newest draft must reach export"
                        )
                    else:
                        save_failure = case == "export-save-error"
                        target = (
                            base + "/api/journal/" + first
                            if save_failure
                            else base + "/api/journal/export"
                        )
                        if save_failure:
                            editor.fill("retained draft on rejected export save")
                        page.route(
                            target,
                            lambda r: (
                                r.fulfill(status=200, json={})
                                if case == "export-malformed"
                                else r.fulfill(status=503, json={"detail": "synthetic outage"})
                            ),
                        )
                        export.focus()
                        page.keyboard.press("Enter")
                        expect(status).to_contain_text("could not export")
                        expect(export).to_be_focused()
                        assert not downloads
                        if save_failure:
                            assert not exports
                            expect(editor).to_have_value("retained draft on rejected export save")
                            assert api.get(target).json()["content"] == content[first]
                        page.screenshot(path=str(out / f"{width}-{case}-error.png"))
                        page.unroute(target)
                        download_current(
                            "retained draft on rejected export save"
                            if save_failure
                            else content[first]
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
                            "scenario_id": "journal.search-export." + case,
                            "profile": str(width),
                            "status": "passed",
                            "rendered": rendered,
                            "console": console,
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "journal.search-export." + case,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
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
