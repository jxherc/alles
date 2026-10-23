"""Setup identity, reversible file confirmation and reduced-motion cursor checks."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 320]:
            for theme in ["dark", "light"]:
                label = f"{width}-{theme}"
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    has_touch=width == 320,
                    reduced_motion="reduce",
                )
                errors, console, external = [], [], []

                def local_only(route):
                    if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                        return route.continue_()
                    external.append(route.request.url)
                    route.abort()

                context.route("**/*", local_only)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(8000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                result = {"scenario_id": "product.clarity", "profile": label, "status": "failed"}
                results.append(result)
                try:
                    assert context.request.put(
                        base + "/api/appearance", data=from_legacy(theme, None)
                    ).ok
                    assert context.request.post(base + "/api/setup/resume").ok
                    context.add_init_script(
                        "if(!localStorage.getItem('alles-name'))localStorage.setItem('alles-name','local greeting')"
                    )
                    page.goto(base, wait_until="networkidle")
                    expect(page.locator("#setup-wizard")).to_be_visible()
                    if page.locator("#sw-back").is_visible():
                        page.locator("#sw-back").click()
                    field = page.locator("#sw-name")
                    expect(field).to_have_accessible_name("username")
                    expect(field).to_have_attribute("autocomplete", "username")
                    expect(field).to_have_accessible_description(
                        "Synced across your apps. Set a separate greeting name for this browser in Settings → General."
                    )
                    username = "owner & 研究 " + label
                    field.fill(username)
                    page.screenshot(path=str(out / f"{label}-setup.png"))
                    page.route(
                        base + "/api/setup/step",
                        lambda route: route.fulfill(
                            status=503, json={"message": "synthetic save interruption"}
                        ),
                        times=1,
                    )
                    page.locator("#sw-save").press("Enter")
                    expect(page.locator("#sw-status")).to_contain_text(
                        "synthetic save interruption"
                    )
                    expect(field).to_have_value(username)
                    page.locator("#sw-save").press("Enter")
                    expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
                    page.reload(wait_until="networkidle")
                    expect(page.locator("#setup-dots")).to_contain_text("2 / 5")
                    page.locator("#setup-skip").click()
                    page.locator("#today-settings").click()
                    choose_settings_section(page, "general")
                    expect(page.locator("#s-username")).to_have_value(username)
                    greeting = page.locator("#s-user-name")
                    expect(greeting).to_have_accessible_name(
                        "greeting name : aide uses it in this browser"
                    )
                    expect(greeting).to_have_value("local greeting")
                    greeting.fill("new local greeting")
                    assert (
                        page.evaluate("localStorage.getItem('alles-name')") == "new local greeting"
                    )
                    assert context.request.get(base + "/api/auth/me").json()["username"] == username
                    page.screenshot(path=str(out / f"{label}-settings.png"))
                    page.locator("#settings-modal-close").click()
                    page.reload(wait_until="networkidle")
                    assert (
                        page.evaluate("localStorage.getItem('alles-name')") == "new local greeting"
                    )

                    page.goto(base + "/?view=files", wait_until="networkidle")
                    filename = "notes & 研究 " + label + ".txt"
                    content = ("owned original " + label).encode()
                    page.locator("#files-upload-input").set_input_files(
                        {"name": filename, "mimeType": "text/plain", "buffer": content}
                    )
                    row = page.locator(f'.file-row[data-path="{filename}"]')
                    expect(row).to_be_visible()
                    row.press("Enter")
                    delete = page.locator('[data-detail-action="delete"]')
                    delete.press("Enter")
                    dialog = page.get_by_role("alertdialog")
                    expect(dialog).to_have_accessible_name(
                        f"move “{filename}” to recently deleted? you can restore it there."
                    )
                    expect(dialog.get_by_role("button", name="cancel", exact=True)).to_be_focused()
                    page.screenshot(path=str(out / f"{label}-delete.png"))
                    page.keyboard.press("Escape")
                    expect(delete).to_be_focused()
                    expect(row).to_be_visible()
                    delete.press("Enter")
                    dialog.get_by_role("button", name="move to recently deleted", exact=True).press(
                        "Enter"
                    )
                    expect(row).to_have_count(0)
                    page.locator('[data-files-view="trash"]').click()
                    trashed = page.locator(".file-row[data-trash-id]").filter(has_text=filename)
                    expect(trashed).to_be_visible()
                    trashed.press("Enter")
                    page.locator('[data-detail-action="restore"]').press("Enter")
                    expect(trashed).to_have_count(0)
                    page.locator('[data-files-view="all"]').click()
                    expect(row).to_be_visible()
                    row.press("Enter")
                    download = page.locator("#files-detail-content a[download]")
                    response = context.request.get(base + download.get_attribute("href"))
                    assert response.ok and response.body() == content
                    page.locator("#files-detail-close").click()
                    long_name = "local-" + "r" * 160 + "-" + label + ".txt"
                    page.locator("#files-upload-input").set_input_files(
                        {
                            "name": long_name,
                            "mimeType": "text/plain",
                            "buffer": b"owned second file",
                        }
                    )
                    second = page.locator(f'.file-row[data-path="{long_name}"]')
                    expect(second).to_be_visible()
                    second.press("Enter")
                    delete.press("Enter")
                    expect(dialog).to_contain_text(long_name)
                    assert dialog.locator(".dialog-msg").evaluate(
                        "node => node.scrollWidth <= node.clientWidth"
                    )
                    bounds = dialog.bounding_box()
                    assert bounds and bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 900, (
                        bounds
                    )
                    page.screenshot(path=str(out / f"{label}-long-name.png"))
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.keyboard.press("Escape")
                    page.locator("#files-detail-close").click()
                    row.locator("[data-file-select]").click()
                    second.locator("[data-file-select]").click()
                    page.locator('[data-files-bulk="delete"]').press("Enter")
                    expect(dialog).to_have_accessible_name(
                        "move 2 items to recently deleted? you can restore them there."
                    )
                    expect(dialog.get_by_role("button", name="cancel", exact=True)).to_be_focused()
                    page.keyboard.press("Escape")
                    expect(row).to_be_visible()
                    expect(second).to_be_visible()

                    page.goto(base + "/?view=system", wait_until="networkidle")
                    host = page.locator("#system-host")
                    expect(host).to_be_visible()

                    def motion():
                        return host.evaluate(
                            "e=>{const s=getComputedStyle(e,'::after');return {name:s.animationName,count:s.animationIterationCount,opacity:s.opacity}}"
                        )

                    reduced = motion()
                    assert reduced["name"] == "none" and reduced["opacity"] == "1", reduced
                    page.emulate_media(reduced_motion="no-preference")
                    normal = motion()
                    assert normal["name"] == "sys-blink" and normal["count"] == "infinite", normal
                    page.emulate_media(reduced_motion="reduce")
                    assert motion()["name"] == "none"
                    result.update(reduced_motion=reduced, normal_motion=normal)
                    assert not errors and not external, (errors, external)
                    assert len(console) == 1 and "503" in console[0], console
                    result.update(
                        status="passed",
                        page_errors=errors,
                        console_errors=console,
                        external_attempts=external,
                    )
                except Exception as error:
                    result.update(error=str(error), traceback=traceback.format_exc())
                    page.screenshot(path=str(out / f"{label}-failed.png"))
                finally:
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(results, indent=2) + "\n")
        browser.close()
    assert all(row["status"] == "passed" for row in results), results


if __name__ == "__main__":
    run()
