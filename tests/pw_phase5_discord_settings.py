"""Browser and spacing gate for the owner-scoped Jarvis Discord connection."""

import json
import os
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

PORT = os.environ.get("PORT", "8046")
URL = f"http://aide.localhost:{PORT}/"


def _state() -> dict:
    return {
        "configured": True,
        "id": "discord-test",
        "bot_name": "Jarvis",
        "bot_id": "9001",
        "enabled": True,
        "paired": True,
        "owner_name": "jxh",
        "allowed_channel_ids": ["123456789012345678"],
        "pairing_available": False,
        "pairing_expires_at": "",
        "connection_state": "connected",
        "last_connected_at": "2026-07-14T00:00:00Z",
        "quiet_hours": {
            "enabled": True,
            "start": "23:00",
            "end": "07:00",
            "timezone": "Asia/Taipei",
        },
        "secret_configured": True,
    }


def run() -> None:
    errors: list[str] = []
    requests: list[tuple[str, dict]] = []
    output = Path(os.environ.get("SCREENSHOT_DIR", "/tmp"))
    state = _state()

    def discord_api(route: Route) -> None:
        request = route.request
        body = request.post_data_json if request.post_data else {}
        requests.append((request.method, body))
        if request.method == "PATCH":
            if "enabled" in body:
                state["enabled"] = bool(body["enabled"])
            if "allowed_channel_ids" in body:
                state["allowed_channel_ids"] = body["allowed_channel_ids"]
            if "quiet_hours" in body:
                state["quiet_hours"] = body["quiet_hours"]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height, label in ((1440, 1000, "desktop"), (390, 844, "mobile")):
            requests.clear()
            state["enabled"] = True
            context = browser.new_context(
                viewport={"width": width, "height": height}, service_workers="block"
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.route("**/api/jarvis/discord", discord_api)
            page.goto(URL, wait_until="networkidle")
            tools_button = page.locator("#aide-tools-link")
            if not tools_button.is_visible():
                page.locator("#sidebar-toggle-btn").click()
                tools_button.wait_for(state="visible")
            tools_button.click()
            page.locator("#aide-sidebar-menu:not([hidden])").wait_for()
            page.locator("#aide-settings-link").click()
            page.locator('.s-nav-item[data-pane="tools"]').click()
            card = page.locator("#jarvis-discord-card")
            card.wait_for(state="visible")
            card.scroll_into_view_if_needed()

            assert card.locator("select").count() == 0
            assert card.locator('input[type="radio"], input[type="checkbox"]').count() == 0
            assert card.locator('[role="switch"]').count() == 2
            assert page.locator("#settings-modal").evaluate(
                "el => el.scrollWidth <= el.clientWidth + 1"
            )
            box = card.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1

            enabled = page.locator("#jarvis-discord-enabled")
            enabled.focus()
            page.keyboard.press("Enter")
            page.wait_for_function(
                "document.querySelector('#jarvis-discord-enabled')?.getAttribute('aria-checked') === 'false'"
            )
            assert enabled.get_attribute("aria-checked") == "false"
            assert any(
                method == "PATCH" and body.get("enabled") is False for method, body in requests
            )

            page.locator("#jarvis-discord-channels").fill("111\n222")
            page.locator("#jarvis-discord-save-channels").click()
            assert any(
                method == "PATCH" and body.get("allowed_channel_ids") == ["111", "222"]
                for method, body in requests
            )

            page.screenshot(path=output / f"alles-phase5-discord-{label}.png", full_page=False)
            context.close()
        browser.close()
    assert not errors, errors


if __name__ == "__main__":
    run()
