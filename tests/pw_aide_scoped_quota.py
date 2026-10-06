"""Verify accepted source drafts stay consumed while newer questions remain owned."""

import base64
import json
import os
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def owned_context(pw, browser, width, zoom, label):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        service_workers="block",
        reduced_motion="reduce",
        has_touch=width == 390,
    )
    if not zoom:
        return browser.new_context(**options)
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


def close_sidebar(page):
    if (
        page.evaluate("matchMedia('(max-width:700px)').matches")
        and page.locator("#aide-sidebar").is_visible()
    ):
        page.keyboard.press("Escape")


base = "http://127.0.0.1:" + os.environ["PORT"]
origin = urlsplit(base)
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in [
            (w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")
        ] + [(1440, t, True) for t in ("light", "dark")]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            ctx = owned_context(pw, browser, width, zoom, label)
            external, errors, console, held, sent = [], [], [], [], []

            def boundary(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    return route.abort()
                return route.continue_()

            ctx.route("**/*", boundary)
            ctx.route_web_socket("**/*", lambda ws: (external.append(ws.url), ws.close()))
            page = ctx.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = ctx.request
            row = {
                "profile": label,
                "native_zoom": zoom,
                "status": "failed",
                "boundary": "actual owned composer/draft storage; held synthetic SSE acceptance, no provider invocation",
            }
            rows.append(row)
            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                ep = api.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned quota fixture " + theme,
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert api.patch(
                    base + "/api/models/endpoint/" + ep["id"], data={"models": ["local-only"]}
                ).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": ep["id"],
                        "default_model": "local-only",
                        "model_roles": {},
                        "memory_policy": "off",
                        "intent_suggestions": False,
                    },
                ).ok
                session = api.post(
                    base + "/api/sessions",
                    data={
                        "name": "owned quota acceptance " + theme,
                        "model": "local-only",
                        "endpoint_id": ep["id"],
                        "mode": "agent",
                    },
                ).json()["id"]
                page.goto(base + "/?view=chat#" + session, wait_until="networkidle")
                if zoom:
                    native_zoom(ctx, page, base)
                close_sidebar(page)
                question = "  submitted owned question\n中文  "
                newer = "newer question remains in this tab 草稿"
                scope = {
                    "kind": "vault_document",
                    "path": "owned.md",
                    "expected_hash": "owned-version",
                }
                field = page.locator("#composer-ta")
                field.fill(question)
                page.evaluate("scope=>window._setAideDocumentScope(scope)", scope)
                key = "aide-draft-v2-" + session
                page.wait_for_function(
                    "({key,text})=>JSON.parse(localStorage.getItem(key)).text===text",
                    arg={"key": key, "text": question},
                )

                def hold(route):
                    held.append(route)
                    sent.append(route.request.post_data_json)

                page.route(base + "/api/chat", hold)
                with page.expect_request(base + "/api/chat"):
                    field.press("Enter")
                page.wait_for_timeout(100)
                assert len(held) == 1 and sent[0]["context_scope"] == scope, sent
                page.evaluate(
                    """() => {const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(this===localStorage && String(key).startsWith('aide-draft-v2-'))throw new DOMException('owned synthetic quota','QuotaExceededError');return original.call(this,key,value);};}"""
                )
                field.fill(newer)
                stored_before = page.evaluate("key=>JSON.parse(localStorage.getItem(key))", key)
                assert stored_before == {"text": question, "document_scope": scope}, stored_before
                held.pop().fulfill(
                    content_type="text/event-stream",
                    body='data: {"delta":"owned synthetic accepted reply"}\n\ndata: {"done":true}\n\ndata: [DONE]\n\n',
                )
                expect(page.locator(".ai-content").last).to_contain_text(
                    "owned synthetic accepted reply"
                )
                expect(page.locator("#send-btn")).to_be_enabled()
                expect(field).to_have_value(newer)
                stored_after = page.evaluate("key=>localStorage.getItem(key)", key)
                capture(ctx, page, out / f"{label}-newer-mounted.png", width)
                assert stored_after is None, stored_after
                page.reload(wait_until="networkidle")
                close_sidebar(page)
                expect(field).to_have_value("")
                assert page.evaluate("window._pendingDocumentScope") is None
                capture(ctx, page, out / f"{label}-accepted-revived.png", width)
                assert not external and not errors and not console, (external, errors, console)
                row.update(
                    status="passed",
                    request=sent[0],
                    stored_before=stored_before,
                    stored_after=stored_after,
                    revived=field.input_value(),
                    scope=scope,
                    newer_preserved_before_reload=True,
                    page_errors=errors,
                    console=console,
                    external=external,
                )
                print(
                    theme,
                    "accepted stored draft removed; newer mounted draft preserved under quota",
                    flush=True,
                )
            finally:
                (out / "outcomes.json").write_text(json.dumps(rows, indent=2) + "\n")
                ctx.close()
    finally:
        browser.close()
