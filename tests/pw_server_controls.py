"""Server setting focus, shared switches and policy recovery on owned local data."""

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
                "scenario_id": "server.controls",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                assert context.request.patch(
                    base + "/api/settings",
                    data={
                        "search_result_count": 5,
                        "andromeda_verification_enabled": True,
                    },
                ).ok
                # Reset only this run's disposable policy fixture.
                (Path(os.environ["ALLES_DATA"]) / "server-policy.json").unlink(missing_ok=True)
                page.goto(base + "/?view=server-search", wait_until="networkidle")
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
                group = page.get_by_role("radiogroup", name="results per search")

                def radio(value):
                    return group.get_by_role("radio", name=str(value), exact=True)

                radio(5).focus()
                for value in [8, 10]:
                    page.keyboard.press("ArrowRight")
                    expect(group).not_to_have_attribute("aria-busy", "true")
                    expect(radio(value)).to_have_attribute("aria-checked", "true")
                    expect(radio(value)).to_be_focused()
                    assert (
                        context.request.get(base + "/api/settings").json()["search_result_count"]
                        == value
                    )
                page.screenshot(path=str(out / f"{label}-radio.png"))

                held = []

                def hold_patch(route):
                    if route.request.method == "PATCH":
                        held.append(route)
                    else:
                        route.continue_()

                page.route(base + "/api/settings", hold_patch)
                page.keyboard.press("ArrowRight")
                expect(group).to_have_attribute("aria-busy", "true")
                expect(radio(12)).to_be_disabled()
                away = page.get_by_label("answer tokens", exact=True)
                away.focus()
                expect(away).to_be_focused()
                assert len(held) == 1
                held.pop().continue_()
                expect(group).not_to_have_attribute("aria-busy", "true")
                expect(away).to_be_focused()
                assert (
                    context.request.get(base + "/api/settings").json()["search_result_count"] == 12
                )
                radio(12).focus()
                page.keyboard.press("Home")
                expect(group).to_have_attribute("aria-busy", "true")
                assert len(held) == 1
                held.pop().fulfill(
                    status=503, json={"detail": "synthetic setting save failed; try again"}
                )
                expect(radio(12)).to_be_enabled()
                expect(radio(12)).to_have_attribute("aria-checked", "true")
                expect(radio(12)).to_be_focused()
                assert (
                    context.request.get(base + "/api/settings").json()["search_result_count"] == 12
                )
                page.screenshot(path=str(out / f"{label}-radio-failed.png"))
                page.unroute(base + "/api/settings", hold_patch)
                page.keyboard.press("Home")
                expect(radio(5)).to_be_enabled()
                expect(radio(5)).to_be_focused()
                assert (
                    context.request.get(base + "/api/settings").json()["search_result_count"] == 5
                )

                toggle = page.get_by_role("switch", name="background fact check", exact=True)
                toggle.focus()
                for key, checked in [("Enter", False), ("Space", True)]:
                    page.keyboard.press(key)
                    expect(toggle).to_be_enabled()
                    expect(toggle).to_have_attribute("aria-checked", str(checked).lower())
                    expect(toggle).to_be_focused()
                    assert (
                        context.request.get(base + "/api/settings").json()[
                            "andromeda_verification_enabled"
                        ]
                        is checked
                    )
                box = toggle.bounding_box()
                geometry = toggle.evaluate(
                    "e => {const track=getComputedStyle(e,'::before'),knob=getComputedStyle(e,'::after');return {track:[track.width,track.height,track.borderRadius],knob:[knob.width,knob.height,knob.borderRadius],transition:knob.transitionDuration}}"
                )
                assert box["width"] == 44 and box["height"] == 44, box
                assert geometry["track"] == ["42px", "24px", "999px"], geometry
                assert geometry["knob"][:3] == ["16px", "16px", "50%"], geometry
                assert all(
                    float(x.strip().removesuffix("s")) <= 0.001
                    for x in geometry["transition"].split(",")
                ), geometry
                page.screenshot(path=str(out / f"{label}-switch.png"))
                page.route(base + "/api/settings", hold_patch)
                page.keyboard.press("Space")
                expect(toggle).to_be_disabled()
                expect(toggle).to_have_attribute("aria-busy", "true")
                page.screenshot(path=str(out / f"{label}-switch-saving.png"))
                assert len(held) == 1
                held.pop().fulfill(
                    status=503, json={"detail": "synthetic setting save failed; try again"}
                )
                expect(toggle).to_be_enabled()
                expect(toggle).to_be_focused()
                expect(toggle).to_have_attribute("aria-checked", "true")
                page.keyboard.press("Space")
                expect(toggle).to_be_disabled()
                away.focus()
                assert len(held) == 1
                held.pop().continue_()
                expect(toggle).to_be_enabled()
                expect(away).to_be_focused()
                expect(toggle).to_have_attribute("aria-checked", "false")
                page.unroute(base + "/api/settings", hold_patch)
                page.reload(wait_until="networkidle")
                expect(toggle).to_have_attribute("aria-checked", "false")
                expect(radio(5)).to_have_attribute("aria-checked", "true")

                # A newer busy control keeps focus even when an older save finishes first.
                page.route(base + "/api/settings", hold_patch)
                radio(5).focus()
                page.keyboard.press("ArrowRight")
                expect(group).to_have_attribute("aria-busy", "true")
                toggle.focus()
                page.keyboard.press("Space")
                expect(toggle).to_be_disabled()
                assert len(held) == 2
                held.pop(0).continue_()
                expect(group).not_to_have_attribute("aria-busy", "true")
                expect(toggle).to_be_focused()
                held.pop().continue_()
                expect(toggle).to_be_enabled()
                expect(toggle).to_be_focused()
                page.keyboard.press("Space")
                expect(toggle).to_be_disabled()
                radio(8).focus()
                page.keyboard.press("ArrowRight")
                expect(group).to_have_attribute("aria-busy", "true")
                assert len(held) == 2
                held.pop(0).continue_()
                expect(toggle).to_be_enabled()
                expect(radio(10)).to_be_focused()
                held.pop().continue_()
                expect(group).not_to_have_attribute("aria-busy", "true")
                expect(radio(10)).to_be_focused()
                page.unroute(base + "/api/settings", hold_patch)
                page.goto(base + "/?view=server-policy", wait_until="networkidle")
                policy = page.locator(".server-workbench-card").filter(
                    has=page.get_by_role("heading", name="server access policy", exact=True)
                )
                expect(policy).to_contain_text("host controls unavailable")
                expect(policy).not_to_contain_text("policy_missing")
                expect(policy).to_contain_text("Nothing outside Alles can be controlled")
                editor = policy.locator("textarea")
                original = editor.input_value()
                editor.fill("{")
                policy.get_by_role("button", name="validate and show diff").click()
                expect(policy.locator(".server-workbench-status").first).to_have_class(
                    "server-workbench-status is-error"
                )
                expect(editor).to_have_value("{")
                assert not context.request.get(base + "/api/system/policy").json()["valid"]
                page.screenshot(path=str(out / f"{label}-policy-missing.png"))
                editor.fill(original)
                policy.get_by_role("button", name="save policy", exact=True).click()
                expect(policy).to_contain_text("saved and verified")
                expect(policy).not_to_contain_text("host controls unavailable")
                saved = context.request.get(base + "/api/system/policy").json()
                assert saved["valid"] and saved["policy"]["control_mode"] == "owned_only"
                page.reload(wait_until="networkidle")
                expect(policy).not_to_contain_text("host controls unavailable")
                expect(policy).not_to_contain_text("policy_missing")
                page.screenshot(path=str(out / f"{label}-policy-saved.png"))
                assert not errors, errors
                assert (
                    len(console) == 3
                    and sum("503" in message for message in console) == 2
                    and sum("422" in message for message in console) == 1
                ), console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                row.update(
                    status="passed",
                    switch_geometry=geometry,
                    native_zoom=zoom,
                    boundary="real local settings and owned-only policy saves; synthetic failed responses; no service actions",
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
