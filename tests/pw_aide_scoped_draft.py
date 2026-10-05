"""Scoped composer drafts, recovery and private-mode isolation on owned local data."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]] + [
    (1280, t, True) for t in ["dark", "light"]
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
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
            context.route(
                "**/*",
                lambda request: (
                    request.continue_()
                    if (urlparse(request.request.url).scheme, urlparse(request.request.url).netloc)
                    == ("http", urlparse(base).netloc)
                    else request.abort()
                ),
            )
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)

            def close_compact_sidebar():
                sidebar = page.locator("#aide-sidebar")
                if (
                    page.evaluate("matchMedia('(max-width:700px)').matches")
                    and sidebar.is_visible()
                ):
                    page.keyboard.press("Escape")
                    expect(sidebar).to_be_hidden()

            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "aide.scoped-draft",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                for endpoint in context.request.get(base + "/api/models").json():
                    assert context.request.delete(
                        base + "/api/models/endpoint/" + endpoint["id"]
                    ).ok
                assert context.request.patch(base + "/api/settings", data={"model_roles": {}}).ok
                other = context.request.post(
                    base + "/api/sessions", data={"name": f"other local task {label}"}
                ).json()["id"]
                name = f"owned-scoped-draft-{label}.md"
                assert context.request.post(
                    base + "/api/vault-md/file",
                    data={"path": name, "content": "# checklist\n\nbring the blue cup\n"},
                ).ok
                page.goto(base + "/?view=wiki", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")
                note = page.locator(f'#wiki-tree [data-file="{name}"]')
                if not note.is_visible():
                    page.locator("#wiki-tree-toggle").click()
                note.click()
                page.locator("#wiki-ask-btn").click()
                question = "what do i need to bring?"
                page.locator("#wiki-ask-input").fill(question)
                page.locator("#wiki-ask-go").click()
                field = page.locator("#composer-ta")
                chip = page.locator("#aide-document-scope")
                expect(field).to_have_value(question)
                expect(chip).to_be_visible()
                expect(page.locator("#aide-document-scope-name")).to_contain_text("1 note only")
                selected = page.evaluate("window._pendingDocumentScope")
                assert selected["documents"][0]["path"] == name
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value(question)
                expect(chip).to_be_visible()
                assert page.evaluate("window._pendingDocumentScope") == selected
                page.screenshot(path=str(out / f"{label}-reopened.png"))

                # Empty questions still carry the selected document context.
                for empty_text in ("", "   "):
                    field.fill(empty_text)
                    expect(chip).to_be_visible()
                    stored_empty = page.evaluate(
                        "JSON.parse(localStorage.getItem('aide-draft-v2-new'))"
                    )
                    assert stored_empty == {"text": "", "document_scope": selected}
                    page.reload(wait_until="networkidle")
                    close_compact_sidebar()
                    expect(field).to_have_value("")
                    expect(chip).to_be_visible()
                    assert page.evaluate("window._pendingDocumentScope") == selected
                page.screenshot(path=str(out / f"{label}-empty-reopened.png"))

                def sidebar():
                    if not page.locator("#aide-sidebar").is_visible():
                        page.locator("#sidebar-toggle-btn").click()
                    expect(page.locator("#aide-sidebar")).to_be_visible()

                sidebar()
                page.locator(f'.session-item[data-id="{other}"] .session-open').click()
                expect(page.locator("#aide-conversation-name")).to_have_text(
                    f"other local task {label}"
                )
                if page.evaluate("matchMedia('(max-width:700px)').matches"):
                    expect(page.locator("#aide-sidebar")).to_be_hidden()
                expect(field).to_have_value("")
                expect(chip).to_be_hidden()
                field.fill("ordinary other-task draft")
                sidebar()
                page.locator("#new-chat-btn").click()
                expect(field).to_have_value("")
                expect(chip).to_be_visible()
                assert page.evaluate("window._pendingDocumentScope") == selected
                stored = page.evaluate(
                    "Object.entries(localStorage).filter(([key]) => key.startsWith('aide-draft-'))"
                )
                page.locator("#incognito-btn").click()
                expect(field).to_have_value("")
                expect(chip).to_be_hidden()
                field.fill("private local question that must never persist")
                assert (
                    page.evaluate(
                        "Object.entries(localStorage).filter(([key]) => key.startsWith('aide-draft-'))"
                    )
                    == stored
                )
                page.locator("#incognito-exit").click()
                expect(field).to_have_value("")
                expect(chip).to_be_visible()
                assert page.evaluate("window._pendingDocumentScope") == selected
                field.fill(question)

                # A local response fixture verifies client send/recovery. It does
                # not invoke a provider or certify generated answers.
                endpoint = context.request.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned draft fixture",
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert context.request.patch(
                    base + "/api/models/endpoint/" + endpoint["id"],
                    data={"models": ["draft-fixture"]},
                ).ok
                assert context.request.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": endpoint["id"],
                        "default_model": "draft-fixture",
                        "model_roles": {},
                        "memory_policy": "off",
                    },
                ).ok
                sent = []

                def answer(route):
                    sent.append(route.request.post_data_json)
                    if len(sent) == 1:
                        route.fulfill(
                            status=409, json={"detail": "selected note changed; select it again"}
                        )
                    else:
                        route.fulfill(
                            content_type="text/event-stream",
                            body='data: {"delta":"owned response fixture"}\n\ndata: {"done":true}\n\ndata: [DONE]\n\n',
                        )

                page.route(base + "/api/chat", answer)
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                field.press("Enter")
                expect(page.locator(".error-msg").last).to_contain_text("selected note changed")
                expect(field).to_have_value(question)
                expect(chip).to_be_visible()
                assert sent[0]["context_scope"] == selected
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value(question)
                expect(chip).to_be_visible()
                assert page.evaluate("window._pendingDocumentScope") == selected
                page.screenshot(path=str(out / f"{label}-failed-send-reopened.png"))
                page.locator("#aide-document-scope-remove").press("Enter")
                expect(chip).to_be_hidden()
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value(question)
                expect(chip).to_be_hidden()
                field.press("Enter")
                expect(page.locator(".ai-content").last).to_contain_text("owned response fixture")
                expect(field).to_have_value("")
                assert not sent[-1].get("context_scope")
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value("")
                expect(chip).to_be_hidden()
                # Simulate full browser storage before migrating a legacy draft.
                # Removing consumed records must still succeed without allocation.
                legacy_question = "consume this legacy question once"
                page.evaluate(
                    "text => { const id=location.hash.slice(1); if(!id) throw Error('missing task'); localStorage.removeItem('aide-draft-v2-'+id); localStorage.setItem('aide-draft-'+id,text); }",
                    legacy_question,
                )
                page.add_init_script(
                    "const originalDraftSet = Storage.prototype.setItem; Storage.prototype.setItem = function(key,value) { if(String(key).startsWith('aide-draft-v2-')) throw new DOMException('synthetic draft quota', 'QuotaExceededError'); return originalDraftSet.call(this,key,value); };"
                )
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value(legacy_question)
                field.press("Enter")
                expect(page.locator(".user-bubble").last).to_have_text(legacy_question)
                expect(field).to_have_value("")
                expect(page.locator("#send-btn")).to_be_enabled()
                page.reload(wait_until="networkidle")
                close_compact_sidebar()
                expect(field).to_have_value("")
                expect(chip).to_be_hidden()
                assert not errors, errors
                assert all("409" in message for message in console), console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                row.update(
                    status="passed",
                    source=selected,
                    requests=len(sent),
                    native_zoom=zoom,
                    boundary="actual local draft/session storage; synthetic chat error and success; no provider invocation",
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))
