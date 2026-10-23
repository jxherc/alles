"""Aide drawer keyboard and selection recovery on owned local data."""

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

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]]
profiles += [(1280, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
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
                    **options,
                )
            else:
                context = browser.new_context(**options)
            context.route(
                "**/*",
                lambda request: (
                    request.continue_()
                    if urlparse(request.request.url).netloc == urlparse(base).netloc
                    else request.abort()
                ),
            )
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.drawer-recovery", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                ids = []
                for name in ["owned first task", "owned second task"]:
                    response = context.request.post(base + "/api/sessions", data={"name": name})
                    assert response.ok
                    ids.append(response.json()["id"])
                page.goto(base + "/?view=chat#" + ids[0], wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")
                # Archive is a modal drawer at every width in central Aide.
                trigger = page.get_by_role("button", name="more Aide actions", exact=True)
                legacy_state = page.locator("#sidebar-toggle-btn")
                menu = page.get_by_role("menu", name="Aide actions", exact=True)
                sidebar = page.locator("#aide-sidebar")
                field = page.locator("#composer-ta")

                def open_sidebar():
                    if not sidebar.is_visible():
                        trigger.click()
                        menu.get_by_role("menuitem", name="archive", exact=True).click()
                    expect(sidebar).to_be_visible()
                    expect(sidebar).to_have_attribute("aria-modal", "true")
                    expect(sidebar).to_have_accessible_name("archive")
                    expect(legacy_state).to_have_attribute("aria-expanded", "true")

                def closed():
                    expect(sidebar).to_be_hidden()
                    expect(legacy_state).to_have_attribute("aria-expanded", "false")
                    expect(trigger).to_be_focused()

                expect(page.locator("#aide-history-name")).to_have_text("owned first task")
                open_sidebar()
                page.keyboard.press("Escape")
                closed()
                open_sidebar()
                page.keyboard.press("Control+b")
                closed()
                open_sidebar()
                page.locator("#nav-backdrop").click(
                    position={"x": page.evaluate("innerWidth") - 10, "y": 100}
                )
                closed()
                page.keyboard.press("Control+b")
                expect(sidebar).to_be_visible()
                expect(legacy_state).to_have_attribute("aria-expanded", "true")
                page.keyboard.press("Escape")
                closed()
                # Nested controls now live in More rather than the hidden archive footer.
                trigger.press("Enter")
                expect(menu).to_be_visible()
                page.keyboard.press("Escape")
                expect(menu).to_be_hidden()
                expect(trigger).to_be_focused()
                trigger.click()
                menu.get_by_role("menuitem", name="settings", exact=True).click()
                expect(page.locator("#settings-modal")).to_be_visible()
                page.wait_for_function(
                    "document.querySelector('#settings-modal').contains(document.activeElement)"
                )
                page.keyboard.press("Escape")
                expect(page.locator("#settings-modal")).to_be_hidden()
                expect(sidebar).to_be_hidden()
                expect(trigger).to_be_focused()
                field.fill("keep my first task draft")
                open_sidebar()
                first = page.locator(f'.session-item[data-id="{ids[0]}"] .session-open')
                first.focus()
                page.keyboard.press("Enter")
                closed()
                expect(field).to_have_value("keep my first task draft")
                open_sidebar()
                page.locator(f'.session-item[data-id="{ids[1]}"] .session-open').click()
                expect(page.locator("#aide-history-name")).to_have_text("owned second task")
                closed()
                expect(field).to_have_value("")
                field.fill("second task draft")
                open_sidebar()
                page.locator(f'.session-item[data-id="{ids[0]}"] .session-open').click()
                expect(page.locator("#aide-history-name")).to_have_text("owned first task")
                closed()
                expect(field).to_have_value("keep my first task draft")
                open_sidebar()
                with page.expect_response(
                    lambda r: r.url.endswith("/api/sessions/" + ids[0] + "/history")
                ):
                    page.evaluate("window._reloadActiveSession()")
                expect(sidebar).to_be_visible()
                page.keyboard.press("Escape")
                closed()
                trigger.click()
                menu.get_by_role("menuitem", name="skills", exact=True).click()
                expect(page.locator("#skills-view")).to_be_visible()
                expect(sidebar).to_be_hidden()
                # The preserved new-task shortcut is available from auxiliary views.
                page.keyboard.press("Alt+n")
                expect(field).to_be_visible()
                expect(sidebar).to_be_hidden()
                expect(legacy_state).to_have_attribute("aria-expanded", "false")
                was_visible = sidebar.is_visible()
                trigger.click()
                menu.get_by_role("menuitem", name="private conversation", exact=True).click()
                expect(sidebar).to_be_hidden()
                expect(legacy_state).to_have_attribute("aria-expanded", "false")
                page.locator("#incognito-exit").click()
                if was_visible:
                    expect(sidebar).to_be_visible()
                else:
                    expect(sidebar).to_be_hidden()
                expect(legacy_state).to_have_attribute("aria-expanded", str(was_visible).lower())
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                assert not errors, errors
                assert not console, console
                row["checks"] = [
                    "escape",
                    "shortcut",
                    "backdrop",
                    "nested-menu",
                    "settings",
                    "same-task",
                    "switch-task",
                    "draft-return",
                    "background-reload",
                    "auxiliary-view",
                    "new-task",
                    "incognito-layout-return",
                ]
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))
