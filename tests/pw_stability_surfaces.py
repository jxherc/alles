"""Rendered resting surfaces, not complete workflow or accessibility certification.

Each profile uses an owned server from run_browser_gates.py. Real local APIs seed
Tasks, Docs and Files; no credentials, remote models or external accounts are used.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

SURFACES = (
    ("home", "", "#today-view", "#today-capture-input"),
    ("aide", "aide", 'body[data-space="aide"] .main', "#composer-ta"),
    ("andromeda", "andromeda", "#andromeda-view", "#andromeda-query"),
    ("plan", "plan", "#plan-view", ".specialist-group-capture input"),
    ("inbox", "inbox", "#inbox-view", "[data-group-overview] button:visible"),
    ("docs", "docs", "#wiki-view", "#wiki-empty-new"),
    ("files", "files", "#files-view", "#files-search"),
    ("library", "library", "#library-view", "[data-group-overview] button:visible"),
    ("health", "health", "#health-group-view", "[data-group-overview] button:visible"),
    ("finance", "finance", "#finance-view", '#finance-tabs [data-group-section="money"]'),
    ("vault", "passwords", "#vault-view", "#vault-pw-input"),
    ("server", "server", "#system-view", ".app-cog"),
    ("settings", "", "#settings-modal", "#settings-modal-close"),
)


def assert_surface(page, root, primary) -> dict:
    expect(root).to_be_visible()
    expect(primary).to_be_visible()
    expect(primary).to_be_enabled()
    # Playwright's trial click checks scrolling, hit testing and overlay interception.
    # It deliberately does not activate destructive/install/network controls.
    primary.click(trial=True)
    primary.focus()
    expect(primary).to_be_focused()
    text = root.inner_text().strip()
    assert text, "visible app root has no content"
    metrics = page.evaluate("""() => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      nativeChoices: [...document.querySelectorAll('select,input[type="checkbox"],input[type="radio"]')]
        .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
        .map(el => el.id || el.outerHTML.slice(0, 160)),
    })""")
    assert metrics["scrollWidth"] <= metrics["width"], metrics
    assert not metrics["nativeChoices"], metrics
    bounds = primary.bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= metrics["width"] + 1, (
        bounds
    )
    assert (
        bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= page.viewport_size["height"] + 1
    ), bounds
    return {
        "layout": metrics,
        "primary": {"selector": str(primary), "bounds": bounds},
        "visible_text": text[:4000],
    }


def run(device: str, theme: str) -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    require_server_ownership(base, run_id)
    files = data / "files"
    files.mkdir(exist_ok=True)
    (files / "surface-proof.txt").write_text("Synthetic surface fixture.\n", encoding="utf-8")
    (files / "project notes with a longer name.txt").write_text(
        "A second visible row.\n", encoding="utf-8"
    )
    rows = []
    events = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 390 if device == "phone" else 1440, "height": 900},
            is_mobile=device == "phone",
            has_touch=device == "phone",
            locale="en-US",
            timezone_id="UTC",
            reduced_motion="reduce",
            service_workers="block",
        )
        for path, payload in (
            ("/api/setup/dismiss", {}),
            (
                "/api/tasks",
                {"title": "surface proof task", "due_date": datetime.now(UTC).date().isoformat()},
            ),
            (
                "/api/vault-md/file",
                {
                    "path": "surface-proof.md",
                    "content": "# Surface proof\n\nA synthetic document for browser verification.\n\nLonger text and 中文 stay readable.\n",
                },
            ),
        ):
            response = context.request.post(base + path, data=payload)
            assert response.ok, (path, response.status, response.text())
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(12_000)
        page.on(
            "console",
            lambda message: events.append(
                {"kind": "console", "type": message.type, "text": message.text, "url": page.url}
            ),
        )
        page.on(
            "pageerror",
            lambda error: events.append({"kind": "pageerror", "text": str(error), "url": page.url}),
        )
        page.on(
            "requestfailed",
            lambda request: events.append(
                {"kind": "requestfailed", "url": request.url, "failure": request.failure}
            ),
        )
        page.on(
            "response",
            lambda response: (
                events.append(
                    {"kind": "http_error", "url": response.url, "status": response.status}
                )
                if response.status >= 400
                else None
            ),
        )
        try:
            page.goto(base, wait_until="networkidle")
            page.locator("#today-settings").click()
            page.locator('.s-nav-item[data-pane="themes"]').click()
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/appearance") and response.request.method == "PUT"
                )
            ) as appearance:
                page.locator(f'[data-theme-mode="{theme}"]').click()
            assert appearance.value.ok, appearance.value.text()
            page.locator("#settings-modal-close").click()
            context.tracing.stop_chunk(path=str(output / "theme-selection.zip"))
            for name, subdomain, root_selector, primary_selector in SURFACES:
                key = f"{name}--{device}--{theme}"
                row = {
                    "id": f"surface.{name}.{device}.{theme}",
                    "surface": name,
                    "status": "failed",
                    "screenshot": f"{key}.png",
                    "trace": f"{key}.zip",
                    "device": device,
                    "theme": theme,
                }
                start = len(events)
                context.tracing.start_chunk(title=f"{name}: {device}, {theme}")
                try:
                    origin = f"http://{subdomain}.localhost:{port}" if subdomain else base
                    response = page.goto(origin + "/", wait_until="networkidle")
                    assert response and response.ok, f"{name} document did not load"
                    if name == "settings":
                        page.locator("#today-settings").click()
                        expect(page.locator(root_selector)).to_be_visible()
                        page.wait_for_load_state("networkidle")
                    root = page.locator(root_selector)
                    expect(root).to_be_visible()
                    if name in {"plan", "inbox", "library", "health", "finance"}:
                        expect(root).to_have_attribute("aria-busy", "false")
                    if theme == "light":
                        expect(page.locator("html")).to_have_attribute("data-theme", "light")
                    else:
                        expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
                    if name == "plan":
                        expect(root).to_contain_text("surface proof task")
                    if name == "docs":
                        expect(
                            page.locator('#wiki-empty-recent [data-file="surface-proof.md"]')
                        ).to_be_visible()
                    if name == "files":
                        expect(
                            page.locator('#files-list [data-path="surface-proof.txt"]')
                        ).to_be_visible()
                    if name == "server":
                        expect(page.locator("#system-body .nf-logo")).to_be_visible()
                    row.update(assert_surface(page, root, root.locator(primary_selector).first))
                    page.screenshot(path=str(output / f"{key}.png"), full_page=True)
                    if name == "docs":
                        page.locator('#wiki-empty-recent [data-file="surface-proof.md"]').click()
                        expect(page.locator("#wiki-preview")).to_contain_text(
                            "A synthetic document"
                        )
                        row["populated_document"] = assert_surface(
                            page, root, page.locator("#wiki-edit-btn")
                        )
                        page.screenshot(path=str(output / f"{key}--document.png"), full_page=True)
                    if name == "settings":
                        page.locator("#settings-modal-close").click()
                        expect(root).to_be_hidden()
                        expect(page.locator("#today-settings")).to_be_focused()
                    else:
                        trigger = page.locator("#app-drawer-btn")
                        trigger.click()
                        expect(page.locator("#app-drawer")).to_be_visible()
                        expect(page.locator("#app-drawer-close")).to_be_focused()
                        expect(page.locator(".app-drawer-item")).to_have_count(12)
                        page.keyboard.press("Escape")
                        expect(page.locator("#app-drawer")).to_be_hidden()
                        expect(trigger).to_be_focused()
                    failures = [
                        event
                        for event in events[start:]
                        if event["kind"] != "console" or event.get("type") == "error"
                    ]
                    assert not failures, failures
                    row["status"] = "passed"
                except Exception as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    page.screenshot(path=str(output / f"{key}--failure.png"), full_page=True)
                finally:
                    row["events"] = events[start:]
                    context.tracing.stop_chunk(path=str(output / f"{key}.zip"))
                    rows.append(row)
                    (output / "surfaces.json").write_text(
                        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
                    )
                    print(f"{key}: {row['status']}", flush=True)
        finally:
            (output / "browser-events.json").write_text(
                json.dumps(events, indent=2) + "\n", encoding="utf-8"
            )
            (output / "browser-environment.json").write_text(
                json.dumps(
                    {
                        "browser": "chromium",
                        "version": browser.version,
                        "device": device,
                        "theme": theme,
                        "viewport": page.viewport_size,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            context.tracing.stop()
            context.close()
            browser.close()
    failed = [row["surface"] for row in rows if row["status"] != "passed"]
    assert not failed, (
        f"surface checks failed: {', '.join(failed)}; see surfaces.json and named traces"
    )
    assert len(rows) == len(SURFACES)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
