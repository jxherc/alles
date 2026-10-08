"""Task help and Settings names preserve the actual workflow and saved choices."""

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
from pw_settings_helpers import choose_settings_section

from services.appearance import from_legacy


def check_instruction_recovery(page, api, base):
    field = page.locator("#settings-owner-instructions")
    save = page.locator("#s-owner-instructions-save")
    endpoint = base + "/api/settings"

    def clear():
        page.locator("#toast-container").evaluate("e => e.replaceChildren()")

    def saved(value):
        save.press("Enter")
        expect(save).to_be_enabled()
        expect(page.locator("#toast-container .toast.success").last).to_have_text(
            "owner instructions saved"
        )
        expect(field).to_have_attribute("data-dirty", "0")
        assert api.get(endpoint).json()["owner_instructions"] == value.strip()

    for failure in ("rejected", "non-json", "wrong-value", "lost-response"):
        clear()
        draft = "owned recovery " + failure
        field.fill(draft)

        def fail(route):
            if route.request.method != "PATCH":
                return route.continue_()
            if failure == "rejected":
                route.fulfill(status=503, json={"detail": "owned save rejected"})
            elif failure == "non-json":
                route.fulfill(status=200, content_type="text/plain", body="not an acknowledgement")
            elif failure == "wrong-value":
                route.fulfill(json={"owner_instructions": "different instructions"})
            else:
                response = route.fetch()
                assert response.ok
                route.abort("failed")

        page.route(endpoint, fail)
        save.press("Enter")
        expect(page.locator("#toast-container .toast.error").last).to_be_visible()
        expect(save).to_be_enabled()
        expect(field).to_have_value(draft)
        expect(field).to_have_attribute("data-dirty", "1")
        expect(page.locator("#toast-container .toast.success")).to_have_count(0)
        page.unroute(endpoint, fail)
        choose_settings_section(page, "ai")
        choose_settings_section(page, "memory")
        expect(field).to_have_value(draft)
        clear()
        saved(draft)

    held_writes, held_reads = [], []
    holding = {"reads": False}

    def hold(route):
        if route.request.method == "PATCH":
            held_writes.append(route)
        elif holding["reads"]:
            held_reads.append(route)
        else:
            route.continue_()

    def wait_for_requests(items, count):
        for _ in range(100):
            if len(items) >= count:
                break
            page.wait_for_timeout(20)
        assert len(items) == count, (len(items), count)

    page.route(endpoint, hold)
    clear()
    field.fill("owned earlier pending edit")
    save.press("Enter")
    wait_for_requests(held_writes, 1)
    expect(save).to_be_disabled()
    save.dispatch_event("click")
    field.fill("owned newer pending edit 中文")
    write = held_writes.pop()
    assert write.request.post_data_json == {"owner_instructions": "owned earlier pending edit"}
    write.fulfill(response=write.fetch())
    expect(page.locator("#toast-container .toast.success").last).to_have_text(
        "earlier instructions saved; your latest edits still need saving"
    )
    expect(field).to_have_value("owned newer pending edit 中文")
    expect(field).to_have_attribute("data-dirty", "1")
    assert not held_writes
    page.unroute(endpoint, hold)
    clear()
    saved("owned newer pending edit 中文")

    # A read begun during a pending write must not overwrite its confirmed result.
    snapshot = api.get(endpoint).json()
    page.route(endpoint, hold)
    clear()
    field.fill("owned confirmed latest edit")
    save.press("Enter")
    wait_for_requests(held_writes, 1)
    with page.expect_response(lambda r: r.url == endpoint and r.request.method == "GET"):
        choose_settings_section(page, "ai")
    holding["reads"] = True
    choose_settings_section(page, "memory")
    # The memory list and owner-instructions field each read Settings.
    wait_for_requests(held_reads, 2)
    write = held_writes.pop()
    write.fulfill(response=write.fetch())
    expect(field).to_have_attribute("data-dirty", "0")
    holding["reads"] = False
    for route in held_reads:
        route.fulfill(json=snapshot)
    held_reads.clear()
    page.wait_for_load_state("networkidle")
    expect(field).to_have_value("owned confirmed latest edit")
    assert api.get(endpoint).json()["owner_instructions"] == "owned confirmed latest edit"

    # Leave and reopen while the old read is pending; the newest read owns the field.
    choose_settings_section(page, "ai")
    page.wait_for_load_state("networkidle")
    holding["reads"] = True
    choose_settings_section(page, "memory")
    wait_for_requests(held_reads, 2)
    holding["reads"] = False
    choose_settings_section(page, "ai")
    choose_settings_section(page, "memory")
    expect(field).to_have_value("owned confirmed latest edit")
    for route in held_reads:
        route.fulfill(json=snapshot)
    held_reads.clear()
    page.wait_for_load_state("networkidle")
    expect(field).to_have_value("owned confirmed latest edit")
    page.unroute(endpoint, hold)

    # A malformed read must retain the displayed value and offer a retry.
    choose_settings_section(page, "ai")
    page.wait_for_load_state("networkidle")
    clear()

    def malformed(route):
        route.fulfill(json={})

    page.route(endpoint, malformed)
    choose_settings_section(page, "memory")
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "could not load owner instructions; reopen this section to retry"
    )
    expect(field).to_have_value("owned confirmed latest edit")
    page.unroute(endpoint, malformed)
    choose_settings_section(page, "ai")
    choose_settings_section(page, "memory")
    expect(field).to_have_value("owned confirmed latest edit")
    return ["503", "net::ERR_FAILED"]


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
                    "scenario_id": "aide.task-help",
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

                try:
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss").ok
                    assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                    assert api.patch(
                        base + "/api/settings",
                        data={
                            "language": "en",
                            "context_limit": 37,
                            "owner_instructions": "owned saved instructions",
                            "insights_enabled": False,
                            "user_model_distill": False,
                        },
                    ).ok
                    page.goto(base + "/?view=chat", wait_until="networkidle")
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
                    field = page.locator("#composer-ta")
                    field.fill("owned unsent question 中文")
                    help_button = page.locator("#aide-help")
                    help_button.press("Enter")
                    dialog = page.get_by_role("dialog", name="aide help", exact=True)
                    expect(dialog).to_be_visible()
                    expect(dialog.locator("[data-help-close]")).to_be_focused()
                    expect(dialog.locator("[data-help-guide]")).to_have_count(7)
                    search = dialog.get_by_role("searchbox", name="search help", exact=True)
                    status = dialog.locator(".aide-help-status")
                    assert status.evaluate(
                        "e=>getComputedStyle(e).display!=='none' && !e.closest('[hidden]')"
                    )
                    capture("guides")
                    search.fill("+plan task")
                    expect(dialog.locator('[data-help-guide="task"]')).to_be_visible()
                    expect(dialog.locator("[data-help-entry]:visible")).to_have_count(1)
                    expect(dialog).to_contain_text("add to plan")
                    expect(field).to_have_value("owned unsent question 中文")
                    search.fill("RETRY RESPONSE")
                    expect(dialog.locator('[data-help-guide="recovery"]')).to_be_visible()
                    expect(dialog.locator("[data-help-entry]:visible")).to_have_count(1)
                    expect(dialog).to_contain_text("review task activity before sending again")
                    capture("recovery-guide")
                    search.fill("/todo")
                    expect(
                        dialog.locator(".aide-help-commands [data-help-entry]:visible")
                    ).to_have_count(1)
                    expect(
                        dialog.locator(".aide-help-commands [data-help-entry]:visible")
                    ).to_contain_text("add a task to Plan")
                    search.fill("no matching owned phrase")
                    expect(status).to_have_text("no matching help. try another word.")
                    expect(dialog.locator("[data-help-group]:visible")).to_have_count(0)
                    expect(search).to_be_focused()
                    search.fill("")
                    expect(dialog.locator("[data-help-group]:visible")).to_have_count(3)
                    expect(status).to_be_empty()
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
                    expect(help_button).to_be_focused()
                    help_button.press("Enter")
                    expect(search).to_have_value("")
                    dialog.locator('[data-help-settings="models"]').press("Enter")
                    expect(page.locator("#s-pane-models")).to_be_visible()
                    expect(page.locator("#settings-pane-title")).to_have_text("models")
                    page.locator("#settings-modal-close").press("Enter")
                    expect(help_button).to_be_focused()
                    expect(field).to_have_value("owned unsent question 中文")
                    # The actual Settings picker keeps all19 panes and each stored owner.
                    help_button.press("Enter")
                    dialog.locator('[data-help-settings="models"]').press("Enter")
                    expect(page.locator("#s-pane-models")).to_be_visible()
                    names = {
                        "ai": "chat display & context",
                        "memory": "memory & instructions",
                        "recall": "search personal records",
                        "intelligence": "patterns & suggestions",
                        "rules": "automation & delivery",
                    }
                    expect(page.locator(".s-nav-item")).to_have_count(19)
                    for pane, name in names.items():
                        choose_settings_section(page, pane, touch=width <= 390)
                        expect(page.locator("#settings-pane-title")).to_have_text(name)
                        expect(page.locator("#s-pane-" + pane)).to_be_visible()
                        expect(page.locator(f'.s-nav-item[data-pane="{pane}"]')).to_have_attribute(
                            "aria-current", "page"
                        )
                        capture("settings-" + pane)
                    choose_settings_section(page, "ai")
                    expect(page.locator("#settings-context-limit")).to_have_value("37")
                    choose_settings_section(page, "memory")
                    instructions = page.locator("#settings-owner-instructions")
                    expect(instructions).to_have_value("owned saved instructions")
                    instructions.fill("owned edited instructions 中文")
                    choose_settings_section(page, "recall")
                    choose_settings_section(page, "memory")
                    expect(instructions).to_have_value("owned edited instructions 中文")
                    with page.expect_response(
                        lambda r: r.url == base + "/api/settings" and r.request.method == "PATCH"
                    ) as saved:
                        page.locator("#s-owner-instructions-save").press("Enter")
                    assert saved.value.ok
                    assert (
                        api.get(base + "/api/settings").json()["owner_instructions"]
                        == "owned edited instructions 中文"
                    )
                    page.locator("#settings-modal-close").press("Enter")
                    expect(field).to_have_value("owned unsent question 中文")
                    page.reload(wait_until="networkidle")
                    help_button.press("Enter")
                    dialog.locator('[data-help-settings="models"]').press("Enter")
                    expect(page.locator("#s-pane-models")).to_be_visible()
                    choose_settings_section(page, "memory")
                    expect(instructions).to_have_value("owned edited instructions 中文")
                    expected_errors = check_instruction_recovery(page, api, base)
                    current = api.get(base + "/api/settings").json()
                    assert (
                        current["context_limit"] == 37
                        and current["insights_enabled"] is False
                        and current["user_model_distill"] is False
                    )
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    assert not external and not errors, (external, errors)
                    assert len(console) == len(expected_errors) and all(
                        any(expected in message for message in console)
                        for expected in expected_errors
                    ), console
                    row.update(
                        status="passed",
                        checks="five concrete guides, search/case/commands/no-match/reset, keyboard/Escape/focus, model settings destination, composer draft,19panes/labels, original context/settings values, instruction draft across panes and save/reload, native200 fullCDP, themes/reduced motion, console/overflow",
                    )
                except Exception:
                    row["error"] = traceback.format_exc()
                    capture("failed")
                finally:
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
