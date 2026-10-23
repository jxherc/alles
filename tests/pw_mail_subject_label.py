"""Verify a persistent subject label and exact local draft save/reload; never send mail."""

import base64
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from pw_inbox_workflows import seed_mail  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def owned_context(pw, browser, width, zoom, label, profiles_root):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        service_workers="block",
        reduced_motion="reduce",
        has_touch=width == 390,
    )
    if not zoom:
        return browser.new_context(**options)
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
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
        profile / "browser",
        channel="chromium",
        headless=True,
        args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"],
        **options,
    )


def native_zoom(ctx, page, base):
    worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    assert (
        worker.evaluate(
            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
            base,
        )
        == 2
    )
    page.wait_for_function("innerWidth===720 && innerHeight===450 && devicePixelRatio===2")


def capture(ctx, page, path, width):
    png = base64.b64decode(
        ctx.new_cdp_session(page).send(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )["data"]
    )
    assert struct.unpack(">II", png[16:24]) == (width, 844 if width == 390 else 900)
    Path(path).write_bytes(png)


base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with (
    tempfile.TemporaryDirectory(
        prefix="pw_mail_subject_label-", dir=os.environ["ALLES_DATA"]
    ) as profiles_root,
    sync_playwright() as pw,
):
    fixture = pw.request.new_context()
    account = seed_mail(fixture, base)
    fixture.dispose()
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            ctx = owned_context(pw, browser, width, zoom, label, profiles_root)
            errors = []
            console = []
            external = []
            sends = []

            def boundary(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    return route.abort()
                if (
                    u.path in {"/api/mail/send", "/api/mail/outbox"}
                    or u.path.startswith(
                        ("/api/mail/send/", "/api/mail/send-undoable/", "/api/mail/schedule/")
                    )
                ) and route.request.method == "POST":
                    sends.append(route.request.url)
                    return route.abort()
                return route.continue_()

            ctx.route("**/*", boundary)
            ctx.route_web_socket("**/*", lambda ws: ws.close())
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            row = {"profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = ctx.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                assert api.patch(
                    base + "/api/settings", data={"language": "en", "timezone": "UTC"}
                ).ok
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.get_by_role("button", name="compose", exact=True).click()
                if zoom:
                    native_zoom(ctx, page, base)
                subject = page.get_by_role("textbox", name="subject", exact=True)
                visible_label = page.locator('label[for="mc-subj"]')
                expect(visible_label).to_be_visible()
                expect(subject).to_have_value("")
                exact = "owned shopping subject — café 中文 " + label
                subject.fill(exact)
                expect(visible_label).to_be_visible()
                visible_label.click()
                expect(subject).to_be_focused()
                page.locator("#mc-html").fill("owned exact unsent draft — café 中文")
                capture(ctx, page, out / f"{label}-filled-label.png", width)
                with page.expect_response(
                    lambda r: r.url == base + "/api/mail/drafts" and r.request.method == "POST"
                ) as saved:
                    page.locator("#mc-save").press("Enter")
                assert saved.value.ok, saved.value.text()
                data = saved.value.json()
                assert data["subject"] == exact and data["account_id"] == account["id"]
                expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                expect(subject).to_have_value(exact)
                page.reload(wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.get_by_role("button", name="drafts", exact=True).click()
                page.get_by_role("button", name=exact, exact=True).click()
                expect(subject).to_have_value(exact)
                expect(visible_label).to_be_visible()
                expect(page.locator("#mc-html")).to_contain_text(
                    "owned exact unsent draft — café 中文"
                )
                expect(subject).to_be_focused()
                current = next(
                    d for d in api.get(base + "/api/mail/drafts").json() if d["id"] == data["id"]
                )
                assert current["subject"] == exact and current["body"] == data["body"]
                capture(ctx, page, out / f"{label}-saved-reopened-label.png", width)
                assert not errors and not console and not external and not sends, (
                    errors,
                    console,
                    external,
                    sends,
                )
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                row.update(
                    status="verified",
                    saved=current,
                    page_errors=errors,
                    console=console,
                    external=external,
                    send_attempts=sends,
                )
                print(label, "exact unsent draft label/save/reopen verified", flush=True)
            finally:
                (out / "outcomes.json").write_text(json.dumps(rows, indent=2) + "\n")
                ctx.close()
    finally:
        browser.close()
