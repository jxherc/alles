"""Voice drafts, loading/retry and save ownership against an owned local server."""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.appearance import from_legacy  # noqa: E402

BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
CASES = []


async def main():
    require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])
    profiles = [(width, theme, False) for width in (1440, 768, 390) for theme in ("dark", "light")]
    profiles += [(1440, theme, True) for theme in ("dark", "light")]
    async with async_playwright() as pw:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            folder = OUT / label
            folder.mkdir(parents=True, exist_ok=True)
            options = dict(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            browser = None
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            manifest_version=3,
                            name="owned Voice zoom verification",
                            version="1.0",
                            permissions=["tabs"],
                            background={"service_worker": "zoom.js"},
                        )
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = await pw.chromium.launch_persistent_context(
                    profile / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(**options)
            errors, console, external = [], [], []

            async def isolate(route):
                if urlsplit(route.request.url).netloc != urlsplit(BASE).netloc:
                    external.append(route.request.url)
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", isolate)
            await context.route_web_socket("**/*", lambda socket: socket.close())
            api = context.request
            assert (await api.post(BASE + "/api/setup/dismiss")).ok
            assert (await api.put(BASE + "/api/appearance", data=from_legacy(theme, None))).ok
            baseline = dict(
                stt_provider="whisper_api",
                tts_provider="openai",
                tts_voice="shimmer",
                tts_speed=2,
                stt_language="fr-FR",
                tts_auto_play=False,
            )
            assert (await api.patch(BASE + "/api/settings", data=baseline)).ok
            page = await context.new_page()
            page.set_default_timeout(7000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            status = page.locator("#s-pane-voice .settings-save-state")
            save = page.locator("#s-voice-save-btn")

            async def section(name):
                trigger = page.locator("#settings-section-trigger")
                if (
                    await trigger.is_visible()
                    and await trigger.get_attribute("aria-expanded") != "true"
                ):
                    await trigger.click()
                await page.locator(f'.s-nav-item[data-pane="{name}"]').click()
                await expect(page.locator("#s-pane-" + name)).to_be_visible()

            async def record(case):
                if case == "05-failed-read-visible":
                    # Let earlier successful-save toasts expire naturally before
                    # assessing the persistent failed-load state and recovery UI.
                    await expect(page.locator("#toast-container .toast")).to_have_count(0)
                await page.locator("#settings-modal .s-content").evaluate("el => el.scrollTop = 0")
                screenshot = folder / f"{case}.png"
                await page.screenshot(path=str(screenshot))
                geometry = await page.evaluate("""() => {
                    const content = document.querySelector('#settings-modal .s-content');
                    return {width: innerWidth, dpr: devicePixelRatio,
                      pageOverflow: document.documentElement.scrollWidth > innerWidth,
                      contentOverflow: content.scrollWidth > content.clientWidth + 1};
                }""")
                assert not geometry["pageOverflow"] and not geometry["contentOverflow"], geometry
                CASES.append(
                    dict(
                        profile=label,
                        case=case,
                        status="passed",
                        screenshot=str(screenshot),
                        **geometry,
                    )
                )
                (OUT / "scenarios.json").write_text(json.dumps(CASES, indent=2) + "\n")

            async def choose(selector, end=False, down=0):
                await page.locator(selector).focus()
                await page.keyboard.press("End" if end else "Home")
                for _ in range(down):
                    await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")

            async def hold_next(method, *, body=None):
                started, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                used = False

                async def handler(route):
                    nonlocal used
                    if route.request.method != method or used:
                        await route.continue_()
                        return
                    used = True
                    started.set()
                    await release.wait()
                    if body is None:
                        await route.continue_()
                    else:
                        await route.fulfill(json=body)
                    completed.set()

                await page.route(BASE + "/api/settings", handler)
                return started, release, completed, handler

            try:
                await page.goto(BASE + "/?view=today", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else await context.wait_for_event("serviceworker")
                    )
                    assert (
                        await worker.evaluate("""async () => {
                        const tab = (await chrome.tabs.query({})).find(t => t.url.startsWith('http://127.0.0.1:'));
                        await chrome.tabs.setZoom(tab.id, 2); return chrome.tabs.getZoom(tab.id);
                    }""")
                        == 2
                    )
                    await page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                await page.locator("#today-settings").click()
                await section("voice")
                await expect(status).to_have_attribute("data-state", "loaded")
                await expect(page.locator("#tts-select")).to_have_attribute("data-value", "openai")
                await record("01-loaded")

                await section("general")
                await page.wait_for_load_state("networkidle")
                stored = await (await api.get(BASE + "/api/settings")).json()
                started, release, completed, handler = await hold_next("GET", body=stored)
                await section("voice")
                await asyncio.wait_for(started.wait(), 7)
                await expect(save).to_be_disabled()
                await page.locator("#s-stt-language").fill("ja-JP")
                await choose("#stt-select", down=1)
                await choose("#tts-select")
                await choose("#s-tts-speed", down=1)
                release.set()
                await asyncio.wait_for(completed.wait(), 7)
                await expect(status).to_have_attribute("data-state", "dirty")
                await expect(page.locator("#s-stt-language")).to_have_value("ja-JP")
                await expect(page.locator("#stt-select")).to_have_attribute("data-value", "local")
                await expect(page.locator("#tts-select")).to_have_attribute("data-value", "browser")
                await expect(page.locator("#s-tts-speed")).to_have_attribute("data-value", "0.75")
                await page.unroute(BASE + "/api/settings", handler)
                await record("02-pending-read-preserves-drafts")

                await save.focus()
                await page.keyboard.press("Enter")
                await expect(status).to_have_attribute("data-state", "saved")
                stored = await (await api.get(BASE + "/api/settings")).json()
                assert stored["stt_language"] == "ja-JP" and stored["tts_speed"] == 0.75
                await record("03-keyboard-save")

                started, release, completed, handler = await hold_next("PATCH")
                await page.locator("#s-stt-language").fill("de-DE")
                await save.click()
                await asyncio.wait_for(started.wait(), 7)
                await page.locator("#s-stt-language").fill("en-US")
                release.set()
                await asyncio.wait_for(completed.wait(), 7)
                await expect(status).to_have_attribute("data-state", "dirty")
                await expect(page.locator("#s-stt-language")).to_have_value("en-US")
                assert (await (await api.get(BASE + "/api/settings")).json())[
                    "stt_language"
                ] == "de-DE"
                await page.unroute(BASE + "/api/settings", handler)
                await record("04-save-keeps-newer-draft")
                await choose("#tts-select", end=True)
                await save.click()
                await expect(status).to_have_attribute("data-state", "saved")

                await section("general")
                await page.wait_for_load_state("networkidle")

                async def refuse(route):
                    await route.fulfill(
                        status=503, json={"detail": "synthetic Voice read unavailable"}
                    )

                await page.route(BASE + "/api/settings", refuse)
                await section("voice")
                await expect(status).to_have_attribute("data-state", "error")
                await expect(status).to_contain_text("could not load")
                await expect(save).to_be_disabled()
                await expect(page.locator("#tts-select")).to_have_attribute("data-value", "openai")
                await expect(page.locator("#s-stt-language")).to_have_value("en-US")
                await record("05-failed-read-visible")
                await page.unroute(BASE + "/api/settings", refuse)
                await page.locator("#s-voice-retry-btn").focus()
                await page.keyboard.press("Enter")
                await expect(status).to_have_attribute("data-state", "loaded")
                await expect(page.locator("#stt-select")).to_be_focused()
                await expect(save).to_be_enabled()
                await record("06-keyboard-retry")

                await section("general")
                await page.wait_for_load_state("networkidle")

                async def malformed(route):
                    await route.fulfill(json={})

                await page.route(BASE + "/api/settings", malformed)
                await section("voice")
                await expect(status).to_have_attribute("data-state", "error")
                await expect(save).to_be_disabled()
                await page.unroute(BASE + "/api/settings", malformed)
                await page.locator("#s-voice-retry-btn").click()
                await expect(status).to_have_attribute("data-state", "loaded")
                await record("07-malformed-read-recovery")

                await section("general")
                await page.wait_for_load_state("networkidle")
                started, release, completed, handler = await hold_next("GET", body=stored)
                await section("voice")
                await asyncio.wait_for(started.wait(), 7)
                await page.keyboard.press("Escape")
                await expect(page.locator("#today-settings")).to_be_focused()
                release.set()
                await asyncio.wait_for(completed.wait(), 7)
                await page.wait_for_load_state("networkidle")
                await expect(page.locator("#s-stt-language")).to_have_value("en-US")
                await page.unroute(BASE + "/api/settings", handler)
                await page.locator("#today-settings").click()
                await section("voice")
                await expect(status).to_have_attribute("data-state", "loaded")
                await record("08-close-invalidates-read")
                assert not errors, errors
                assert not external, external
                assert len(console) == 1 and "503" in console[0], console
                print(label, "8 scenarios passed", flush=True)
            except Exception:
                await page.screenshot(path=str(folder / "failure.png"))
                raise
            finally:
                (folder / "events.json").write_text(
                    json.dumps(
                        dict(pageerrors=errors, console=console, external=external), indent=2
                    )
                )
                await context.close()
                if browser:
                    await browser.close()
    print(f"{len(CASES)} Voice scenarios passed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
