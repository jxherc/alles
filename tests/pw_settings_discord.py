"""Browser regressions for Discord Settings state ownership."""

import json
import os

from playwright.sync_api import Route, expect, sync_playwright

BASE = os.environ.get("DISCORD_SETTINGS_BASE", "http://127.0.0.1:8971")


def run() -> None:
    state = {
        "configured": True,
        "connection_state": "connected",
        "bot_name": "Jarvis",
        "paired": True,
        "owner_name": "owner",
        "enabled": False,
        "allowed_channel_ids": ["111"],
        "quiet_hours": {
            "enabled": True,
            "start": "23:00",
            "end": "07:00",
            "timezone": "Asia/Taipei",
        },
    }
    fail_quiet_disable = {"value": False}

    def discord_api(route: Route) -> None:
        request = route.request
        if request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(state))
            return
        if request.method == "PATCH":
            patch = request.post_data_json
            if patch.get("quiet_hours") == {"enabled": False} and fail_quiet_disable["value"]:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"quiet hours unavailable"}',
                )
                return
            if "enabled" in patch:
                state["enabled"] = patch["enabled"]
            if "allowed_channel_ids" in patch:
                state["allowed_channel_ids"] = patch["allowed_channel_ids"]
            if "quiet_hours" in patch:
                state["quiet_hours"] = {**state["quiet_hours"], **patch["quiet_hours"]}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(state))
            return
        route.continue_()

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.route("**/api/jarvis/discord", discord_api)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function("typeof window._openSettings === 'function'")
        page.evaluate("window._openSettings('tools')")
        expect(page.locator("#jarvis-discord-manage")).to_be_visible()

        channels = page.locator("#jarvis-discord-channels")
        quiet_start = page.locator("#jarvis-discord-quiet-start")
        channels.fill("222")
        quiet_start.fill("21:30")

        # A newer channel edit made while an older save is pending must survive its response.
        page.evaluate(
            """() => {
              const originalFetch = window.fetch.bind(window);
              let held = false;
              window.fetch = (input, init = {}) => {
                if (!held && String(input) === '/api/jarvis/discord'
                    && init.method === 'PATCH'
                    && String(init.body || '').includes('allowed_channel_ids')) {
                  held = true;
                  return new Promise(resolve => {
                    window.__releaseDiscordChannelSave = () => originalFetch(input, init).then(resolve);
                  });
                }
                return originalFetch(input, init);
              };
            }"""
        )
        page.locator("#jarvis-discord-save-channels").click()
        page.wait_for_function("typeof window.__releaseDiscordChannelSave === 'function'")
        channels.fill("333")
        page.evaluate("window.__releaseDiscordChannelSave()")
        expect(page.locator("#toast-container .toast").last).to_contain_text(
            "approved channels saved"
        )
        expect(channels).to_have_value("333")

        # Enabling the quiet-hours editor is itself a draft and survives unrelated saves.
        page.locator("#jarvis-discord-quiet").click()
        expect(page.locator("#jarvis-discord-quiet")).to_have_attribute("aria-checked", "false")
        expect(page.locator("#jarvis-discord-quiet-fields")).to_be_hidden()
        page.locator("#jarvis-discord-quiet").click()
        quiet_start.fill("20:45")
        page.locator("#jarvis-discord-enabled").click()
        expect(page.locator("#jarvis-discord-enabled")).to_have_attribute("aria-checked", "true")
        expect(channels).to_have_value("333")
        expect(page.locator("#jarvis-discord-quiet")).to_have_attribute("aria-checked", "true")
        expect(page.locator("#jarvis-discord-quiet-fields")).to_be_visible()
        expect(quiet_start).to_have_value("20:45")

        # A GET started before a mutation must not overwrite the mutation response.
        page.evaluate(
            """oldState => {
              const originalFetch = window.fetch.bind(window);
              let held = false;
              window.fetch = (input, init = {}) => {
                if (!held && String(input) === '/api/jarvis/discord' && !init.method) {
                  held = true;
                  return new Promise(resolve => {
                    window.__releaseStaleDiscordLoad = () => resolve(new Response(
                      JSON.stringify(oldState),
                      {status: 200, headers: {'content-type': 'application/json'}},
                    ));
                  });
                }
                return originalFetch(input, init);
              };
            }""",
            {**state, "enabled": True},
        )
        page.locator('.s-nav-item[data-pane="models"]').click()
        page.locator('.s-nav-item[data-pane="tools"]').click()
        page.wait_for_function("typeof window.__releaseStaleDiscordLoad === 'function'")
        page.locator("#jarvis-discord-enabled").click()
        expect(page.locator("#jarvis-discord-enabled")).to_have_attribute("aria-checked", "false")
        page.evaluate("window.__releaseStaleDiscordLoad()")
        page.wait_for_timeout(100)
        expect(page.locator("#jarvis-discord-enabled")).to_have_attribute("aria-checked", "false")

        fail_quiet_disable["value"] = True
        page.locator("#jarvis-discord-quiet").click()
        expect(page.locator("#jarvis-discord-quiet")).to_have_attribute("aria-checked", "true")
        expect(page.locator("#jarvis-discord-quiet-fields")).to_be_visible()
        expect(channels).to_have_value("333")
        expect(quiet_start).to_have_value("20:45")

        expected_503 = [error for error in errors if "503 (Service Unavailable)" in error]
        assert len(expected_503) == 1, errors
        errors[:] = [error for error in errors if error not in expected_503]
        context.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("Discord Settings state browser gate passed")


if __name__ == "__main__":
    run()
