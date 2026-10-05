"""Submitted Aide response retry and draft isolation on an owned local application."""

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
profiles = [(w, t, False) for w in [1440, 390, 320] for t in ["dark", "light"]]
profiles += [(1440, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce" if theme == "dark" else "no-preference",
                "has_touch": width <= 390,
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
            state = {
                "status": 404,
                "hold": True,
                "partial": "",
                "done": True,
                "tool": False,
                "http": 0,
            }
            held, requests, errors, console, external = [], [], [], [], []

            def reply(route):
                if state["http"]:
                    return route.fulfill(
                        status=state["http"],
                        json=(
                            {
                                "detail": "a response is already running in this task; wait or stop it before sending again",
                                "code": "turn_in_progress",
                            }
                            if state.get("busy")
                            else {
                                "detail": "this question can no longer be retried; reopen the task"
                            }
                        ),
                    )
                chunks = []
                if state["tool"]:
                    chunks.append(
                        {
                            "tool_start": {
                                "name": "read_file",
                                "call_id": "local",
                                "args": {"path": "synthetic.txt"},
                            }
                        }
                    )
                    chunks.append(
                        {
                            "tool_result": {
                                "name": "read_file",
                                "call_id": "local",
                                "output": "synthetic output",
                            }
                        }
                    )
                if state["partial"]:
                    chunks.append({"delta": state["partial"]})
                if state["status"]:
                    chunks.append(
                        {
                            "error": f'HTTP {state["status"]}: {{"detail":"synthetic local model failure"}}'
                        }
                    )
                else:
                    chunks.append({"delta": "successful synthetic local answer"})
                chunks.append({"saved_user": {"id": "synthetic-saved-user"}})
                stream = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                route.fulfill(
                    content_type="text/event-stream",
                    body=stream + ("data: [DONE]\n\n" if state["done"] else ""),
                )

            def route(request):
                url = urlparse(request.request.url)
                if (url.scheme, url.netloc) != ("http", urlparse(base).netloc):
                    external.append(request.request.url)
                    return request.abort()
                if url.path.endswith("/history") and "history" in state:
                    response = request.fetch()
                    payload = response.json()
                    payload["messages"] = state["history"]
                    return request.fulfill(response=response, json=payload)
                if url.path == "/api/chat" and request.request.method == "POST":
                    requests.append(request.request.post_data_json)
                    if state["hold"]:
                        held.append(request)
                        return None
                    return reply(request)
                return request.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.response-retry", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                endpoint = api.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned error fixture",
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert api.patch(
                    base + "/api/models/endpoint/" + endpoint["id"],
                    data={"models": ["local-error-fixture"]},
                ).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": endpoint["id"],
                        "default_model": "local-error-fixture",
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
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                field = page.locator("#composer-ta")
                scope = {
                    "kind": "vault_document",
                    "path": "original.md",
                    "expected_hash": "original-version",
                }
                newer_scope = {
                    "kind": "vault_document",
                    "path": "newer.md",
                    "expected_hash": "newer-version",
                }
                page.evaluate("scope=>window._setAideDocumentScope(scope)", scope)
                upload = page.locator("#file-input-hidden")
                upload.set_input_files(
                    {
                        "name": "original.txt",
                        "mimeType": "text/plain",
                        "buffer": b"original attachment",
                    }
                )
                expect(page.locator(".attach-chip").first).to_contain_text("original.txt")
                page.wait_for_function(
                    "document.querySelector('.attach-chip') && !document.querySelector('.attach-chip.uploading')"
                )
                question = "original synthetic local question"
                field.fill(question)
                page.locator("#send-btn").click()
                expect(page.locator("#send-btn")).to_be_disabled()
                page.wait_for_timeout(100)
                assert len(held) == 1
                original = requests[0]
                assert original["context_scope"] == scope
                assert len(original["file_ids"]) == 1
                newer = "newer unsent draft stays exactly here"
                field.fill(newer)
                page.evaluate("scope=>window._setAideDocumentScope(scope)", newer_scope)
                upload.set_input_files(
                    {"name": "newer.txt", "mimeType": "text/plain", "buffer": b"newer attachment"}
                )
                expect(page.locator(".attach-chip").filter(has_text="newer.txt")).to_be_visible()
                page.wait_for_function("!document.querySelector('.attach-chip.uploading')")
                newer_remove = page.get_by_role("button", name="remove newer.txt", exact=True)
                newer_remove.focus()
                reply(held.pop())
                expect(newer_remove).to_be_focused()
                retry = page.get_by_role("button", name="retry response", exact=True)
                expect(retry).to_be_visible()
                expect(field).to_have_value(newer)
                retry.focus()
                expect(retry).to_be_focused()
                assert retry.bounding_box()["height"] >= 44
                assert retry.evaluate(
                    "e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"
                )
                page.screenshot(path=str(out / f"{label}-retry.png"))
                old_button = retry.element_handle()
                retry.tap() if width <= 390 else retry.press("Enter")
                old_button.evaluate("e=>e.click()")
                expect(field).to_be_focused()
                expect(field).to_have_value(newer)
                expect(page.locator("#send-btn")).to_be_disabled()
                page.wait_for_timeout(100)
                assert len(held) == 1 and len(requests) == 2, requests
                assert requests[1] == {**original, "retry_message_id": "synthetic-saved-user"}
                assert page.evaluate("window._pendingDocumentScope") == newer_scope
                expect(page.locator(".attach-chip").first).to_contain_text("newer.txt")
                expect(page.locator(".user-bubble")).to_have_count(1)
                # A second known provider failure remains retryable.
                state["status"] = 503
                reply(held.pop())
                expect(retry).to_be_visible()
                retry.press("Enter")
                page.wait_for_timeout(100)
                assert len(requests) == 3
                assert requests[-1] == requests[-2]
                state["status"] = 0
                reply(held.pop())
                expect(page.locator(".ai-content").last).to_have_text(
                    "successful synthetic local answer"
                )
                expect(retry).to_have_count(0)
                expect(page.locator(".user-bubble")).to_have_count(1)
                expect(field).to_have_value(newer)
                assert page.evaluate("window._pendingDocumentScope") == newer_scope
                expect(page.locator(".attach-chip").first).to_contain_text("newer.txt")
                page.screenshot(path=str(out / f"{label}-recovered.png"))

                state["hold"] = False
                for case, updates in [
                    ("partial", {"partial": "partial answer retained"}),
                    ("tool", {"tool": True}),
                    ("uncertain", {"done": False}),
                ]:
                    state.update(status=503, partial="", tool=False, done=True, http=0)
                    state.update(updates)
                    field.fill("bounded local " + case)
                    bodies = page.locator(".ai-body").count()
                    page.locator("#send-btn").click()
                    expect(page.locator(".ai-body")).to_have_count(bodies + 1)
                    expect(page.locator(".ai-body.done")).to_have_count(bodies + 1)
                    expect(page.locator("#send-btn")).to_be_enabled()
                    expect(page.locator(".error-msg").last).to_contain_text(
                        "temporarily unavailable"
                    )
                    expect(retry).to_have_count(0)
                    if case == "partial":
                        expect(page.locator(".ai-content").last).to_have_text(
                            "partial answer retained"
                        )
                # A later turn retires an earlier retry, even if an old click arrives.
                state.update(status=503, partial="", tool=False, done=True)
                field.fill("old retry")
                page.locator("#send-btn").click()
                expect(retry).to_be_visible()
                old_button = retry.element_handle()
                state["hold"] = True
                field.fill("new request")
                page.locator("#send-btn").click()
                expect(retry).to_have_count(0)
                old_button.evaluate("e=>e.click()")
                page.wait_for_timeout(100)
                assert len(held) == 1
                before = len(requests)
                reply(held.pop())
                expect(retry).to_be_visible()
                assert len(requests) == before
                # Server rejects a now-stale retry without changing the newer composer.
                field.fill(newer)
                page.evaluate("scope=>window._setAideDocumentScope(scope)", newer_scope)
                state.update(hold=False, http=409)
                retry.press("Enter")
                expect(page.locator(".error-msg").last).to_contain_text("reopen the task")
                expect(field).to_have_value(newer)
                assert page.evaluate("window._pendingDocumentScope") == newer_scope
                expect(retry).to_have_count(0)
                # A definite refusal before work started can retry the same request.
                state.update(busy=True, http=409, hold=False)
                field.fill("question refused while another turn runs")
                user_count = page.locator(".user-bubble").count()
                page.locator("#send-btn").click()
                expect(retry).to_be_visible()
                busy_notice = page.locator(".error-msg").last
                expect(busy_notice.get_by_role("status")).to_contain_text(
                    "a response is already running"
                )
                paragraph = busy_notice.get_by_role("status").bounding_box()
                button = retry.bounding_box()
                assert button["y"] >= paragraph["y"] + paragraph["height"], (paragraph, button)
                assert button["height"] >= 44
                retry.focus()
                page.keyboard.press("Tab")
                page.keyboard.press("Shift+Tab")
                expect(retry).to_be_focused()
                page.screenshot(path=str(out / f"{label}-busy-refused.png"))
                busy_request = dict(requests[-1])
                assert "retry_message_id" not in busy_request
                field.fill("newer busy recovery draft")
                busy_scope = {
                    "kind": "vault_document",
                    "path": "busy-next.md",
                    "expected_hash": "next",
                }
                page.evaluate("scope=>window._setAideDocumentScope(scope)", busy_scope)
                bodies = page.locator(".ai-body").count()
                retry.press("Enter")
                expect(page.locator(".ai-body.done")).to_have_count(bodies)
                expect(retry).to_be_visible()
                assert requests[-1] == busy_request
                expect(field).to_have_value("newer busy recovery draft")
                assert page.evaluate("window._pendingDocumentScope") == busy_scope
                state.update(busy=False, http=0, status=0)
                retry.press("Enter")
                expect(page.locator(".ai-content").last).to_have_text(
                    "successful synthetic local answer"
                )
                assert requests[-1] == busy_request
                expect(page.locator(".user-bubble")).to_have_count(user_count + 1)
                expect(field).to_have_value("newer busy recovery draft")
                assert page.evaluate("window._pendingDocumentScope") == busy_scope
                expect(retry).to_have_count(0)
                expect(page.locator(".ai-body").last).to_have_class("ai-body done")
                expect(page.locator("#send-btn")).to_be_enabled()
                page.screenshot(path=str(out / f"{label}-busy-recovered.png"))
                recovery_request = {
                    key: value
                    for key, value in original.items()
                    if key not in {"session_id", "message", "retry_message_id"}
                }
                saved = {
                    "id": "synthetic-restored-user",
                    "role": "user",
                    "content": original["message"],
                    "meta": {
                        "response_recovery": {"status": "failed", "request": recovery_request}
                    },
                }
                state["history"] = [saved]
                page.reload(wait_until="networkidle")
                expect(page.locator(".aide-response-recovery")).to_contain_text(
                    "the model could not answer this question"
                )
                expect(retry).to_be_visible()
                expect(field).to_have_value("newer busy recovery draft")
                page.evaluate("scope=>window._setAideDocumentScope(scope)", busy_scope)
                retry.press("Enter")
                expect(page.locator(".ai-content").last).to_have_text(
                    "successful synthetic local answer"
                )
                assert requests[-1] == {**original, "retry_message_id": saved["id"]}
                expect(page.locator(".user-bubble")).to_have_count(1)
                expect(field).to_have_value("newer busy recovery draft")
                assert page.evaluate("window._pendingDocumentScope") == busy_scope
                # Partial, uncertain and pre-metadata histories explain the outcome without replay.
                for outcome in ("partial", "incomplete", "legacy"):
                    saved["meta"] = (
                        {}
                        if outcome != "incomplete"
                        else {"response_recovery": {"status": "incomplete"}}
                    )
                    state["history"] = [saved]
                    if outcome == "partial":
                        state["history"].append(
                            {
                                "id": "synthetic-partial",
                                "role": "assistant",
                                "content": "partial saved answer",
                                "meta": {"response_recovery": {"status": "failed"}},
                            }
                        )
                    page.reload(wait_until="networkidle")
                    expect(page.locator(".aide-response-recovery")).to_contain_text(
                        "before sending again"
                    )
                    expect(retry).to_have_count(0)
                    if outcome == "partial":
                        expect(page.locator(".ai-content").last).to_have_text(
                            "partial saved answer"
                        )
                page.screenshot(path=str(out / f"{label}-incomplete-reopened.png"))
                assert not errors, errors
                assert not external, external
                unexpected = [x for x in console if "409" not in x]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    requests=len(requests),
                    checks="original request snapshot, repeated failure then success, duplicate click guard, newer draft/attachment/scope, partial/tool/uncertain exclusion, retired old button, stale409 preservation, reopened known failure retry, partial/incomplete/legacy history guidance without replay",
                )
            except Exception as error:
                row.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                )
                page.screenshot(path=str(out / f"{label}-failed.png"))
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    finally:
        browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"
