"""Isolated browser QA for the macOS PhotoKit Gallery action.

The native status endpoint is read, but the permission/import requests are
intercepted with fakes so this test never prompts for or reads the real library.
"""

import json
import os
import re

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("ALLES_TEST_PORT", "8897"))
BASE = f"http://gallery.localhost:{PORT}"
API = f"http://127.0.0.1:{PORT}"


def main():
    result = {}
    console_errors = []
    job_polls = {"count": 0}
    status = {
        "platform": "darwin",
        "available": True,
        "authorization": "authorized",
        "ready": True,
        "reason": "ready",
        "job": None,
    }

    def status_route(route):
        route.fulfill(status=200, json=status)

    def start_route(route):
        route.fulfill(
            status=202,
            json={
                "id": "browser-job",
                "state": "queued",
                "processed": 0,
                "total": 0,
                "imported": 0,
                "updated": 0,
            },
        )

    def job_route(route):
        job_polls["count"] += 1
        if job_polls["count"] == 1:
            route.fulfill(
                status=200,
                json={
                    "id": "browser-job",
                    "state": "running",
                    "processed": 1,
                    "total": 2,
                    "imported": 1,
                    "updated": 0,
                },
            )
        else:
            route.fulfill(
                status=200,
                json={
                    "id": "browser-job",
                    "state": "complete",
                    "processed": 2,
                    "total": 2,
                    "imported": 2,
                    "updated": 0,
                    "failed": 0,
                    "remaining": 0,
                },
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}, reduced_motion="reduce"
        )
        actual = context.request.get(API + "/api/photos/sync/macos/status")
        result["native_status_http"] = actual.status
        actual_status = actual.json()
        result["native_platform"] = actual_status.get("platform")
        result["native_available"] = actual_status.get("available")
        result["native_authorization"] = actual_status.get("authorization")

        context.route("**/api/photos/sync/macos/status", status_route)
        context.route("**/api/photos/sync/macos/jobs/**", job_route)
        context.route(re.compile(r"/api/photos/sync/macos\?limit=\d+$"), start_route)

        page = context.new_page()
        page.on(
            "console",
            lambda msg: (
                console_errors.append(f"console:{msg.text}") if msg.type == "error" else None
            ),
        )
        page.on("pageerror", lambda err: console_errors.append(f"page:{err}"))
        page.goto(BASE + "/", wait_until="networkidle")
        button = page.locator("#photos-macos-btn")
        button.wait_for(state="visible")
        result["desktop_visible"] = button.is_visible()
        result["desktop_label"] = button.inner_text().strip()
        result["button_tag"] = button.evaluate("el => el.tagName")
        button.focus()
        page.keyboard.press("Enter")
        page.locator("[data-dialog-confirm]").wait_for(state="visible")
        page.screenshot(path="/tmp/alles-photokit-confirm.png", full_page=True)
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => document.querySelector('#photos-macos-btn')?.disabled === true"
        )
        page.wait_for_function(
            "() => document.querySelector('#photos-macos-btn')?.textContent.includes('importing')"
        )
        result["keyboard_started"] = True
        page.locator(".toast.success").wait_for(state="visible", timeout=5000)
        result["completion_toast"] = page.locator(".toast.success").inner_text()
        page.screenshot(path="/tmp/alles-photokit-desktop.png", full_page=True)

        mobile = context.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.on(
            "console",
            lambda msg: (
                console_errors.append(f"mobile-console:{msg.text}") if msg.type == "error" else None
            ),
        )
        mobile.on("pageerror", lambda err: console_errors.append(f"mobile-page:{err}"))
        mobile.goto(BASE + "/", wait_until="networkidle")
        mobile_button = mobile.locator("#photos-macos-btn")
        mobile_button.wait_for(state="visible")
        box = mobile_button.bounding_box()
        result["mobile_visible"] = mobile_button.is_visible()
        result["mobile_button_in_viewport"] = bool(
            box and box["x"] >= 0 and box["x"] + box["width"] <= 390
        )
        result["mobile_no_page_overflow"] = mobile.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        mobile.screenshot(path="/tmp/alles-photokit-mobile.png", full_page=True)

        result["console_errors"] = console_errors
        browser.close()

    assert result["native_status_http"] == 200
    assert result["native_platform"] == "darwin"
    assert result["native_available"] is True
    assert result["native_authorization"] in {
        "not_determined",
        "authorized",
        "limited",
        "denied",
        "restricted",
    }
    assert result["desktop_visible"]
    assert result["button_tag"] == "BUTTON"
    assert result["keyboard_started"]
    assert "2 imported" in result["completion_toast"]
    assert result["mobile_visible"]
    assert result["mobile_button_in_viewport"]
    assert result["mobile_no_page_overflow"]
    assert not result["console_errors"], result["console_errors"]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
