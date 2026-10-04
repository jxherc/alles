"""Verify streamed-response completion and safe uncertainty feedback on owned local data."""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in [1440, 390, 320] for t in ["light", "dark"]
        ] + [(1440, t, True) for t in ["light", "dark"]]:
            options = dict(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / f"zoom-{theme}"
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
            external = []
            errors = []
            console = []
            mode = "partial"
            held = []
            requests = []

            def route(r):
                url = urlparse(r.request.url)
                if url.netloc != urlparse(base).netloc:
                    external.append(r.request.url)
                    return r.abort()
                if url.path == "/api/chat" and r.request.method == "POST":
                    requests.append(r.request.post_data_json)
                    if mode == "http_error":
                        return r.fulfill(status=503, json={"detail": "owned request refused"})
                    chunks = (
                        []
                        if mode == "empty"
                        else [
                            {
                                "delta": "owned partial answer"
                                if mode in ["partial", "json_done", "saved_no_done", "held_partial"]
                                else "owned completed answer"
                            }
                        ]
                    )
                    if mode == "json_done":
                        chunks.append({"done": True})
                    if mode == "saved_no_done":
                        chunks.append(
                            {
                                "saved_message": {
                                    "id": "owned-reply-id",
                                    "content": "owned saved answer",
                                }
                            }
                        )
                    if mode.startswith("provider_error"):
                        chunks = [
                            {"saved_user": {"id": "owned-question-id"}},
                            {"error": "HTTP 503: owned provider failure"},
                        ]
                    body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
                    if mode in ["complete", "provider_error"]:
                        body += "data: [DONE]\n\n"
                    if mode in ["held_partial", "user_stop"]:
                        held.append((r, body))
                        return None
                    return r.fulfill(content_type="text/event-stream", body=body)
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            ep = api.post(
                base + "/api/models/endpoint",
                data={
                    "name": "owned EOF fixture",
                    "base_url": base + "/synthetic-model",
                    "provider_adapter": "manual",
                },
            ).json()
            assert api.patch(
                base + "/api/models/endpoint/" + ep["id"], data={"models": ["local-eof"]}
            ).ok
            assert api.patch(
                base + "/api/settings",
                data={
                    "default_endpoint_id": ep["id"],
                    "default_model": "local-eof",
                    "model_roles": {},
                    "memory_policy": "off",
                    "memory_auto_inject": False,
                    "intent_suggestions": False,
                    "auto_compact": False,
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
                        "async base=>{const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",
                        base,
                    )
                    == 2
                )
                page.wait_for_function(
                    "innerWidth===720 && innerHeight===450 && devicePixelRatio===2"
                )
            for private_mode in [False, True]:
                if private_mode:
                    page.locator("#incognito-btn").click()
                    expect(page.locator("#incognito-bar")).to_be_visible()
                for mode in [
                    "partial",
                    "empty",
                    "json_done",
                    "saved_no_done",
                    "complete",
                    "provider_error",
                    "provider_error_no_done",
                    "http_error",
                    "held_partial",
                    "user_stop",
                ]:
                    count = page.locator(".ai-body.done").count()
                    sent = len(requests)
                    page.locator("#composer-ta").fill("owned " + mode + " test")
                    page.locator("#send-btn").click()
                    if mode in ["held_partial", "user_stop"]:
                        expect(page.locator("#send-btn")).to_be_disabled()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert len(held) == 1
                        page.locator("#composer-ta").fill("newer exact draft 中文")
                        if mode == "held_partial":
                            pending, body = held.pop()
                            pending.fulfill(content_type="text/event-stream", body=body)
                        else:
                            page.keyboard.press("Escape")
                    expect(page.locator(".ai-body.done")).to_have_count(count + 1)
                    assert (
                        len(requests) == sent + 1
                        and bool(requests[-1]["incognito"]) == private_mode
                    )
                    if mode in ["held_partial", "user_stop"]:
                        expect(page.locator("#composer-ta")).to_have_value("newer exact draft 中文")
                    if mode == "user_stop":
                        held.pop()[0].abort()
                    body = page.locator(".ai-body").last
                    row = {
                        "width": width,
                        "theme": theme,
                        "zoom": zoom,
                        "mode": mode,
                        "private": private_mode,
                        "text": body.inner_text(),
                        "notices": body.locator(".aide-interruption").count(),
                        "retry": body.locator(".aide-retry-response").count(),
                        "error_count": body.locator(".error-msg").count(),
                        "notice_roles": body.locator(".aide-interruption").evaluate_all(
                            "els=>els.map(e=>e.getAttribute('role'))"
                        ),
                    }
                    rows.append(row)
                    (out / "observations.json").write_text(json.dumps(rows, indent=2))
                    shot = context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (out / f"{width}-{theme}-{zoom}-{private_mode}-{mode}.png").write_bytes(
                        base64.b64decode(shot["data"])
                    )
            assert not external and not errors, (external, errors)
            assert (
                console
                == [
                    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
                ]
                * 2
            ), console
            with (out / "console.jsonl").open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "width": width,
                            "theme": theme,
                            "console": console,
                            "expected": "two deliberately refused HTTP requests",
                        }
                    )
                    + "\n"
                )
            context.close()
    finally:
        browser.close()
(out / "observations.json").write_text(json.dumps(rows, indent=2))
unknown = {"partial", "empty", "json_done", "saved_no_done", "held_partial"}
notified = unknown | {"user_stop"}
assert all(r["notices"] == (1 if r["mode"] in notified else 0) for r in rows), rows
assert all(r["notice_roles"] == (["status"] if r["mode"] in notified else []) for r in rows), rows
assert all("completion was confirmed" in r["text"] for r in rows if r["mode"] in unknown), rows
assert all(r["retry"] == (1 if r["mode"] == "provider_error" else 0) for r in rows), rows
assert all(
    r["error_count"]
    == (1 if r["mode"].startswith("provider_error") or r["mode"] == "http_error" else 0)
    for r in rows
), rows
assert all(
    "owned partial answer" in r["text"] for r in rows if r["mode"] in ["partial", "json_done"]
), rows
assert all("owned saved answer" in r["text"] for r in rows if r["mode"] == "saved_no_done"), rows
assert all(
    "response interrupted" in r["text"] and "completion was confirmed" not in r["text"]
    for r in rows
    if r["mode"] == "user_stop"
), rows

scenarios = []
for width, theme, zoom in sorted({(r["width"], r["theme"], r["zoom"]) for r in rows}):
    cases = [r for r in rows if (r["width"], r["theme"], r["zoom"]) == (width, theme, zoom)]
    scenarios.append(
        {
            "scenario_id": "aide.stream-completion",
            "profile": f"{width}-{theme}" + ("-native200" if zoom else ""),
            "status": "passed",
            "cases": len(cases),
            "checks": "normal/private, partial/empty/JSONdone/savedreply EOF without app completion, completed control, provider failure with/without completion, HTTP refusal, explicitstop,newer draft, one request per dispatch, native200/fullCDP",
        }
    )
(out / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
