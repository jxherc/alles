"""Compact Files history, named restores and exact undo recovery on owned local data."""

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
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)

            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "files.completed-history",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                root = Path(os.environ["ALLES_DATA"]) / "files"
                root.mkdir(exist_ok=True)

                def operate(**values):
                    response = context.request.post(base + "/api/files/operations", data=values)
                    assert response.ok, response.text()
                    return response.json()

                names = [f"{label}-record-{i}.txt" for i in range(3)]
                copies = []
                for i, name in enumerate(names):
                    (root / name).write_text(f"exact local contents {i}")
                    copies.append(
                        operate(action="copy", source_path=name, destination_path="copy-" + name)
                    )
                page.goto(base + "/?view=files", wait_until="networkidle")
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
                dock = page.locator("#files-operation-dock")
                toggle = page.locator("#files-operations-clear")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                assert dock.bounding_box()["height"] <= 88
                assert page.locator(".files-operation-row").count() == 0
                page.screenshot(path=str(out / f"{label}-collapsed.png"))
                toggle.focus()
                page.keyboard.press("Enter")
                expect(toggle).to_have_attribute("aria-expanded", "true")
                first_copy = page.locator(f'[data-operation-id="{copies[0]["id"]}"]')
                undo_copy = first_copy.get_by_role("button", name="undo", exact=True)
                undo_copy.focus()
                page.evaluate(
                    "window._historyRenders=0;new MutationObserver(()=>window._historyRenders++).observe(document.querySelector('#files-operation-list'),{childList:true})"
                )
                page.wait_for_function("window._historyRenders > 0", timeout=10000)
                expect(undo_copy).to_be_focused()
                toggle.press("Enter")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                restores = []
                for name in names[:2]:
                    operate(action="delete", source_path=name)
                page.reload(wait_until="networkidle")
                page.locator('[data-files-view="trash"]').click()
                for name in names[:2]:
                    item = page.locator("#files-list .file-row[data-trash-id]").filter(
                        has_text=name
                    )
                    expect(item).to_be_visible()
                    restored = operate(
                        action="restore", source_path=item.get_attribute("data-trash-id")
                    )
                    restores.append((name, restored["id"]))
                page.reload(wait_until="networkidle")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                toggle.press("Enter")
                for name, identity in restores:
                    expect(page.locator(f'[data-operation-id="{identity}"] strong')).to_have_text(
                        "restore " + name
                    )
                page.screenshot(path=str(out / f"{label}-named-restores.png"))
                first_name, first_id = restores[0]
                second_name, second_id = restores[1]
                first_row = page.locator(f'[data-operation-id="{first_id}"]')
                first_row.get_by_role("button", name="undo", exact=True).press("Enter")
                expect(first_row.get_by_role("button", name="undo", exact=True)).to_have_count(0)
                assert not (root / first_name).exists()
                assert (root / second_name).read_text() == "exact local contents 1"
                second_row = page.locator(f'[data-operation-id="{second_id}"]')
                undo_url = base + f"/api/files/operations/{second_id}/undo"
                page.route(
                    undo_url,
                    lambda route: route.fulfill(
                        status=503, json={"detail": "synthetic undo unavailable; try again"}
                    ),
                )
                second_row.get_by_role("button", name="undo", exact=True).click()
                expect(page.locator(".toast").last).to_contain_text("synthetic undo unavailable")
                assert (root / second_name).read_text() == "exact local contents 1"
                page.unroute(undo_url)
                second_row.get_by_role("button", name="undo", exact=True).click()
                expect(second_row.get_by_role("button", name="undo", exact=True)).to_have_count(0)
                assert not (root / second_name).exists()
                page.reload(wait_until="networkidle")
                toggle.press("Enter")
                for name, identity in restores:
                    expect(page.locator(f'[data-operation-id="{identity}"] strong')).to_have_text(
                        "restore " + name
                    )
                    assert (
                        context.request.get(base + f"/api/files/operations/{identity}").json()[
                            "state"
                        ]
                        == "undone"
                    )
                toggle.press("Enter")
                queued = operate(
                    action="copy",
                    source_path=names[2],
                    destination_path="queued-" + names[2],
                    run_now=False,
                )
                failed = operate(
                    action="copy",
                    source_path=names[2],
                    destination_path="copy-" + names[2],
                    run_now=False,
                )
                response = context.request.post(base + f"/api/files/operations/{failed['id']}/run")
                assert response.status == 409
                page.reload(wait_until="networkidle")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                queued_row = page.locator(f'[data-operation-id="{queued["id"]}"]')
                failed_row = page.locator(f'[data-operation-id="{failed["id"]}"]')
                expect(queued_row.get_by_role("button", name="start", exact=True)).to_be_visible()
                expect(failed_row).to_contain_text("destination already exists")
                page.screenshot(path=str(out / f"{label}-unfinished-visible.png"))
                queued_row.get_by_role("button", name="start", exact=True).click()
                expect(queued_row).to_have_count(0)
                assert (root / ("queued-" + names[2])).read_text() == "exact local contents 2"
                failed_row.get_by_role("button", name="dismiss", exact=True).click()
                expect(failed_row).to_have_count(0)
                assert dock.bounding_box()["height"] <= 88
                expect(toggle).to_be_visible()
                assert not errors, errors
                assert len(console) == 1 and "503" in console[0], console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                row.update(
                    status="passed",
                    native_zoom=zoom,
                    collapsed_height=dock.bounding_box()["height"],
                    restores=restores,
                    boundary="actual owned local operations and exact undo; one synthetic undo failure",
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
