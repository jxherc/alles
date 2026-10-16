"""Keyboard-first Andromeda result actions with mocked search/model transports.

Library writes use the owned app and database. No provider, source, or model
network request leaves the isolated browser gate.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy

SIMULATION = "mocked search/model HTTP; real Andromeda UI, clipboard, Library API, and database"


async def search_chrome(page):
    return await page.locator("#andromeda-form").evaluate(
        """form => {
          const input = form.querySelector('#andromeda-query');
          const formStyle = getComputedStyle(form);
          const inputStyle = getComputedStyle(input);
          const focusRail = getComputedStyle(form, '::before');
          return {
            borderTopWidth: formStyle.borderTopWidth,
            borderRightWidth: formStyle.borderRightWidth,
            borderBottomWidth: formStyle.borderBottomWidth,
            borderLeftWidth: formStyle.borderLeftWidth,
            boxShadow: formStyle.boxShadow,
            outlineStyle: formStyle.outlineStyle,
            inputBorderTopWidth: inputStyle.borderTopWidth,
            inputBorderRightWidth: inputStyle.borderRightWidth,
            inputBorderBottomWidth: inputStyle.borderBottomWidth,
            inputBorderLeftWidth: inputStyle.borderLeftWidth,
            inputBoxShadow: inputStyle.boxShadow,
            inputOutlineStyle: inputStyle.outlineStyle,
            keyboardFocus: form.hasAttribute('data-keyboard-focus'),
            focusRailWidth: focusRail.width,
            focusRailColor: focusRail.backgroundColor,
          };
        }"""
    )


async def assert_search_has_no_outline(page):
    chrome = await search_chrome(page)
    assert all(
        chrome[name] == "0px"
        for name in (
            "borderTopWidth",
            "borderRightWidth",
            "borderBottomWidth",
            "borderLeftWidth",
            "inputBorderTopWidth",
            "inputBorderRightWidth",
            "inputBorderBottomWidth",
            "inputBorderLeftWidth",
        )
    ), chrome
    assert chrome["boxShadow"] == "none", chrome
    assert chrome["inputBoxShadow"] == "none", chrome
    assert chrome["outlineStyle"] == "none", chrome
    assert chrome["inputOutlineStyle"] == "none", chrome
    return chrome


async def assert_switcher_alignment(page):
    alignment = await page.locator("#app-drawer-btn").evaluate(
        """button => {
          const label = button.querySelector('#app-drawer-label').getBoundingClientRect();
          const chevron = button.querySelector('.shell-navigation-chevron');
          const chevronRect = chevron.getBoundingClientRect();
          const chevronStyle = getComputedStyle(chevron);
          return {
            centerDelta: Math.abs(
              (label.top + label.height / 2) - (chevronRect.top + chevronRect.height / 2)
            ),
            chevronTag: chevron.tagName,
            chevronWidth: chevronRect.width,
            chevronHeight: chevronRect.height,
            chevronDisplay: chevronStyle.display,
            chevronTransform: chevronStyle.transform,
          };
        }"""
    )
    assert alignment["centerDelta"] <= 0.5, alignment
    assert alignment["chevronTag"] == "svg", alignment
    assert alignment["chevronWidth"] == 12, alignment
    assert alignment["chevronHeight"] == 12, alignment
    assert alignment["chevronDisplay"] == "block", alignment
    assert alignment["chevronTransform"] == "none", alignment


class Transport:
    def __init__(self, profile):
        self.profile = profile
        self.hold_preview = False
        self.remote = False
        self.pending = asyncio.Event()
        self.release = asyncio.Event()
        self.posts = []
        self.unexpected = []

    def hold(self):
        self.hold_preview = True
        self.pending = asyncio.Event()
        self.release = asyncio.Event()

    async def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != "127.0.0.1":
            self.unexpected.append(request.url)
            await route.abort("blockedbyclient")
            return
        path = url.path
        if path == "/api/andromeda/providers":
            await route.fulfill(
                json={
                    "selected": "duckduckgo",
                    "providers": [{"value": "duckduckgo", "label": "fixture", "available": True}],
                }
            )
            return
        if path == "/api/andromeda/search":
            body = request.post_data_json
            await route.fulfill(
                json={
                    "query": str(body["query"]).replace(" !ai", ""),
                    "status": "ready",
                    "provider": "fixture",
                    "normal_results_enabled": True,
                    "overview_requested": False,
                    "used_no_ai": True,
                    "elapsed_ms": 2,
                    "has_more": False,
                    "results": [
                        {
                            "title": "Keyboard result actions",
                            "url": f"https://docs.example.test/result-actions-{self.profile}",
                            "publisher": "docs.example.test",
                            "favicon_url": "https://icons.example.test/docs.png",
                            "snippet": "A synthetic result for selection, summary, copy, and Library checks.",
                        },
                        {
                            "title": "Second stable result",
                            "url": f"https://docs.example.test/second-result-{self.profile}",
                            "publisher": "docs.example.test",
                            "snippet": "A second result verifies selection moves without navigation.",
                        },
                    ],
                }
            )
            return
        if path == "/api/andromeda/media":
            await route.fulfill(
                path=str(Path(__file__).resolve().parents[1] / "static/icons/icon-192.png"),
                content_type="image/png",
            )
            return
        if path == "/api/andromeda/overview/preview":
            held = self.hold_preview
            self.hold_preview = False
            if held:
                self.pending.set()
                await self.release.wait()
            await route.fulfill(
                json={
                    "endpoint_id": "fixture-endpoint",
                    "endpoint": "isolated fixture",
                    "model": "fixture-model",
                    "privacy_class": "remote" if self.remote else "local",
                }
            )
            return
        if path == "/api/andromeda/overview":
            body = request.post_data_json
            self.posts.append(body)
            result = body["results"][0]
            quote = "This page documents keyboard-first result actions."
            claim = {
                "text": quote,
                "citations": [
                    {
                        "source_id": "s1",
                        "quote": quote,
                        "url": result["url"],
                        "title": result["title"],
                    }
                ],
            }
            overview = {"status": "ready", "claims": [claim], "key_answer": claim}
            stream = (
                f"data: {json.dumps({'type': 'claim', 'claim': claim})}\n\n"
                f"data: {json.dumps({'type': 'overview', 'overview': overview})}\n\n"
                "data: [DONE]\n\n"
            )
            await route.fulfill(status=200, content_type="text/event-stream", body=stream)
            return
        await route.continue_()


async def run_profile(browser, base, output, device, theme, record):
    profile = f"{device}-{theme}"
    width = 390 if device == "phone" else 1440
    context = await browser.new_context(
        viewport={"width": width, "height": 844 if device == "phone" else 900},
        is_mobile=device == "phone",
        has_touch=device == "phone",
        reduced_motion="reduce",
        color_scheme=theme,
        locale="en-US",
        timezone_id="UTC",
        service_workers="block",
        permissions=["clipboard-read", "clipboard-write"],
    )
    transport = Transport(profile)
    await context.route("**/*", transport.route)
    await context.route_web_socket("**/*", lambda socket: socket.close())
    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = await context.new_page()
    page.set_default_timeout(12_000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        api = context.request
        assert (await api.post(base + "/api/setup/dismiss", max_redirects=0)).ok
        assert (await api.put(base + "/api/appearance", data=from_legacy(theme, None))).ok
        await page.goto(base + "/?view=andromeda", wait_until="networkidle")
        await expect(page.locator("#andromeda-saved-list")).to_have_text("nothing saved yet")
        form = page.locator("#andromeda-form")
        query = page.locator("#andromeda-query")

        # Empty, filled, hover, pointer-active, and keyboard-focus search states
        # stay borderless. Keyboard focus uses the short internal rail only.
        await expect(query).to_have_value("")
        empty = await assert_search_has_no_outline(page)
        assert not empty["keyboardFocus"], empty
        await assert_switcher_alignment(page)
        await page.screenshot(path=str(output / f"{profile}-empty.png"), full_page=True)

        await query.click()
        pointer = await assert_search_has_no_outline(page)
        assert not pointer["keyboardFocus"], pointer
        await query.fill("result actions !ai")
        await expect(form).to_have_attribute("data-ready", "")
        filled = await assert_search_has_no_outline(page)
        assert not filled["keyboardFocus"], filled

        await form.hover()
        hovered = await assert_search_has_no_outline(page)
        assert not hovered["keyboardFocus"], hovered
        query_box = await query.bounding_box()
        assert query_box
        await page.mouse.move(
            query_box["x"] + query_box["width"] / 2,
            query_box["y"] + query_box["height"] / 2,
        )
        await page.mouse.down()
        active = await assert_search_has_no_outline(page)
        assert not active["keyboardFocus"], active
        await page.mouse.up()

        await page.locator("#app-drawer-btn").focus()
        await page.keyboard.press("Tab")
        await expect(query).to_be_focused()
        await expect(form).to_have_attribute("data-keyboard-focus", "")
        keyboard = await assert_search_has_no_outline(page)
        assert keyboard["keyboardFocus"], keyboard
        assert keyboard["focusRailWidth"] == "2px", keyboard
        assert keyboard["focusRailColor"] not in {
            "rgba(0, 0, 0, 0)",
            "transparent",
        }, keyboard
        await page.screenshot(path=str(output / f"{profile}-keyboard-focus.png"), full_page=True)

        await query.click()
        pointer_after_keyboard = await assert_search_has_no_outline(page)
        assert not pointer_after_keyboard["keyboardFocus"], pointer_after_keyboard
        await query.fill("result actions !ai")
        await query.press("Enter")
        rows = page.locator("#andromeda-results .andromeda-result")
        await expect(rows).to_have_count(2)
        marks = page.locator("#andromeda-results .andromeda-source-mark")
        await expect(marks).to_have_count(2)
        await expect(marks.nth(0).locator("img")).to_have_count(1)
        await expect(marks.nth(0).locator("img")).to_have_class("loaded")
        await expect(marks.nth(1)).to_have_text("de")
        original_links = await page.locator(
            "#andromeda-results .andromeda-result-title"
        ).evaluate_all("nodes => nodes.map(node => ({href: node.href, text: node.textContent}))")
        original_url = page.url
        original_history = await page.evaluate("history.length")

        # Keyboard selection and the KOKUEN menu model.
        await page.evaluate("document.activeElement.blur()")
        await page.keyboard.press("j")
        first = rows.nth(0)
        await expect(first).to_have_attribute("data-selected", "")
        assert await first.evaluate("row => document.activeElement === row")
        await page.keyboard.press("m")
        menu = first.locator('[role="menu"]')
        await expect(menu).to_be_visible()
        await page.screenshot(path=str(output / f"{profile}-menu-open.png"), full_page=True)
        await expect(menu.get_by_role("menuitem", name="summarize page")).to_be_focused()
        await page.keyboard.press("ArrowDown")
        await expect(menu.get_by_role("menuitem", name="copy link")).to_be_focused()
        await page.keyboard.press("Escape")
        await expect(menu).to_be_hidden()
        await expect(
            first.get_by_role("button", name="actions for Keyboard result actions")
        ).to_be_focused()

        # Cancellation is local to the summary and leaves the result/link untouched.
        transport.hold()
        await first.focus()
        await page.keyboard.press("s")
        await asyncio.wait_for(transport.pending.wait(), timeout=5)
        summary = first.locator(".andromeda-result-summary")
        await expect(summary).to_be_visible()
        await expect(summary.get_by_role("button", name="stop")).to_be_visible()
        await page.screenshot(path=str(output / f"{profile}-summary-pending.png"), full_page=True)
        await summary.get_by_role("button", name="stop").click()
        await expect(summary).to_contain_text("summary stopped. original link is unchanged.")
        await page.screenshot(path=str(output / f"{profile}-summary-stopped.png"), full_page=True)
        transport.release.set()
        await page.wait_for_timeout(100)
        assert not transport.posts
        await summary.get_by_role("button", name="retry summary").click()
        await expect(summary).to_contain_text("This page documents keyboard-first result actions.")
        await expect(summary).to_contain_text("summary ready · fixture-model")
        assert len(transport.posts) == 1
        assert transport.posts[0]["results"][0]["url"] == original_links[0]["href"]

        # Copy reports completion inline and does not navigate.
        await first.focus()
        await page.keyboard.press("c")
        await expect(first.locator(".andromeda-result-receipt")).to_have_text("link copied")
        assert await page.evaluate("navigator.clipboard.readText()") == original_links[0]["href"]

        # Library save is explicit, confirmed, and restored as an Open action.
        await first.focus()
        await page.keyboard.press("m")
        save = menu.get_by_role("menuitem", name="save to Library: Keyboard result actions")
        await expect(save).to_be_visible()
        await save.click()
        await expect(first.locator(".andromeda-result-receipt")).to_have_text("saved to Library")
        await first.focus()
        await page.keyboard.press("m")
        await expect(
            menu.get_by_role("menuitem", name="open in Library: Keyboard result actions")
        ).to_be_visible()
        await page.keyboard.press("Escape")
        await query.fill("result actions !ai")
        await query.press("Enter")
        await expect(rows).to_have_count(2)
        first = rows.nth(0)
        await first.focus()
        await page.keyboard.press("m")
        menu = first.locator('[role="menu"]')
        await expect(
            menu.get_by_role("menuitem", name="open in Library: Keyboard result actions")
        ).to_be_visible()
        await page.keyboard.press("Escape")

        # A remote configured model still requires exact, per-action consent.
        transport.remote = True
        await first.focus()
        await page.keyboard.press("s")
        dialog = page.locator(".dialog-overlay")
        await expect(dialog).to_be_visible()
        before = len(transport.posts)
        await dialog.locator("[data-dialog-cancel]").click()
        await expect(first.locator(".andromeda-result-summary")).to_contain_text(
            "summary cancelled before anything was sent."
        )
        assert len(transport.posts) == before
        await first.get_by_role("button", name="retry summary").click()
        await expect(dialog).to_be_visible()
        await dialog.locator("[data-dialog-confirm]").click()
        await expect(first.locator(".andromeda-result-summary")).to_contain_text(
            "summary ready · fixture-model"
        )
        assert transport.posts[-1]["confirmed_endpoint_id"] == "fixture-endpoint"
        assert transport.posts[-1]["confirmed_model"] == "fixture-model"

        assert page.url == original_url
        assert await page.evaluate("history.length") == original_history
        assert (
            await page.locator("#andromeda-results .andromeda-result-title").evaluate_all(
                "nodes => nodes.map(node => ({href: node.href, text: node.textContent}))"
            )
            == original_links
        )
        assert await page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert not errors, errors
        assert not transport.unexpected, transport.unexpected
        await page.locator("#andromeda-view").evaluate("node => { node.scrollTop = 0; }")
        await page.screenshot(path=str(output / f"{profile}-result-actions.png"), full_page=True)
        record("andromeda.result-actions", profile, "passed")
    except BaseException as exc:
        record("andromeda.result-actions", profile, "failed", f"{type(exc).__name__}: {exc}")
        await page.screenshot(path=str(output / f"{profile}-failure.png"), full_page=True)
        raise
    finally:
        transport.release.set()
        await context.tracing.stop(path=str(output / f"{profile}-trace.zip"))
        await context.close()


async def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []

    def record(check, profile, status, error=None):
        scenarios[:] = [row for row in scenarios if (row["id"], row["profile"]) != (check, profile)]
        scenarios.append(
            {
                "id": check,
                "scenario_id": check,
                "profile": profile,
                "status": status,
                "error": error,
                "simulation": SIMULATION,
                "evidence": [
                    f"{profile}-empty.png",
                    f"{profile}-keyboard-focus.png",
                    f"{profile}-menu-open.png",
                    f"{profile}-summary-pending.png",
                    f"{profile}-summary-stopped.png",
                    f"{profile}-result-actions.png",
                    f"{profile}-trace.zip",
                ],
            }
        )
        (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for theme in ("dark", "light"):
                for device in ("desktop", "phone"):
                    await run_profile(browser, base, output, device, theme, record)
        finally:
            await browser.close()
    print("desktop/phone Andromeda result action, cancellation, consent, and Library checks passed")


if __name__ == "__main__":
    asyncio.run(run())
