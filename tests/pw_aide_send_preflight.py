"""Composer preflight uses an owned application and a synthetic loopback model."""

import json
import os
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_aide_continuity import Provider

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
state = Provider()
provider = ThreadingHTTPServer(("127.0.0.1", 0), state.handler())
provider.daemon_threads = True
thread = threading.Thread(target=provider.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(w, t) for w in [1440, 820, 390] for t in ["dark", "light"]]:
            for case in [
                "no-model",
                "create-failed",
                "newer-draft",
                "switched-task",
                "switched-new",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                api = context.request
                context.route(
                    "**/*",
                    lambda r: (
                        r.continue_()
                        if urlparse(r.request.url).netloc == urlparse(base).netloc
                        else r.abort()
                    ),
                )
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                endpoint = None
                page = context.new_page()
                page.set_default_timeout(3000)
                errors = []
                console_errors = []
                posts = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "console",
                    lambda m: console_errors.append(m.text) if m.type == "error" else None,
                )
                page.on(
                    "request",
                    lambda r: (
                        posts.append(r.url)
                        if r.method == "POST"
                        and r.url in [base + "/api/sessions", base + "/api/chat"]
                        else None
                    ),
                )
                result = {
                    "scenario_id": "aide.send-preflight." + case,
                    "profile": f"{width}-{theme}",
                    "status": "failed",
                }
                rows.append(result)

                def configure():
                    global endpoint
                    endpoint = api.post(
                        base + "/api/models/endpoint",
                        data={
                            "name": "owned preflight",
                            "base_url": f"http://127.0.0.1:{provider.server_port}",
                            "provider_adapter": "manual",
                        },
                    ).json()
                    assert api.patch(
                        base + "/api/models/endpoint/" + endpoint["id"],
                        data={"models": ["continuity-fixture"]},
                    ).ok
                    assert api.patch(
                        base + "/api/settings",
                        data={
                            "default_endpoint_id": endpoint["id"],
                            "default_model": "continuity-fixture",
                            "memory_policy": "off",
                            "memory_auto_inject": False,
                        },
                    ).ok

                def close_sidebar():
                    backdrop = page.locator("#nav-backdrop")
                    if backdrop.is_visible():
                        backdrop.click(position={"x": width - 15, "y": 150})

                def load():
                    page.goto(base + "/?view=chat", wait_until="networkidle")
                    close_sidebar()

                try:
                    if case != "no-model":
                        configure()
                    if case == "switched-task":
                        existing = api.post(
                            base + "/api/sessions", data={"name": "other saved task"}
                        ).json()
                    load()
                    field = page.locator("#composer-ta")
                    text = "keep this exact thought  中文\n  before sending"
                    field.fill(text)
                    held = []
                    failing = case == "create-failed"
                    holding = case == "newer-draft"

                    def fail(route):
                        route.fulfill(
                            status=503, json={"detail": "owned preflight unavailable"}
                        ) if failing and route.request.method == "POST" else route.continue_()

                    def hold(route):
                        if holding and route.request.method == "POST":
                            held.append((route, route.fetch()))
                        else:
                            route.continue_()

                    def hold_failure(route):
                        if route.request.method == "POST":
                            held.append(route)
                        else:
                            route.continue_()

                    if case.startswith("switched-"):
                        page.route(base + "/api/sessions", hold_failure)
                    if case == "create-failed":
                        page.route(base + "/api/sessions", fail)
                    if case == "newer-draft":
                        page.route(base + "/api/sessions", hold)
                    field.press("Enter")
                    if case.startswith("switched-"):
                        deadline = time.monotonic() + 4
                        while not held and time.monotonic() < deadline:
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        if width < 700:
                            page.locator("#sidebar-toggle-btn").click()
                        if case == "switched-task":
                            page.locator(
                                f'.session-item[data-id="{existing["id"]}"] .session-open'
                            ).click()
                            expect(page).to_have_url(base + "/?view=chat#" + existing["id"])
                        else:
                            page.locator("#new-chat-btn").click()
                        close_sidebar()
                        field.fill("new context draft")
                        held[0].fulfill(
                            status=503, json={"detail": "owned delayed creation failure"}
                        )
                        page.wait_for_timeout(200)
                        expect(page.locator("#composer-send-recovery")).to_be_hidden()
                        expect(field).to_have_value("new context draft")
                        if case == "switched-task":
                            assert page.evaluate("localStorage.getItem('aide-draft-new')") == text
                    elif case == "newer-draft":
                        deadline = time.monotonic() + 4
                        while not held and time.monotonic() < deadline:
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        field.fill("a newer draft to keep")
                        field.press("Enter")
                        page.wait_for_timeout(100)
                        assert posts.count(base + "/api/sessions") == 1, posts
                        holding = False
                        held[0][0].fulfill(response=held[0][1])
                        expect(page.locator(".user-bubble").last).to_have_text(text.strip())
                        expect(field).to_have_value("a newer draft to keep")
                    else:
                        expect(field).to_have_value(text)
                        expect(page.locator("#composer-send-recovery")).to_be_visible()
                        expect(field).to_be_focused()
                        if case == "create-failed":
                            expect(page.locator("#composer-choose-model")).to_be_hidden()
                        assert page.evaluate("localStorage.getItem('aide-draft-new')") == text
                        page.screenshot(path=str(out / f"{width}-{theme}-{case}-recovery.png"))
                        if case == "no-model":
                            assert not posts, posts
                            page.locator("#composer-choose-model").focus()
                            page.keyboard.press("Enter")
                            expect(page.locator("#model-modal")).to_be_visible()
                            page.keyboard.press("Escape")
                            expect(page.locator("#model-modal")).not_to_be_visible()
                            expect(page.locator("#composer-choose-model")).to_be_focused()
                            expect(page.locator("#composer-choose-model")).to_have_attribute(
                                "aria-expanded", "false"
                            )
                            configure()
                        else:
                            failing = False
                        page.reload(wait_until="networkidle")
                        close_sidebar()
                        expect(field).to_have_value(text)
                        field.press("Enter")
                        expect(page.locator(".user-bubble").last).to_have_text(text.strip())
                        expect(field).to_have_value("")
                    expect(page.locator("#send-btn")).to_be_enabled(timeout=12000)
                    expect(page.locator("#composer-send-recovery")).to_be_hidden()
                    if case == "newer-draft":
                        page.evaluate(
                            "localStorage.setItem('aide-draft-new', 'separate unsent draft')"
                        )
                        page.reload(wait_until="networkidle")
                        close_sidebar()
                        expect(field).to_have_value("a newer draft to keep")
                        assert (
                            page.evaluate("localStorage.getItem('aide-draft-new')")
                            == "separate unsent draft"
                        )
                    unexpected_console = [
                        m
                        for m in console_errors
                        if not (
                            (case == "create-failed" or case.startswith("switched-")) and "503" in m
                        )
                    ]
                    assert not unexpected_console, unexpected_console
                    assert not errors, errors
                    result["status"] = "passed"
                except Exception as e:
                    result.update(error=str(e), traceback=traceback.format_exc())
                finally:
                    result.update(page_errors=errors, console_errors=console_errors, posts=posts)
                    page.screenshot(path=str(out / f"{width}-{theme}-{case}.png"))
                    if endpoint:
                        assert api.delete(base + "/api/models/endpoint/" + endpoint["id"]).ok
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
finally:
    provider.shutdown()
    provider.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    (out / "provider-cleanup.json").write_text(json.dumps({"stopped": True}))
raise SystemExit(any(r["status"] != "passed" for r in rows))
