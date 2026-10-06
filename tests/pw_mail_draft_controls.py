"""Quiet, named draft deletion with keyboard recovery on owned local records."""

import base64
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, t, False) for w in (1440, 820, 390, 320) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with (
        tempfile.TemporaryDirectory(
            prefix="pw_mail_draft_controls-", dir=os.environ["ALLES_DATA"]
        ) as profiles_root,
        sync_playwright() as pw,
    ):
        fixture_api = pw.request.new_context()
        account = seed_mail(fixture_api, base)
        fixture_api.dispose()
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in profiles:
                label = f"{width}-{theme}" + ("-native200" if zoom else "")
                options = dict(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                    accept_downloads=True,
                )
                if zoom:
                    profile = Path(profiles_root) / label
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
                    "scenario_id": "inbox.draft-delete-control",
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
                    for old in api.get(base + "/api/mail/drafts").json():
                        assert api.delete(base + "/api/mail/drafts/" + old["id"]).ok
                    subject = f"Weekend shopping {label}"
                    draft = api.post(
                        base + "/api/mail/drafts",
                        data={
                            "account_id": account["id"],
                            "subject": subject,
                            "body": "remember tea",
                            "to": "recipient@example.invalid",
                        },
                    ).json()
                    other = api.post(
                        base + "/api/mail/drafts",
                        data={
                            "account_id": account["id"],
                            "subject": "Trip checklist",
                            "body": "bring a notebook",
                        },
                    ).json()
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.wait_for_load_state("networkidle")
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
                    page.get_by_role("button", name="drafts", exact=True).click()
                    button = page.get_by_role("button", name="delete draft: " + subject, exact=True)
                    expect(button).to_be_visible()
                    geometry = button.evaluate(
                        """el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {width:r.width,height:r.height,background:s.backgroundColor,border:s.borderTopWidth}}"""
                    )
                    assert geometry["width"] >= 44 and geometry["height"] >= 44, geometry
                    assert (
                        geometry["background"] in ("rgba(0, 0, 0, 0)", "transparent")
                        and geometry["border"] == "0px"
                    ), geometry
                    capture("resting")
                    button.focus()
                    page.keyboard.press("Tab")
                    page.keyboard.press("Shift+Tab")
                    expect(button).to_be_focused()
                    assert button.evaluate(
                        "el=>el.matches(':focus-visible') && getComputedStyle(el).outlineStyle !== 'none'"
                    )
                    capture("focus")
                    endpoint = base + "/api/mail/drafts/" + draft["id"] + "**"

                    def rejected(route):
                        if route.request.method == "DELETE":
                            return route.fulfill(
                                status=503, json={"detail": "synthetic delete failure"}
                            )
                        return route.continue_()

                    page.route(endpoint, rejected)
                    button.press("Enter")
                    expect(
                        page.get_by_text("synthetic delete failure", exact=True).last
                    ).to_be_visible()
                    expect(button).to_be_enabled()
                    expect(button).to_be_focused()
                    current = api.get(base + "/api/mail/drafts").json()
                    assert {d["id"] for d in current} == {draft["id"], other["id"]}
                    assert (
                        next(d for d in current if d["id"] == draft["id"])["body"] == "remember tea"
                    )
                    capture("failure")
                    page.unroute(endpoint, rejected)
                    button.press("Enter")
                    expect(button).to_have_count(0)
                    remaining = page.locator(
                        '.mail-draft-row[data-id="' + other["id"] + '"] .mail-open'
                    )
                    expect(remaining).to_be_focused()
                    assert [d["id"] for d in api.get(base + "/api/mail/drafts").json()] == [
                        other["id"]
                    ]
                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.get_by_role("button", name="drafts", exact=True).click()
                    expect(button).to_have_count(0)
                    second = page.get_by_role(
                        "button", name="delete draft: Trip checklist", exact=True
                    )
                    expect(second).to_be_visible()
                    capture("remaining")
                    second.press("Enter")
                    expect(page.get_by_text("no drafts", exact=True)).to_be_visible()
                    expect(page.locator("#mail-compose-btn")).to_be_focused()
                    assert api.get(base + "/api/mail/drafts").json() == []
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    unexpected = [message for message in console if "503" not in message]
                    assert not external and not errors and not unexpected, (
                        external,
                        errors,
                        unexpected,
                    )
                    row.update(
                        status="passed",
                        geometry=geometry,
                        checks="exact subject name, quiet resting icon,44px target, keyboard visible focus, failed delete retains bytes and focus, retry deletes exact draft, next draft/compose focus, reload persistence, console and overflow",
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
