"""Searchable effort, permission and memory help in every built-in locale.

Run from the project root against a marker-owned browser-gate server. Native zoom
uses the same Chromium extension technique as pw_task_help.py. Checks use the real shipped application assets.
"""

import base64
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

LANGUAGES = ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")
PROFILES = [(width, theme, False) for width in (1440, 820, 390) for theme in ("light", "dark")]
PROFILES += [(1440, theme, True) for theme in ("light", "dark")]
PROFILES = [
    (width, theme, zoom, language) for width, theme, zoom in PROFILES for language in LANGUAGES
]


def fits(locator):
    value = locator.evaluate("""e => {
      const r=e.getBoundingClientRect();
      return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,
        viewport:innerWidth,viewportHeight:innerHeight,overflow:e.scrollWidth-e.clientWidth};
    }""")
    assert value["left"] >= 0 and value["right"] <= value["viewport"] + 1, value
    assert value["top"] >= 0 and value["bottom"] <= value["viewportHeight"] + 1, value
    assert value["overflow"] <= 1, value
    return value


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (data / ".alles-test-owner").read_text() == run_id
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom, language in PROFILES:
                label = f"{width}-{theme}" + ("-native200" if zoom else "") + "-" + language
                row = {
                    "profile": label,
                    "language": language,
                    "status": "failed",
                    "browser_child_pid": os.getpid(),
                }
                records.append(row)
                options = dict(
                    viewport={"width": width, "height": 844 if width == 390 else 900},
                    timezone_id="UTC",
                    service_workers="block",
                    accept_downloads=True,
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                    has_touch=width <= 390,
                )
                if zoom:
                    profile = data / ("context-help-" + label)
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
                events = {
                    "external": [],
                    "websockets_denied": [],
                    "page_errors": [],
                    "console_errors": [],
                    "http_errors": [],
                    "failed_requests": [],
                }

                def route(request):
                    parsed = urlsplit(request.request.url)
                    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                        events["external"].append(request.request.url)
                        return request.abort()
                    return request.continue_()

                def deny_websocket(ws):
                    events["websockets_denied"].append(ws.url)
                    ws.close()

                context.route("**/*", route)
                context.route_web_socket("**/*", deny_websocket)
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
                page.on(
                    "console",
                    lambda msg: (
                        events["console_errors"].append(msg.text) if msg.type == "error" else None
                    ),
                )
                page.on(
                    "response",
                    lambda res: (
                        events["http_errors"].append({"url": res.url, "status": res.status})
                        if res.status >= 400
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda req: events["failed_requests"].append(
                        {"url": req.url, "failure": req.failure}
                    ),
                )

                def capture(name):
                    session = context.new_cdp_session(page)
                    try:
                        shot = session.send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )
                        png = base64.b64decode(shot["data"])
                        assert struct.unpack(">II", png[16:24]) == (
                            width,
                            844 if width == 390 else 900,
                        )
                        (out / f"{label}-{name}.png").write_bytes(png)
                    finally:
                        session.detach()

                def api(method, path, payload=None):
                    assert path.startswith("/api/") and not path.startswith("//")
                    response = context.request.fetch(
                        base + path, method=method, data=payload, max_redirects=0
                    )
                    assert response.ok, (path, response.status)
                    return response

                try:
                    api("POST", "/api/setup/dismiss")
                    api(
                        "PATCH",
                        "/api/settings",
                        {
                            "language": language,
                            "region": "US",
                            "insights_enabled": False,
                            "user_model_distill": False,
                        },
                    )
                    api("PUT", "/api/appearance", from_legacy(theme, None))
                    page.goto(base + "/?view=chat", wait_until="networkidle")
                    expect(page.locator("#setup-wizard")).to_be_hidden()
                    if zoom:
                        row["before_zoom"] = page.evaluate(
                            "({width:innerWidth,dpr:devicePixelRatio})"
                        )
                        worker = (
                            context.service_workers[0]
                            if context.service_workers
                            else context.wait_for_event("serviceworker")
                        )
                        row["native_zoom"] = worker.evaluate(
                            """async base => {
                          const tab=(await chrome.tabs.query({})).find(t=>{try{return new URL(t.url).origin===base}catch{return false}});
                          await chrome.tabs.setZoom(tab.id,2); return chrome.tabs.getZoom(tab.id);
                        }""",
                            base,
                        )
                        assert row["native_zoom"] == 2
                        page.wait_for_function(
                            "innerWidth===720 && innerHeight===450 && devicePixelRatio===2 && visualViewport.scale===1"
                        )
                    row["viewport"] = page.evaluate(
                        "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,visualScale:visualViewport.scale,cssZoom:getComputedStyle(document.documentElement).zoom})"
                    )
                    messages = json.loads(
                        (ROOT / "static/locales" / (language + ".json")).read_text()
                    )["messages"]
                    draft = "owned unsent question — café 中文 " + language
                    field = page.locator("#composer-ta")
                    field.fill(draft)
                    help_button = page.locator("#aide-help")
                    help_button.press("Enter")
                    dialog = page.locator("#aide-help-dialog")
                    expect(dialog).to_be_visible()
                    expect(dialog.locator("[data-help-close]")).to_be_focused()
                    expect(dialog.locator("[data-help-guide]")).to_have_count(7)
                    search = dialog.locator("#aide-help-search")
                    row["guides"] = {}
                    for guide in ("controls", "memory"):
                        entry = dialog.locator('[data-help-guide="' + guide + '"]')
                        title = messages["aide.help_" + guide + "_title"]
                        body = messages["aide.help_" + guide + "_body"]
                        expect(entry.locator("dt")).to_have_text(title)
                        expect(entry.locator("dd")).to_have_text(body)
                        search.fill(title)
                        expect(entry).to_be_visible()
                        expect(dialog.locator("[data-help-entry]:visible")).to_have_count(1)
                        entry.scroll_into_view_if_needed()
                        row["guides"][guide] = {"title": title, "body": body, "bounds": fits(entry)}
                        assert entry.evaluate("e=>getComputedStyle(e).overflowX") != "hidden"
                        capture(guide + "-filtered")
                    search.fill("owned-no-help-match-92731")
                    expect(dialog.locator("[data-help-entry]:visible")).to_have_count(0)
                    expect(dialog.locator(".aide-help-status")).to_have_text(
                        messages["aide.help_no_matches"]
                    )
                    search.fill("")
                    expect(dialog.locator("[data-help-guide]:visible")).to_have_count(7)
                    for guide in ("model", "notes", "task", "save", "recovery"):
                        entry = dialog.locator('[data-help-guide="' + guide + '"]')
                        expect(entry.locator("dt")).to_have_text(
                            messages["aide.help_" + guide + "_title"]
                        )
                        expect(entry.locator("dd")).to_have_text(
                            messages["aide.help_" + guide + "_body"]
                        )
                    page.keyboard.press("Escape")
                    expect(dialog).to_have_count(0)
                    expect(help_button).to_be_focused()
                    expect(field).to_have_value(draft)
                    help_button.press("Enter")
                    expect(dialog.locator("#aide-help-search")).to_have_value("")
                    dialog.locator("[data-help-close]").press("Enter")
                    expect(help_button).to_be_focused()
                    expect(field).to_have_value(draft)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    row["rendered_language"] = page.locator("html").get_attribute("lang")
                    assert row["rendered_language"] == language + "-US"
                    if language == "en":
                        before = api("GET", "/api/system/policy").json()
                        page.goto(base + "/?view=server", wait_until="networkidle")
                        root = page.locator("#server-workbench-view")
                        root.locator('[data-group-section="policy"]').press("Enter")
                        card = root.locator(".server-workbench-card").filter(
                            has=page.get_by_role("heading", name="server access policy", exact=True)
                        )
                        expect(card).to_contain_text(
                            "owned-only limits control to Alles-managed services"
                        )
                        expect(card).to_contain_text(
                            "allowlisted_host also permits the exact host services you list"
                        )
                        expect(card).to_contain_text("validate the change before saving")
                        expect(card).to_contain_text(
                            "commands, arguments, paths, and globs are rejected"
                        )
                        editor = card.locator("textarea")
                        original = editor.input_value()
                        validate = card.get_by_role(
                            "button", name="validate and show diff", exact=True
                        )
                        validate.press("Enter")
                        expect(card.locator(".server-workbench-status").first).to_have_text(
                            "policy is valid"
                        )
                        expect(validate).to_be_focused()
                        expect(editor).to_have_value(original)
                        assert api("GET", "/api/system/policy").json() == before
                        card.locator("h2").scroll_into_view_if_needed()
                        row["policy"] = {"unchanged": True, "text": card.inner_text()}
                        capture("policy-context")
                    assert (
                        not events["external"]
                        and not events["page_errors"]
                        and not events["console_errors"]
                    ), events
                    assert not events["http_errors"] and not events["failed_requests"], events
                    row["status"] = "passed"
                except Exception:
                    row["failure"] = traceback.format_exc()
                    capture("failed")
                finally:
                    row["events"] = events
                    (out / f"{label}-events.json").write_text(json.dumps(row, indent=2) + "\n")
                    (out / "outcomes.json").write_text(json.dumps(records, indent=2) + "\n")
                    context.close()
                print(
                    json.dumps({"profile": label, "language": language, "status": row["status"]}),
                    flush=True,
                )
        finally:
            browser.close()
    assert all(row["status"] == "passed" for row in records), records
    return records


if __name__ == "__main__":
    run()
