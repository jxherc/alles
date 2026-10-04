"""Docs offline guidance, local retry and exact saved content."""

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
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]] + [
    (1280, t, True) for t in ["dark", "light"]
]

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
            row = {
                "scenario_id": "docs.offline-guidance",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                name = f"owned-retry-{label}.md"
                assert context.request.post(
                    base + "/api/vault-md/file",
                    data={"path": name, "content": "# original local text\n"},
                ).ok
                page.goto(base + "/?view=wiki", wait_until="networkidle")
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
                file = page.locator(f'#wiki-tree [data-file="{name}"]')
                if not file.is_visible():
                    page.locator("#wiki-tree-toggle").click()
                file.click()
                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                draft = "# keep this local edit\n\nretry after connection returns\n"
                page.locator("#wiki-source").fill(draft)
                context.set_offline(True)
                page.locator("#wiki-save-btn").press("Enter")
                expect(page.locator("#wiki-save-state")).to_contain_text("could not reach")
                expect(page.locator("#wiki-source")).to_have_value(draft)
                page.screenshot(path=str(out / f"{label}-offline.png"))
                expect(page.locator("#wiki-save-state")).to_contain_text("retry")
                expect(page.locator("#wiki-save-state")).to_contain_text(
                    "your edits are still here"
                )
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                context.set_offline(False)
                page.locator("#wiki-save-btn").press("Enter")
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                saved = context.request.get(base + "/api/vault-md/file", params={"path": name})
                assert saved.ok and saved.json()["content"] == draft
                page.reload(wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text("keep this local edit")
                expect(page.locator("#wiki-preview")).to_contain_text(
                    "retry after connection returns"
                )
                page.screenshot(path=str(out / f"{label}-reopened.png"))
                assert not errors, errors
                unexpected = [
                    message for message in console if "ERR_INTERNET_DISCONNECTED" not in message
                ]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    native_zoom=zoom,
                    recovery="actual browser offline; local save and reload",
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                context.set_offline(False)
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))
