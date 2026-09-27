"""Settings persistence, explicit response faults, ordering and regional controls.

Runs only owned synthetic loopback servers. Faults are Playwright response/transport
simulations; successful and deliberately delayed writes use the real backend.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

from services.appearance import from_legacy  # noqa: E402


def wait_for(page, predicate):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(50)
    raise AssertionError("expected state did not arrive")


def assert_expected_events(events):
    assert events["pageerrors"] == [], events["pageerrors"]
    errors = Counter(item["text"] for item in events["console"] if item["type"] == "error")
    assert errors == Counter(
        {
            "Failed to load resource: the server responded with a status of 503 (Service Unavailable)": 5,
            "Failed to load resource: net::ERR_CONNECTION_FAILED": 2,
        }
    ), errors
    responses = Counter(
        (item["method"], urlparse(item["path"]).path, item["status"])
        for item in events["responses"]
    )
    assert responses == Counter(
        {
            ("PATCH", "/api/settings", 503): 4,
            ("PUT", "/api/appearance", 503): 1,
        }
    ), responses
    failures = Counter(
        (item["method"], urlparse(item["path"]).path, item["failure"])
        for item in events["failed_requests"]
    )
    assert failures == Counter(
        {
            ("PATCH", "/api/settings", "net::ERR_CONNECTION_FAILED"): 1,
            ("PUT", "/api/appearance", "net::ERR_CONNECTION_FAILED"): 1,
        }
    ), failures


def exercise(page, api, dest, profile, restart, records):
    keyboard_routes = []

    def active_control():
        return page.evaluate("""(()=>{const e=document.activeElement; return {
          tag:e?.tagName, id:e?.id, role:e?.getAttribute('role'),
          language:e?.dataset.localeLanguage, value:e?.dataset.value,
          text:e?.textContent.trim().slice(0,80)
        }})()""")

    def tab_to(target, label, limit=160):
        route = {"target": label, "keys": [], "start": active_control()}
        keyboard_routes.append(route)
        for _ in range(limit + 1):
            if target.evaluate("e => e === document.activeElement"):
                expect(target).to_be_in_viewport()
                route["end"] = active_control()
                route["status"] = "reached"
                (dest / "keyboard-traversal.json").write_text(json.dumps(keyboard_routes, indent=2))
                return
            if len(route["keys"]) == limit:
                break
            page.keyboard.press("Tab")
            route["keys"].append({"key": "Tab", "active": active_control()})
        route["status"] = "unreachable"
        (dest / "keyboard-traversal.json").write_text(json.dumps(keyboard_routes, indent=2))
        raise AssertionError(f"{label} was not reachable within {limit} Tab presses")

    def settings():
        response = api.get("/api/settings")
        assert response.ok, response.text()
        return response.json()

    def appearance():
        response = api.get("/api/appearance")
        assert response.ok, response.text()
        return response.json()

    def pane(name, reload=False):
        if reload or page.url == "about:blank":
            page.goto("/?view=today")
            expect(page.locator("#setup-wizard")).to_be_hidden()
        if not page.locator("#settings-modal").is_visible():
            page.locator("#today-settings").click()
        page.locator(f'.s-nav-item[data-pane="{name}"]').click()
        expect(page.locator("#s-pane-" + name)).to_be_visible()
        if name == "ai":
            expect(page.locator("#settings-context-limit")).not_to_have_value("")
        if name == "notifications":
            expect(page.locator("#locale-settings-workbench")).to_have_attribute(
                "aria-busy", "false"
            )

    def record(scenario, **details):
        records.append({"scenario_id": scenario, "profile": profile, "status": "passed", **details})
        (dest.parent / "scenarios.json").write_text(json.dumps(records, indent=2))

    def shot(name):
        page.screenshot(path=str(dest / (name + ".png")), full_page=True)

    def submit(value):
        page.locator("#settings-context-limit").fill(str(value))
        page.locator("#settings-save-btn").click()

    def locale_fields():
        return page.evaluate("""({
          language: document.querySelector('[data-locale-language][aria-checked=true]').dataset.localeLanguage,
          region: document.querySelector('#s-region-trigger').dataset.value,
          timezone: document.querySelector('#s-timezone-trigger').dataset.value,
          currency: document.querySelector('#s-currency-trigger').dataset.value,
          clock_format: document.querySelector('[data-locale-format=clock_format][aria-checked=true]').dataset.value,
          week_start: document.querySelector('[data-locale-format=week_start][aria-checked=true]').dataset.value
        })""")

    def choice(name, value):
        trigger = page.locator("#s-" + name + "-trigger")
        tab_to(trigger, name + " dropdown")
        page.keyboard.press("Enter")
        expect(page.locator("#s-" + name + "-menu")).to_be_visible()
        for _ in range(100):
            if page.evaluate("document.activeElement.dataset.value") == value:
                break
            page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.dataset.value") == value
        page.keyboard.press("Enter")
        expect(trigger).to_have_attribute("data-value", value)
        expect(trigger).to_be_focused()

    def locale_save():
        page.locator("#s-locale-save").click()
        expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")

    pane("ai", True)
    submit(55)
    wait_for(page, lambda: settings()["context_limit"] == 55)
    pane("ai", True)
    expect(page.locator("#settings-context-limit")).to_have_value("55")
    toggle = page.locator("#s-thinking-toggle")
    tab_to(toggle, "streaming thinking switch")
    page.keyboard.press("Space")
    wait_for(page, lambda: settings()["stream_thinking"] is False)
    expect(toggle).not_to_have_attribute("aria-busy", "true")

    def reject(route):
        if route.request.method == "PATCH":
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"simulated settings rejection"}',
            )
        else:
            route.continue_()

    page.route("**/api/settings", reject)
    submit(77)
    expect(page.locator("#s-pane-ai .settings-save-state")).to_have_attribute("data-state", "error")
    expect(page.locator("#settings-context-limit")).to_have_value("77")
    assert settings()["context_limit"] == 55
    toggle.click()
    expect(toggle).not_to_have_attribute("aria-busy", "true")
    expect(toggle).to_have_attribute("aria-checked", "false")
    assert settings()["stream_thinking"] is False
    shot("01-rejected-settings")
    page.unroute("**/api/settings", reject)
    submit(77)
    wait_for(page, lambda: settings()["context_limit"] == 77)
    toggle.click()
    wait_for(page, lambda: settings()["stream_thinking"] is True)
    pane("ai", True)
    expect(page.locator("#settings-context-limit")).to_have_value("77")
    expect(toggle).to_have_attribute("aria-checked", "true")
    record(
        "settings.rejected-save-recovery",
        fault="simulated HTTP503",
        values={"context_limit": 77, "stream_thinking": True},
    )

    held = []

    def hold_settings(route):
        if route.request.method == "PATCH":
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/settings", hold_settings)
    submit(51)
    wait_for(page, lambda: len(held) == 1)
    submit(52)
    page.wait_for_timeout(450)
    assert len(held) == 1, "later save reached the network before its predecessor settled"
    response = held[0].fetch()
    assert response.ok
    held[0].fulfill(response=response)
    wait_for(page, lambda: len(held) == 2)
    response = held[1].fetch()
    assert response.ok
    held[1].fulfill(response=response)
    page.unroute("**/api/settings", hold_settings)
    wait_for(page, lambda: settings()["context_limit"] == 52)
    expect(page.locator("#settings-context-limit")).to_have_value("52")
    pane("ai", True)
    expect(page.locator("#settings-context-limit")).to_have_value("52")
    shot("02-ordered-settings")
    record(
        "settings.ordered-saves",
        writes=[json.loads(route.request.post_data)["context_limit"] for route in held],
        stored=52,
    )

    held = []
    page.route("**/api/settings", hold_settings)
    toggle.click()
    wait_for(page, lambda: len(held) == 1)
    toggle.click()
    expect(toggle).to_have_attribute("aria-checked", "true")
    page.wait_for_timeout(150)
    assert len(held) == 1
    held[0].fulfill(
        status=503,
        content_type="application/json",
        body='{"detail":"simulated earlier toggle rejection"}',
    )
    wait_for(page, lambda: len(held) == 2)
    response = held[1].fetch()
    assert response.ok
    held[1].fulfill(response=response)
    page.unroute("**/api/settings", hold_settings)
    expect(toggle).not_to_have_attribute("aria-busy", "true")
    expect(toggle).to_have_attribute("aria-checked", "true")
    assert settings()["stream_thinking"] is True
    record(
        "settings.switch-queued-recovery",
        fault="first queued switch explicitly rejected with HTTP503",
        writes=[False, True],
        stored=True,
    )

    pane("themes")
    page.locator('[data-theme-mode="light"]').click()
    wait_for(page, lambda: appearance()["preset"] == "light")
    expect(page.locator("#s-pane-themes .theme-save-state")).to_have_attribute(
        "data-state", "saved"
    )

    def reject_theme(route):
        if route.request.method == "PUT":
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"simulated appearance rejection"}',
            )
        else:
            route.continue_()

    page.route("**/api/appearance", reject_theme)
    page.locator('[data-theme-mode="dark"]').click()
    state = page.locator("#s-pane-themes .theme-save-state")
    expect(state).to_have_attribute("data-state", "error")
    assert appearance()["preset"] == "light"
    shot("03-theme-rejection")
    pane("themes", True)
    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
    expect(state).to_have_attribute("data-state", "error")
    assert appearance()["preset"] == "light"
    shot("04-theme-recovery-after-reload")
    page.unroute("**/api/appearance", reject_theme)
    state.get_by_role("button", name="retry theme save").click()
    expect(state).to_have_attribute("data-state", "saved")
    wait_for(page, lambda: appearance()["preset"] == "dark")
    assert page.evaluate("localStorage.getItem('alles-appearance-pending')") is None
    pane("themes", True)
    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
    record(
        "settings.theme-rejected-save-recovery",
        fault="simulated HTTP503",
        recovered_after_reload=True,
        stored="dark",
    )

    for fault in ("invalid-json", "incomplete-json", "transport"):
        prior = appearance()["preset"]
        target = "light" if prior == "dark" else "dark"

        def theme_fault(route):
            if route.request.method != "PUT":
                route.continue_()
            elif fault == "transport":
                route.abort("connectionfailed")
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body="{" if fault == "invalid-json" else '{"colors":{}}',
                )

        page.route("**/api/appearance", theme_fault)
        page.locator(f'[data-theme-mode="{target}"]').click()
        expect(state).to_have_attribute("data-state", "error")
        assert appearance()["preset"] == prior
        assert (
            page.evaluate("JSON.parse(localStorage.getItem('alles-appearance-pending')).preset")
            == target
        )
        shot("04-theme-" + fault)
        page.unroute("**/api/appearance", theme_fault)
        state.get_by_role("button", name="retry theme save").click()
        expect(state).to_have_attribute("data-state", "saved")
        assert appearance()["preset"] == target
    record(
        "settings.theme-response-recovery",
        faults=["invalid JSON200", "incomplete JSON200", "transport abort"],
        stored=target,
    )

    held = []

    def hold_theme(route):
        if route.request.method == "PUT":
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/appearance", hold_theme)
    page.locator('[data-theme-mode="dark"]').click()
    wait_for(page, lambda: len(held) == 1)
    page.locator('[data-theme-mode="light"]').click()
    page.wait_for_timeout(450)
    assert len(held) == 1, "appearance PUT requests overlapped"
    response = held[0].fetch()
    assert response.ok
    held[0].fulfill(response=response)
    wait_for(page, lambda: len(held) == 2)
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    response = held[1].fetch()
    assert response.ok
    held[1].fulfill(response=response)
    page.unroute("**/api/appearance", hold_theme)
    expect(state).to_have_attribute("data-state", "saved")
    assert appearance()["preset"] == "light"
    pane("themes", True)
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    shot("05-ordered-theme")
    record(
        "settings.theme-ordered-saves",
        writes=[json.loads(route.request.post_data)["preset"] for route in held],
        stored="light",
    )

    pane("notifications")
    choice("region", "FR")
    choice("timezone", "Asia/Taipei")
    choice("currency", "JPY")
    page.locator('[data-locale-format="clock_format"][data-value="24"]').click()
    page.locator('[data-locale-format="week_start"][data-value="mon"]').click()
    locale_save()
    before = locale_fields()
    assert all(settings()[key] == value for key, value in before.items())
    choice("region", "JP")
    draft = locale_fields()
    for fault in ("http503", "invalid-json", "incomplete-json", "transport"):

        def locale_fault(route):
            if route.request.method != "PATCH":
                route.continue_()
            elif fault == "transport":
                route.abort("connectionfailed")
            else:
                route.fulfill(
                    status=503 if fault == "http503" else 200,
                    content_type="application/json",
                    body='{"detail":"simulated rejection"}'
                    if fault == "http503"
                    else "{"
                    if fault == "invalid-json"
                    else "{}",
                )

        page.route("**/api/settings", locale_fault)
        locale_save()
        assert locale_fields() == draft
        assert settings()["region"] == "FR"
        expect(page.locator("#locale-settings-save-state")).not_to_have_text("saved just now")
        shot("06-locale-" + fault)
        page.unroute("**/api/settings", locale_fault)
    locale_save()
    assert all(settings()[key] == value for key, value in draft.items())
    pane("notifications", True)
    assert locale_fields() == draft
    record(
        "settings.locale-response-recovery",
        faults=["simulated HTTP503", "invalid JSON200", "incomplete JSON200", "transport abort"],
        values=draft,
    )

    expect(page.locator("#s-timezone-detected")).to_contain_text("America/Toronto")
    choice("timezone", "")
    expect(page.locator("#locale-preview-timezone")).to_have_text("automatic · America/Toronto")
    page.locator(".locale-settings-preview").scroll_into_view_if_needed()
    shot("07-automatic-timezone")
    locale_save()
    assert settings()["timezone"] == ""
    choice("timezone", "Asia/Taipei")
    locale_save()
    record(
        "settings.browser-timezone",
        browser=page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone"),
        saved_override="Asia/Taipei",
    )

    language_writes = []

    def capture_language_write(request):
        if request.method == "PATCH" and urlparse(request.url).path == "/api/settings":
            language_writes.append(request.post_data_json)

    page.on("request", capture_language_write)
    regional_before = locale_fields()
    assert regional_before["language"] == "en"
    languages = page.locator("[data-locale-language]").evaluate_all(
        "es => es.filter(e => !e.disabled && e.getAttribute('aria-disabled') !== 'true').map(e => e.dataset.localeLanguage)"
    )
    assert languages == ["en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar"]
    language_route = {"target": "language radio group", "keys": []}
    keyboard_routes.append(language_route)

    def radio_state(selector, attribute, value):
        selected = page.locator(f'{selector}[{attribute}="{value}"]')
        expect(selected).to_be_focused()
        expect(selected).to_be_in_viewport()
        expect(selected).to_have_attribute("aria-checked", "true")
        expect(selected).to_have_attribute("tabindex", "0")
        assert page.locator(f'{selector}[aria-checked="true"]').count() == 1
        assert page.locator(f'{selector}[tabindex="0"]').count() == 1
        assert page.locator(f'{selector}[aria-checked="false"][tabindex="-1"]').count() == (
            page.locator(selector).count() - 1
        )
        focus = selected.evaluate(
            "e => ({visible:e.matches(':focus-visible'), outline:getComputedStyle(e).outlineStyle, width:getComputedStyle(e).outlineWidth})"
        )
        assert focus["visible"] and focus["outline"] != "none" and focus["width"] != "0px", focus

    def language_key(key, value):
        page.keyboard.press(key)
        radio_state("[data-locale-language]", "data-locale-language", value)
        language_route["keys"].append({"key": key, "language": value, "active": active_control()})
        (dest / "keyboard-traversal.json").write_text(json.dumps(keyboard_routes, indent=2))

    def format_keys(direction):
        for name in ("clock_format", "week_start"):
            selector = f'[data-locale-format="{name}"]'
            values = page.locator(selector).evaluate_all("es => es.map(e => e.dataset.value)")
            original = locale_fields()[name]
            tab_to(page.locator(f'{selector}[tabindex="0"]'), direction + " " + name)
            for key, value in (
                ("Home", values[0]),
                ("ArrowDown", values[1]),
                ("End", values[-1]),
                ("ArrowDown", values[0]),
                ("ArrowUp", values[-1]),
                ("Home", values[0]),
            ):
                page.keyboard.press(key)
                radio_state(selector, "data-value", value)
            for value in values[1 : values.index(original) + 1]:
                page.keyboard.press("ArrowDown")
                radio_state(selector, "data-value", value)
            assert locale_fields()[name] == original

    tab_to(page.locator('#locale-language-list [tabindex="0"]'), "current language LTR")
    radio_state("[data-locale-language]", "data-locale-language", "en")
    shot("08-language-tab-entry")
    for value in languages[1:]:
        language_key("ArrowDown", value)
    for key, value in (
        ("ArrowDown", "en"),
        ("ArrowUp", "ar"),
        ("Home", "en"),
        ("ArrowRight", "fr"),
        ("ArrowLeft", "en"),
        ("End", "ar"),
        ("Home", "en"),
        ("ArrowDown", "fr"),
    ):
        language_key(key, value)
    page.keyboard.press("Tab")
    expect(page.locator("#s-region-trigger")).to_be_focused()
    format_keys("LTR")
    regional_draft = {**regional_before, "language": "fr"}
    assert locale_fields() == regional_draft
    expect(page.locator("#locale-settings-save-state")).to_have_text("unsaved changes")
    pane("ai")
    pane("notifications")
    assert locale_fields() == regional_draft
    assert all(settings()[key] == value for key, value in regional_before.items())
    assert language_writes == [], language_writes
    tab_to(page.locator('#locale-language-list [tabindex="0"]'), "retained unsaved language")
    radio_state("[data-locale-language]", "data-locale-language", "fr")
    shot("08-language-unsaved-draft")
    language_key("End", "ar")
    assert language_writes == [], language_writes
    tab_to(page.locator("#s-locale-save"), "deliberate language Save")
    page.keyboard.press("Enter")
    wait_for(page, lambda: settings()["language"] == "ar")
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    assert len(language_writes) == 1 and language_writes[0]["language"] == "ar"
    pane("notifications", True)
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    assert locale_fields() == {**regional_before, "language": "ar"}
    tab_to(page.locator('#locale-language-list [tabindex="0"]'), "saved language RTL")
    radio_state("[data-locale-language]", "data-locale-language", "ar")
    for key, value in (
        ("ArrowRight", "ko"),
        ("ArrowLeft", "ar"),
        ("ArrowDown", "en"),
        ("ArrowUp", "ar"),
        ("Home", "en"),
        ("End", "ar"),
    ):
        language_key(key, value)
    shot("08-language-rtl-keyboard-focus")
    format_keys("RTL")
    assert locale_fields() == {**regional_before, "language": "ar"}
    assert all(settings()[key] == value for key, value in locale_fields().items())
    assert len(language_writes) == 1, language_writes
    locale_save()
    assert len(language_writes) == 2 and language_writes[1]["language"] == "ar"
    page.remove_listener("request", capture_language_write)
    record(
        "settings.language-keyboard",
        feature="localization.regional-settings",
        enabled_languages=languages,
        directions=["LTR", "RTL"],
        sibling_groups=["clock_format", "week_start"],
        draft_retained=regional_draft,
        writes=language_writes,
        keyboard_events=language_route["keys"],
    )
    page.locator("#s-timezone-trigger").scroll_into_view_if_needed()
    rect = page.locator("#settings-modal .s-modal").bounding_box()
    viewport = page.evaluate("document.documentElement.clientWidth")
    overlay = page.locator("#settings-modal").bounding_box()
    assert overlay["x"] >= -1 and overlay["width"] >= viewport - 1
    assert rect["x"] >= 0 and rect["x"] + rect["width"] <= viewport + 1
    hit = page.locator("#s-timezone-trigger").evaluate(
        "e=>{let r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.right-5,r.y+r.height/2))}"
    )
    assert hit, "settings overlay covers the timezone control"
    page.locator("#s-timezone-trigger").click()
    expect(page.locator("#s-timezone-menu")).to_be_visible()
    shot("08-arabic-menu")
    page.keyboard.press("Escape")
    expect(page.locator("#s-timezone-trigger")).to_be_focused()
    pane("recall")
    page.locator("#s-pidx-clear").click()
    dialog = page.locator(".dialog-overlay .dialog-card")
    expect(dialog).to_be_visible()
    rect2 = dialog.bounding_box()
    assert rect2["x"] >= 0 and rect2["x"] + rect2["width"] <= viewport + 1
    shot("09-arabic-confirm-dialog")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.locator("#s-pidx-clear")).to_be_focused()
    record("settings.rtl-overlay", settings_rect=rect, dialog_rect=rect2, overlay_rect=overlay)
    pane("notifications")
    page.locator('[data-locale-language="en"]').click()
    locale_save()

    pane("themes")
    color = page.locator("#theme-editor-inline .cp-swatch-input").first
    tab_to(color, "theme background color")
    shot("10-color-keyboard-focus")
    page.keyboard.press("Enter")
    picker = page.locator(".cp-popover")
    expect(picker).to_be_visible()
    expect(picker.locator(".cp-hex")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(picker.locator(".cp-done")).to_be_focused()
    page.keyboard.press("Tab")
    expect(picker.locator(".cp-hex")).to_be_focused()
    picker.locator(".cp-hex").fill("#eeeeee")
    page.keyboard.press("Enter")
    expect(picker).to_be_hidden()
    expect(color).to_be_focused()
    wait_for(page, lambda: appearance()["colors"]["bg"] == "#eeeeee")
    page.keyboard.press("Space")
    expect(picker).to_be_visible()
    shot("10-color-keyboard")
    page.keyboard.press("Escape")
    expect(picker).to_be_hidden()
    expect(color).to_be_focused()
    expect(page.locator("#settings-modal")).to_be_visible()
    color.click()
    expect(picker).to_be_visible()
    picker.locator(".cp-done").click()
    expect(color).to_be_focused()
    rect = color.bounding_box()
    assert rect["width"] >= 44 and rect["height"] >= 44
    assert (
        page.locator(
            '#settings-modal input[type="color"]:visible, #settings-modal select:visible'
        ).count()
        == 0
    )
    pane("themes", True)
    expect(page.locator("#theme-editor-inline .cp-swatch-input").first).to_have_value("#eeeeee")
    record(
        "settings.color-keyboard",
        stored_color="#eeeeee",
        opener_rect=rect,
        keyboard=["Enter", "Space", "Escape", "Tab", "Shift+Tab"],
    )

    pane("general")
    compact = page.locator("#s-ui-compact-toggle")
    tab_to(compact, "compact mode switch")
    page.keyboard.press("Space")
    expect(compact).to_have_attribute("aria-checked", "true")
    font = page.locator("#s-ui-font-size")
    tab_to(font, "font size dropdown")
    shot("11-font-keyboard-focus")
    page.keyboard.press("Enter")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    expect(font).to_have_attribute("data-value", "lg")
    pane("general", True)
    expect(compact).to_have_attribute("aria-checked", "true")
    expect(font).to_have_attribute("data-value", "lg")
    before = {
        key: settings()[key]
        for key in (
            "language",
            "region",
            "timezone",
            "currency",
            "clock_format",
            "week_start",
            "context_limit",
            "stream_thinking",
        )
    }
    theme_before = appearance()
    # Close the page before the owned restart, avoiding unrelated polling failures.
    page.goto("about:blank")
    restart()
    assert {key: settings()[key] for key in before} == before
    assert appearance() == theme_before
    pane("notifications", True)
    assert all(
        locale_fields()[key] == value for key, value in before.items() if key in locale_fields()
    )
    shot("11-after-restart")
    record("settings.restart-persistence", values=before, appearance=theme_before)


def run():
    output = Path(
        os.environ.get("ALLES_BROWSER_ARTIFACTS")
        or tempfile.mkdtemp(prefix="alles-settings-recovery-")
    )
    output.mkdir(parents=True, exist_ok=True)
    records, cleanup = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for profile in ("desktop", "phone"):
                    dest = output / profile
                    dest.mkdir(exist_ok=True)
                    with owned_data() as (data, run_id):
                        port = free_port()
                        env = isolated_environment(data, run_id, port, dest)
                        fixture = {
                            "profile": profile,
                            "data_root": str(data),
                            "port": port,
                            "run_id": run_id,
                            "server_stopped": True,
                        }
                        cleanup.append(fixture)
                        process = None
                        with (dest / "server.log").open("w") as log:

                            def start():
                                child = subprocess.Popen(
                                    [sys.executable, "app.py"],
                                    cwd=ROOT,
                                    env=env,
                                    stdout=log,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=False,
                                )
                                try:
                                    wait_for_server(child, port, run_id, 90)
                                except BaseException:
                                    stop_process(child, process_group=False)
                                    raise
                                return child

                            def restart():
                                nonlocal process
                                stop_process(process, process_group=False)
                                process = start()

                            process = start()
                            fixture["server_stopped"] = False
                            try:
                                context = browser.new_context(
                                    base_url=f"http://127.0.0.1:{port}",
                                    viewport={
                                        "width": 390 if profile == "phone" else 1440,
                                        "height": 844 if profile == "phone" else 900,
                                    },
                                    is_mobile=profile == "phone",
                                    has_touch=profile == "phone",
                                    locale="en-CA",
                                    timezone_id="America/Toronto",
                                    reduced_motion="reduce",
                                    service_workers="block",
                                )
                                events = {
                                    "pageerrors": [],
                                    "console": [],
                                    "responses": [],
                                    "failed_requests": [],
                                }
                                page = None
                                try:
                                    context.tracing.start(
                                        screenshots=True, snapshots=True, sources=True
                                    )
                                    api = context.request
                                    assert api.post("/api/setup/dismiss").ok
                                    assert api.put(
                                        "/api/appearance", data=from_legacy("dark", None)
                                    ).ok
                                    assert api.patch(
                                        "/api/settings",
                                        data={
                                            "language": "en",
                                            "region": "",
                                            "timezone": "",
                                            "currency": "",
                                            "clock_format": "auto",
                                            "week_start": "auto",
                                            "context_limit": 40,
                                            "stream_thinking": True,
                                        },
                                    ).ok
                                    page = context.new_page()
                                    page.set_default_timeout(12000)
                                    page.on(
                                        "pageerror", lambda e: events["pageerrors"].append(str(e))
                                    )
                                    page.on(
                                        "console",
                                        lambda m: events["console"].append(
                                            {"type": m.type, "text": m.text}
                                        ),
                                    )
                                    page.on(
                                        "response",
                                        lambda r: (
                                            events["responses"].append(
                                                {
                                                    "path": r.url,
                                                    "method": r.request.method,
                                                    "status": r.status,
                                                }
                                            )
                                            if r.status >= 400
                                            else None
                                        ),
                                    )
                                    page.on(
                                        "requestfailed",
                                        lambda r: events["failed_requests"].append(
                                            {
                                                "path": r.url,
                                                "method": r.method,
                                                "failure": r.failure,
                                            }
                                        ),
                                    )
                                    exercise(page, api, dest, profile, restart, records)
                                    assert_expected_events(events)
                                except BaseException:
                                    page.screenshot(path=str(dest / "failure.png"), full_page=True)
                                    raise
                                finally:
                                    (dest / "events.json").write_text(json.dumps(events, indent=2))
                                    context.tracing.stop(path=str(dest / "trace.zip"))
                                    context.close()
                            finally:
                                stop_process(process, process_group=False)
                                fixture["server_stopped"] = process.poll() is not None
            finally:
                browser.close()
    finally:
        for fixture in cleanup:
            fixture["data_removed"] = not Path(fixture["data_root"]).exists()
            with socket.socket() as sock:
                sock.settimeout(0.2)
                fixture["port_closed"] = sock.connect_ex(("127.0.0.1", fixture["port"])) != 0
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))
        (output / "owned-fixtures.json").write_text(json.dumps(cleanup, indent=2))
    print(json.dumps({"status": "passed", "scenarios": len(records), "cleanup": cleanup}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    run()
