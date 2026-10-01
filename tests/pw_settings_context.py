"""Settings context visibility and preferences in independent authenticated sessions.

Owns disposable loopback servers and synthetic credentials. Browser input uses
pointer, touch and keyboard; DOM evaluation only reads state and geometry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from pw_settings_helpers import choose_settings_section, settings_section_focus_target  # noqa: E402
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)
from stabilization_report import source_fingerprint  # noqa: E402

PASSWORD = "synthetic-settings-context-owner-passphrase"
EXPECTED = {
    "context_limit": 57,
    "stream_thinking": False,
    "language": "fr",
    "clock_format": "24",
    "week_start": "mon",
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


@contextmanager
def fixture(dest, authenticated, cleanup):
    with owned_data() as (data, run_id):
        port = free_port()
        env = isolated_environment(data, run_id, port, dest)
        env["AUTH_ENABLED"] = "true" if authenticated else "false"
        if authenticated:
            env["AUTH_PASSWORD"] = PASSWORD
            env["SECRET_KEY"] = "synthetic-settings-context-secret"
        record = {"data_root": str(data), "run_id": run_id, "port": port, "artifact": str(dest)}
        cleanup.append(record)
        with (dest / "server.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=False,
            )
            record["server_pid"] = process.pid
            try:
                wait_for_server(process, port, run_id, 90)
                yield f"http://127.0.0.1:{port}"
            finally:
                stop_process(process, process_group=False)
                record["server_stopped"] = process.poll() is not None


@contextmanager
def session(browser, base, dest, profile, width=None):
    context = browser.new_context(
        base_url=base,
        viewport={
            "width": width or (390 if profile == "phone" else 1440),
            "height": 844 if profile == "phone" else 900,
        },
        is_mobile=profile == "phone",
        has_touch=profile == "phone",
        locale="en-CA",
        timezone_id="America/Toronto",
        color_scheme="dark",
        reduced_motion="reduce",
        service_workers="block",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(12000)
    events = []
    page.on("pageerror", lambda error: events.append({"kind": "pageerror", "error": str(error)}))
    page.on(
        "console",
        lambda msg: (
            events.append({"kind": "console", "text": msg.text}) if msg.type == "error" else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            events.append({"kind": "http", "url": response.url, "status": response.status})
            if response.status >= 400
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda req: events.append(
            {"kind": "requestfailed", "url": req.url, "failure": req.failure}
        ),
    )
    try:
        yield context, page
        assert not events, events
    except BaseException:
        page.screenshot(path=str(dest / "failure.png"), full_page=True)
        raise
    finally:
        dump(dest / "events.json", events)
        context.tracing.stop(path=str(dest / "trace.zip"))
        context.close()


def tab_to(page, target, reverse=False):
    for count in range(161):
        if target.evaluate("e => e === document.activeElement"):
            expect(target).to_be_in_viewport()
            return count
        page.keyboard.press("Shift+Tab" if reverse else "Tab")
    raise AssertionError("control was unreachable by keyboard")


def open_pane(page, name):
    if not page.locator("#settings-modal").is_visible():
        page.locator("#today-settings").click()
    choose_settings_section(page, name)
    expect(page.locator("#s-pane-" + name)).to_be_visible()
    if name == "notifications":
        expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    if name == "ai":
        expect(page.locator("#settings-context-limit")).not_to_have_value("")


def save_locale(page, language):
    page.locator(f'[data-locale-language="{language}"]').click()
    with page.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PATCH"
    ) as response:
        page.locator("#s-locale-save").click()
    assert response.value.ok
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    expect(page.locator("html")).to_have_attribute("dir", "rtl" if language == "ar" else "ltr")


def navigation(page, api, dest, profile, records):
    observations = []
    compact = page.viewport_size["width"] <= 760
    assert api.post("/api/setup/dismiss").ok
    page.goto("/?view=today")
    expect(page.locator("#setup-wizard")).to_be_hidden()
    page.locator("#today-settings").click()

    def observe(label):
        title = page.locator("#settings-pane-title")
        current = page.locator(".s-nav-item.active")
        expect(title).to_have_text(current.inner_text())
        expect(title).to_be_in_viewport(ratio=1)
        expect(page.locator("#settings-modal-close")).to_be_in_viewport(ratio=1)
        expect(page.locator("#settings-modal")).to_have_accessible_name(
            "alles settings " + current.inner_text()
        )
        actual = page.evaluate("""() => {
          const rect = e => { const r=e.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}; };
          const nav=document.querySelector('.s-nav'), box=nav.getBoundingClientRect();
          return {dir:document.documentElement.dir, context:document.querySelector('#settings-pane-title').textContent,
            header:rect(document.querySelector('.s-header')), contextRect:rect(document.querySelector('#settings-pane-title')),
            close:rect(document.querySelector('#settings-modal-close')),
            focus:document.activeElement.dataset.pane || document.activeElement.dataset.localeLanguage,
            navScroll:nav.scrollLeft,
            tabs:[...document.querySelectorAll('.s-nav-item')].map(e=>{
              const r=e.getBoundingClientRect(),s=getComputedStyle(e);
              return {pane:e.dataset.pane,active:e.classList.contains('active'),current:e.getAttribute('aria-current'),hover:e.matches(':hover'),
                decoration:s.textDecorationLine,visible:r.right>box.left&&r.left<box.right&&r.bottom>box.top&&r.top<box.bottom};
            }), panes:[...document.querySelectorAll('.s-pane')].filter(e=>e.getBoundingClientRect().height>0).map(e=>e.id)};
        }""")
        active = [t for t in actual["tabs"] if t["active"]]
        assert len(active) == 1 and active[0]["current"] == "page", actual
        assert actual["panes"] == ["s-pane-" + active[0]["pane"]], actual
        assert active[0]["decoration"] == "underline", actual
        assert all(t["decoration"] != "underline" for t in actual["tabs"] if not t["active"]), (
            actual
        )
        header, context, close = actual["header"], actual["contextRect"], actual["close"]
        assert context["top"] >= header["top"] and context["bottom"] <= header["bottom"], actual
        assert context["right"] <= close["left"] or close["right"] <= context["left"], actual
        page.screenshot(path=str(dest / (label + ".png")), full_page=True)
        actual["label"] = label
        observations.append(actual)
        dump(dest / "observations.json", observations)
        return actual

    open_pane(page, "general")
    page.wait_for_load_state("networkidle")
    expect(page.locator("#s-user-name")).to_have_accessible_name(re.compile(r"^your name"))
    expect(page.locator("#s-username")).to_have_accessible_name(re.compile(r"^username"))
    expect(page.locator("#s-ui-font-size")).to_have_accessible_name("font size")
    for selector, label in (
        ("#s-welcome-toggle", "welcome message"),
        ("#s-ui-compact-toggle", "compact mode"),
        ('[data-vis-key="bar-mic"]', "microphone"),
    ):
        expect(page.locator(selector)).to_have_accessible_name(label)
        page.locator(selector).focus()
        previous = page.locator(selector).get_attribute("aria-checked")
        page.keyboard.press("Space")
        expect(page.locator(selector)).to_have_attribute(
            "aria-checked", str(previous != "true").lower()
        )
        page.keyboard.press("Space")
        expect(page.locator(selector)).to_have_attribute("aria-checked", previous)
    assert page.locator('[data-vis-key^="nav-"]').count() == 0
    open_pane(page, "home")
    expect(page.locator("#home-settings-workbench")).to_have_attribute("aria-busy", "false")
    preview = page.locator(".home-settings-preview")
    assert preview.get_attribute("open") is None
    controls_box = page.locator(".home-settings-controls").bounding_box()
    preview_box = preview.bounding_box()
    if compact:
        assert controls_box["y"] < preview_box["y"]
    preview.locator("summary").click()
    expect(page.locator("#home-settings-preview-list")).to_be_visible()
    preview.locator("summary").click()
    expect(page.locator("#home-settings-preview-list")).to_be_hidden()
    open_pane(page, "notifications")
    menus = []
    for name in ("region", "timezone", "currency"):
        trigger = page.locator(f'[data-locale-choice="{name}"]')
        trigger.focus()
        page.keyboard.press("ArrowDown")
        menu = page.locator(f'[data-locale-menu="{name}"]')
        expect(menu).to_be_visible()
        assert menu.evaluate("e => e.parentElement.id") == "settings-modal"
        page.keyboard.press("End")
        last = menu.locator('[role="option"]').last
        expect(last).to_be_focused()
        expect(last).to_be_in_viewport(ratio=1)
        box = menu.bounding_box()
        assert box["x"] >= 8 and box["x"] + box["width"] <= page.viewport_size["width"] - 7
        assert box["y"] >= 8 and box["y"] + box["height"] <= page.viewport_size["height"] - 7
        page.screenshot(path=str(dest / f"locale-{name}-end.png"))
        menus.append({"name": name, "box": box, "last_option_visible": True})
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        expect(menu).to_be_hidden()
        assert menu.evaluate("e => e.parentElement.className") == "locale-choice-wrap"
        trigger.click()
        menu.locator('[aria-selected="true"]').click()
        expect(trigger).to_be_focused()
        expect(menu).to_be_hidden()
    dump(
        dest / "usability.json",
        {
            "profile_labels": True,
            "live_switches_named": 3,
            "retired_dead_controls": 8,
            "home_controls_first": compact,
            "locale_menus": menus,
        },
    )
    page.locator("#settings-modal-close").click()
    page.locator("#today-settings").click()

    # Discover the destination by real Tab traversal from the Home settings entry.
    compact = page.locator("#settings-section-trigger").is_visible()
    if compact:
        expect(page.locator("#settings-section-trigger")).to_be_focused()
        page.keyboard.press("Enter")
    tab_to(page, page.locator('.s-nav-item[data-pane="notifications"]'))
    page.keyboard.press("Enter")
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    observe("01-language-entry")

    for language in ("en", "ar"):
        if language == "ar":
            save_locale(page, language)
            page.reload()
            open_pane(page, "notifications")
        nav_scroll = None
        if compact:
            page.locator("#settings-section-trigger").click()
            expect(page.locator('.s-nav-item[data-pane="notifications"]')).to_be_focused()
        for pane in ("rules", "credits", "backup"):
            page.keyboard.press("Tab")
            target = page.locator(f'.s-nav-item[data-pane="{pane}"]')
            expect(target).to_be_focused()
            expect(target).to_be_in_viewport()
            # Focus does not select another pane or snap the strip back to it.
            state = observe(f"{language}-focus-{pane}")
            if pane == "backup":
                nav_scroll = state["navScroll"]
        page.keyboard.press("Tab")
        expect(page.locator(f'[data-locale-language="{language}"]')).to_be_focused()
        after = observe(f"{language}-controls-hover")
        if profile == "phone":
            assert after["navScroll"] == nav_scroll, after
        page.mouse.move(page.viewport_size["width"] - 1, 1)
        observe(f"{language}-controls-no-hover")
        target = settings_section_focus_target(page, "notifications")
        assert tab_to(page, target, reverse=True) == (1 if compact else 4)
        observe(f"{language}-keyboard-return")

    # Touch switches the pane and persistent context together, without mouse hover.
    if profile == "phone":
        choose_settings_section(page, "credits", touch=True)
        observe("touch-credits")
        choose_settings_section(page, "notifications", touch=True)
        observe("touch-language")
    # The longest shipped destination is checked without inventing a long label.
    open_pane(page, "tools")
    observe("long-destination")
    # All destinations keep the header in sync. Real pointer activation preserves
    # normal loading paths; unexpected network/console errors fail the session.
    for name in (
        "general",
        "home",
        "themes",
        "ai",
        "search",
        "voice",
        "personas",
        "proactive",
        "intelligence",
        "models",
        "memory",
        "recall",
        "developer",
        "security",
        "rules",
        "backup",
    ):
        open_pane(page, name)
        observe("pane-" + name)
    open_pane(page, "themes")
    with page.expect_response(
        lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
    ) as response:
        page.locator('[data-theme-mode="light"]').click()
    assert response.value.ok
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    open_pane(page, "notifications")
    tab_to(page, page.locator('[data-locale-language="ar"]'))
    observe("light-scrolled-context")
    page.keyboard.press("Escape")
    expect(page.locator("#settings-modal")).to_be_hidden()
    expect(page.locator("#today-settings")).to_be_focused()
    page.locator("#today-settings").click()
    observe("reopened-home")
    records.append(
        {
            "scenario_id": "settings.navigation-context",
            "profile": profile,
            "width": page.viewport_size["width"],
            "status": "passed",
            "states": len(observations),
        }
    )


def authenticate(context, page):
    assert context.cookies() == []
    assert context.storage_state()["origins"] == []
    initial = context.request.get("/api/auth/me").json()
    assert initial["enabled"] and not initial["authenticated"], initial
    page.goto("/?view=today")
    expect(page.locator("#login-pw")).to_be_visible()
    page.locator("#login-pw").fill(PASSWORD)
    page.locator("#login-pw").press("Enter")
    expect(page.locator("#login-pw")).to_be_hidden()
    auth = context.request.get("/api/auth/me").json()
    assert auth["enabled"] and auth["authenticated"], auth
    cookie = next(c for c in context.cookies() if c["name"] == "aide_session")
    return {
        "initial_cookie_count": 0,
        "initial_origin_count": 0,
        "initial_authenticated": False,
        "authenticated": True,
        "cookie_digest": hashlib.sha256(cookie["value"].encode()).hexdigest(),
    }


def change_preferences(page):
    open_pane(page, "ai")
    page.locator("#settings-context-limit").fill("57")
    with page.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PATCH"
    ) as response:
        page.locator("#settings-save-btn").click()
    assert response.value.ok
    expect(page.locator("#s-pane-ai .settings-save-state")).to_contain_text("saved")
    expect(page.locator("#s-thinking-toggle")).to_have_attribute("aria-checked", "true")
    tab_to(page, page.locator("#s-thinking-toggle"))
    with page.expect_response(
        lambda r: r.url.endswith("/api/settings") and r.request.method == "PATCH"
    ) as response:
        page.keyboard.press("Space")
    assert response.value.ok
    expect(page.locator("#s-thinking-toggle")).to_have_attribute("aria-checked", "false")
    open_pane(page, "themes")
    with page.expect_response(
        lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
    ) as response:
        page.locator('[data-theme-mode="light"]').click()
    assert response.value.ok
    open_pane(page, "notifications")
    page.locator('[data-locale-format="clock_format"][data-value="24"]').click()
    page.locator('[data-locale-format="week_start"][data-value="mon"]').click()
    save_locale(page, "fr")


def verify_preferences(context, page, dest):
    saved = context.request.get("/api/settings").json()
    assert {key: saved[key] for key in EXPECTED} == EXPECTED
    appearance = context.request.get("/api/appearance").json()
    assert appearance["preset"] == "light" and appearance["_stored"]
    open_pane(page, "ai")
    expect(page.locator("#settings-context-limit")).to_have_value("57")
    expect(page.locator("#s-thinking-toggle")).to_have_attribute("aria-checked", "false")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.screenshot(path=str(dest / "chat.png"), full_page=True)
    open_pane(page, "notifications")
    expect(page.locator('[data-locale-language="fr"]')).to_have_attribute("aria-checked", "true")
    expect(page.locator('[data-locale-format="clock_format"][data-value="24"]')).to_have_attribute(
        "aria-checked", "true"
    )
    expect(page.locator('[data-locale-format="week_start"][data-value="mon"]')).to_have_attribute(
        "aria-checked", "true"
    )
    expect(page.locator("html")).to_have_attribute("lang", "fr-CA")
    expect(page.locator("#s-locale-save")).to_have_text("enregistrer la langue et la région")
    page.screenshot(path=str(dest / "locale.png"), full_page=True)
    tab_to(page, page.locator('[data-locale-format="clock_format"][data-value="24"]'))
    page.screenshot(path=str(dest / "saved-formats.png"), full_page=True)
    dump(
        dest / "saved.json",
        {
            "settings": EXPECTED,
            "appearance": appearance["preset"],
            "lang": "fr-CA",
            "save_label": page.locator("#s-locale-save").inner_text(),
        },
    )


def run():
    output = Path(
        os.environ.get("ALLES_BROWSER_ARTIFACTS")
        or tempfile.mkdtemp(prefix="alles-settings-context-")
    )
    output.mkdir(parents=True, exist_ok=True)
    records, cleanup = [], []
    before = source_fingerprint(ROOT)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            dump(
                output / "environment.json",
                {
                    "browser": browser.version,
                    "source_fingerprint": before,
                    "reduced_motion": True,
                    "locale": "en-CA",
                    "timezone": "America/Toronto",
                },
            )
            try:
                for profile, width in (("desktop", 1440), ("phone", 390), ("phone", 320)):
                    dest = output / f"navigation-{width}"
                    dest.mkdir(exist_ok=True)
                    with fixture(dest, False, cleanup) as base:
                        with session(browser, base, dest, profile, width) as (context, page):
                            navigation(page, context.request, dest, profile, records)
                for profile in ("desktop", "phone"):
                    dest = output / ("persistence-" + profile)
                    dest.mkdir(exist_ok=True)
                    auth = []
                    with fixture(dest, True, cleanup) as base:
                        for index in (1, 2):
                            child = dest / f"session-{index}"
                            child.mkdir(exist_ok=True)
                            with session(browser, base, child, profile) as (context, page):
                                auth.append(authenticate(context, page))
                                if index == 1:
                                    assert context.request.post("/api/setup/dismiss").ok
                                    page.reload()
                                    change_preferences(page)
                                    page.reload()
                                verify_preferences(context, page, child)
                        assert auth[0]["cookie_digest"] != auth[1]["cookie_digest"]
                        dump(dest / "authentication-sessions.json", auth)
                    records.append(
                        {
                            "scenario_id": "settings.persistence",
                            "profile": profile,
                            "status": "passed",
                            "fields": EXPECTED,
                            "appearance": "light",
                            "reload": True,
                            "fresh_authenticated_sessions": 2,
                            "copied_browser_storage": False,
                        }
                    )
            finally:
                browser.close()
    finally:
        for record in cleanup:
            record["data_removed"] = not Path(record["data_root"]).exists()
            with socket.socket() as sock:
                sock.settimeout(0.2)
                record["port_closed"] = sock.connect_ex(("127.0.0.1", record["port"])) != 0
        dump(output / "owned-fixtures.json", cleanup)
        dump(output / "scenarios.json", records)
        dump(output / "source-closure.json", {"before": before, "after": source_fingerprint(ROOT)})
    assert all(r["server_stopped"] and r["data_removed"] and r["port_closed"] for r in cleanup), (
        cleanup
    )
    assert before == source_fingerprint(ROOT)
    print(json.dumps({"status": "passed", "scenarios": len(records)}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    run()
