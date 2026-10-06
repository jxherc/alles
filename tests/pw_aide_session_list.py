"""Task-list failures preserve local work, deep links and keyboard recovery."""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    zoomed = os.environ.get("ALLES_SESSION_LIST_ZOOM") == "1"
    profiles = [(w, t) for w in ([1440] if zoomed else [1440, 820, 390]) for t in ["dark", "light"]]
    rows = []
    with sync_playwright() as pw:
        for width, theme in profiles:
            if zoomed:
                profile = Path(os.environ["ALLES_DATA"]) / f"session-zoom-{theme}"
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "local task-list zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
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
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                browser = None
            else:
                browser = pw.chromium.launch()
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlparse(route.request.url).netloc == urlparse(base).netloc
                    else route.abort()
                ),
            )
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            ids = []
            for name in ["owned saved task", "owned other task"]:
                response = api.post(base + "/api/sessions", data={"name": name})
                assert response.ok
                ids.append(response.json()["id"])
            page = context.new_page()
            page.set_default_timeout(4000)
            errors, console, held = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "aide.task-list.recovery",
                "profile": f"{width}-{theme}" + ("-zoom200" if zoomed else ""),
                "status": "failed",
            }
            rows.append(row)
            mode = "hold"
            requests = []

            def listed(route):
                if route.request.method != "GET":
                    route.continue_()
                    return
                requests.append(mode)
                if mode == "hold":
                    held.append(route)
                elif mode == "fail":
                    route.fulfill(status=503, json={"detail": "owned task list outage"})
                else:
                    route.continue_()

            def wait_held():
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                assert held

            def open_sidebar():
                if page.locator("body.sidebar-hidden").count():
                    page.locator("#sidebar-toggle-btn").click()

            page.route(base + "/api/sessions", listed)
            context.tracing.start(screenshots=True, snapshots=True)
            try:
                page.goto(base + "/?app=aide#" + ids[0], wait_until="domcontentloaded")
                wait_held()
                expect(page.locator("#session-list-message")).to_have_text("loading aide tasks…")
                assert "no aide tasks yet" not in page.locator("#session-list").inner_text()
                if width == 1440:
                    page.screenshot(path=str(out / f"{row['profile']}-loading.png"))
                mode = "fail"
                held.pop().fulfill(status=503, json={"detail": "owned task list outage"})
                page.wait_for_load_state("networkidle")
                page.wait_for_function("id => window._currentSession?.id === id", arg=ids[0])
                assert page.evaluate("location.hash") == "#" + ids[0]
                if zoomed:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    zoom = worker.evaluate(
                        "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return await chrome.tabs.getZoom(tab.id);}"
                    )
                    assert zoom == 2
                    page.wait_for_function("innerWidth===720 && devicePixelRatio===2")
                    row["native_zoom"] = zoom
                open_sidebar()
                status = page.locator("#session-list-state")
                retry = page.locator("#session-list-retry")
                search = page.locator("#session-search")
                expect(status).to_contain_text("could not load aide tasks")
                expect(retry).to_be_visible()
                box = retry.bounding_box()
                assert box["height"] >= 44 and box["width"] >= 44, box
                row["retry_target"] = box
                page.screenshot(path=str(out / f"{row['profile']}-error.png"))
                if zoomed:
                    page.locator(".sidebar").hover()
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(150)
                    for control in [retry, page.locator("#aide-tools-link")]:
                        target = control.bounding_box()
                        assert target["y"] >= 0 and target["y"] + target["height"] <= page.evaluate(
                            "innerHeight"
                        ), target
                    row["sidebar_scroll"] = page.locator(".sidebar").evaluate("e => e.scrollTop")
                    assert row["sidebar_scroll"] > 0
                    page.screenshot(path=str(out / f"{row['profile']}-error-scrolled.png"))
                retry.focus()
                page.keyboard.press("Enter")
                expect(retry).to_have_attribute("aria-disabled", "false")
                expect(retry).to_be_focused()
                mode = "hold"
                page.keyboard.press("Enter")
                wait_held()
                expect(retry).to_have_attribute("aria-disabled", "true")
                before = len(requests)
                page.keyboard.press("Enter")
                page.wait_for_timeout(50)
                assert len(requests) == before
                page.screenshot(path=str(out / f"{row['profile']}-retrying.png"))
                mode = "pass"
                held.pop().continue_()
                expect(status).to_be_hidden()
                expect(search).to_be_focused()
                expect(page.locator("#session-list .session-item")).to_have_count(2)
                other = page.locator(f'.session-item[data-id="{ids[1]}"] .session-open')
                other.focus()
                page.keyboard.press("Enter")
                page.wait_for_function("id => window._currentSession?.id === id", arg=ids[1])
                mode = "fail"
                page.evaluate("window._reloadAideSessions()")
                expect(status).to_contain_text("last loaded list")
                expect(page.locator("#session-list .session-item")).to_have_count(2)
                expect(other).to_have_attribute("aria-current", "true")
                open_sidebar()
                search.fill("missing task")
                expect(page.locator("#session-list")).to_have_text("no matching aide tasks")
                expect(status).to_be_visible()
                search.fill("")
                expect(page.locator("#session-list .session-item")).to_have_count(2)
                mode = "hold"
                retry.click()
                wait_held()
                first = page.locator(f'.session-item[data-id="{ids[0]}"] .session-open')
                first.click()
                page.wait_for_function("id => window._currentSession?.id === id", arg=ids[0])
                mode = "pass"
                held.pop().continue_()
                expect(status).to_be_hidden()
                assert page.evaluate("location.hash") == "#" + ids[0]
                expect(
                    page.locator(f'.session-item[data-id="{ids[0]}"] .session-open')
                ).to_have_attribute("aria-current", "true")
                page.screenshot(path=str(out / f"{row['profile']}-recovered.png"))
                for sid in ids:
                    assert api.delete(base + "/api/sessions/" + sid).ok
                ids.clear()
                page.evaluate("window._reloadAideSessions()")
                open_sidebar()
                expect(page.locator("#session-list")).to_contain_text("no aide tasks yet")
                expect(status).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                unexpected = [
                    message
                    for message in console
                    if "503" not in message
                    and "loadSessions Error: could not load aide tasks" not in message
                ]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    requests=requests,
                    deep_link_opened=True,
                    retained_rows=True,
                    keyboard_retry=True,
                    real_empty=True,
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row.update(page_errors=errors, console_errors=console)
                page.screenshot(path=str(out / f"{row['profile']}-final.png"))
                for route in held:
                    route.abort()
                for sid in ids:
                    assert api.delete(base + "/api/sessions/" + sid).ok
                context.tracing.stop(path=str(out / f"{row['profile']}.zip"))
                context.close()
                if browser:
                    browser.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    return any(row["status"] != "passed" for row in rows)


if __name__ == "__main__":
    raise SystemExit(run())
