"""Artifact motion follows the preference after leaving Aide as well as inside it."""

import base64
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    timezone_id="UTC",
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
                )
                if zoom:
                    profile = Path(os.environ["ALLES_DATA"]) / label
                    extension = profile / "extension"
                    extension.mkdir(parents=True)
                    (extension / "manifest.json").write_text(
                        json.dumps(
                            dict(
                                manifest_version=3,
                                name="owned zoom check",
                                version="1.0",
                                permissions=["tabs"],
                                background={"service_worker": "zoom.js"},
                            )
                        )
                    )
                    (extension / "zoom.js").write_text(
                        "chrome.runtime.onInstalled.addListener(() => {});"
                    )
                    context = pw.chromium.launch_persistent_context(
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
                    context = browser.new_context(**options)
                external, errors, console = [], [], []

                def route(request):
                    if urlparse(request.request.url).netloc != urlparse(base).netloc:
                        external.append(request.request.url)
                        return request.abort()
                    return request.continue_()

                context.route("**/*", route)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                row = {
                    "scenario_id": "aide.artifact-motion",
                    "profile": label,
                    "status": "failed",
                }
                rows.append(row)

                def capture(name):
                    screenshot = context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (output / f"{label}-{name}.png").write_bytes(
                        base64.b64decode(screenshot["data"])
                    )

                task_ids = []
                try:
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    session = api.post(
                        base + "/api/sessions", data={"name": "Owned artifact motion fixture"}
                    ).json()
                    task_ids.append(session["id"])

                    def history(route):
                        response = route.fetch()
                        data = response.json()
                        data["messages"] = [
                            {
                                "id": "owned-artifact-message",
                                "role": "assistant",
                                "content": "A saved code result.",
                                "meta": {
                                    "artifacts": [
                                        {
                                            "type": "code",
                                            "title": "Owned code result",
                                            "lang": "javascript",
                                            "content": "const total = 2 + 2;",
                                        }
                                    ]
                                },
                                "timestamp": "2032-01-01T12:00:00",
                            }
                        ]
                        route.fulfill(response=response, json=data)

                    page.route(base + "/api/sessions/" + session["id"] + "/history", history)
                    page.goto(base + "/?view=chat#" + session["id"], wait_until="networkidle")
                    if zoom:
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        assert (
                            worker.evaluate(
                                "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                                base,
                            )
                            == 2
                        )
                        page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    opener = page.get_by_role("button", name="open artifact", exact=True)
                    panel = page.locator("#artifact-panel")
                    close = page.locator("#artifact-close-btn")
                    observations = []
                    for motion in ["reduce", "no-preference"]:
                        page.emulate_media(reduced_motion=motion)
                        opener.press("Enter")
                        expect(panel).to_have_class("artifact-panel open")
                        expect(close).to_be_focused()
                        expect(panel.locator(".artifact-content")).to_have_text(
                            "const total = 2 + 2;"
                        )
                        observation = {
                            "motion": motion,
                            "aide_duration": panel.evaluate(
                                "e=>getComputedStyle(e).transitionDuration"
                            ),
                        }
                        if motion == "reduce":
                            assert observation["aide_duration"] == "0s"
                            assert panel.evaluate("e=>e.getAnimations().length") == 0
                        page.wait_for_function(
                            "!document.getElementById('artifact-panel').getAnimations().some(a=>a.playState==='running')"
                        )
                        assert panel.bounding_box()["width"] == (
                            page.evaluate("innerWidth")
                            if page.evaluate("innerWidth") <= 720
                            else 420
                        )
                        capture(motion + "-aide")
                        if page.evaluate("innerWidth") > 720:
                            # These are exposed product controls; the artifact stays open on Home.
                            page.locator("#app-drawer-btn").click()
                            page.locator('.app-drawer-item[data-view="today"]').click()
                            expect(page.locator("#today-view")).to_be_visible()
                            expect(panel).to_have_class("artifact-panel open")
                            observation["home_duration"] = panel.evaluate(
                                "e=>getComputedStyle(e).transitionDuration"
                            )
                            assert observation["home_duration"] == (
                                "0s" if motion == "reduce" else "0.2s"
                            )
                            capture(motion + "-home")
                            close.press("Enter")
                            if motion == "reduce":
                                assert panel.evaluate("e=>e.getAnimations().length") == 0
                                assert panel.bounding_box()["width"] <= 1
                            page.wait_for_function(
                                "document.getElementById('artifact-panel').getBoundingClientRect().width <= 1"
                            )
                            assert panel.evaluate("e=>e.inert")
                            page.locator("#app-drawer-btn").click()
                            page.locator('.app-drawer-item[data-view="chat"]').click()
                            expect(opener).to_be_visible()
                        else:
                            # On small screens the full-screen artifact covers navigation.
                            page.keyboard.press("Escape")
                            expect(opener).to_be_focused()
                            page.wait_for_function(
                                "document.getElementById('artifact-panel').getBoundingClientRect().width <= 1"
                            )
                            assert panel.evaluate("e=>e.inert")
                        observations.append(observation)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert not external and not errors and not console, (external, errors, console)
                    row.update(
                        status="passed",
                        observations=observations,
                        checks="actual saved-result opener, code content, close/Escape/focus, both motion preferences, outside-Aide desktop navigation/close, native200 full CDP captures, console and overflow",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
                    for identity in task_ids:
                        assert context.request.delete(base + "/api/sessions/" + identity).ok
                    row.update(
                        page_errors=errors, console_errors=console, blocked_external=external
                    )
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in rows), rows


if __name__ == "__main__":
    run()
