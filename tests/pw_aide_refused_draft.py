"""Refused scoped sends retain drafts until acceptance, using owned local fixtures."""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme in [(w, t) for w in (1440, 390) for t in ("dark", "light")]:
            label = f"{width}-{theme}"
            context = browser.new_context(
                viewport={"width": width, "height": 844},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                has_touch=width == 390,
            )
            requests, held, errors, console, blocked = [], [], [], [], []
            state = {"busy": True, "hold": False}

            def reply(route):
                if state["busy"]:
                    return route.fulfill(
                        status=409,
                        json={
                            "code": "turn_in_progress",
                            "detail": "a response is already running in this task; wait or stop it before sending again",
                        },
                    )
                return route.fulfill(
                    content_type="text/event-stream",
                    body=('data: {"delta":"accepted local answer"}\n\ndata: [DONE]\n\n'),
                )

            def guard(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                    blocked.append(route.request.url)
                    return route.abort()
                if (
                    parsed.path == "/api/sessions"
                    and route.request.method == "POST"
                    and state.get("hold_creation")
                ):
                    creations.append((route, route.fetch()))
                    return None
                if parsed.path == "/api/chat" and route.request.method == "POST":
                    requests.append(route.request.post_data_json)
                    if state["hold"]:
                        held.append(route)
                        return None
                    return reply(route)
                return route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.refused-scoped-draft", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                endpoint = api.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned refusal fixture",
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert api.patch(
                    base + "/api/models/endpoint/" + endpoint["id"], data={"models": ["local-only"]}
                ).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": endpoint["id"],
                        "default_model": "local-only",
                        "model_roles": {},
                        "memory_policy": "off",
                        "memory_auto_inject": False,
                        "intent_suggestions": False,
                        "auto_compact": False,
                    },
                ).ok

                def create(name):
                    response = api.post(
                        base + "/api/sessions",
                        data={
                            "name": name,
                            "model": "local-only",
                            "endpoint_id": endpoint["id"],
                            "mode": "chat",
                        },
                    )
                    assert response.ok
                    return response.json()["id"]

                other = create("other local task")
                existing = create("original local task")
                field = page.locator("#composer-ta")
                retry = page.get_by_role("button", name="retry response", exact=True)

                def switch(session):
                    if not page.locator("#aide-sidebar").is_visible():
                        page.locator("#sidebar-toggle-btn").click()
                    page.locator(f'.session-item[data-id="{session}"] .session-open').click()
                    page.wait_for_function("id=>location.hash.slice(1)===id", arg=session)
                    if width == 390:
                        expect(page.locator("#aide-sidebar")).to_be_hidden()

                def draft(question, scope):
                    field.fill(question)
                    page.evaluate("scope=>window._setAideDocumentScope(scope)", scope)

                def check(question, scope):
                    if width == 390 and page.locator("#aide-sidebar").is_visible():
                        page.keyboard.press("Escape")
                        expect(page.locator("#aide-sidebar")).to_be_hidden()
                    expect(field).to_have_value(question)
                    assert page.evaluate("window._pendingDocumentScope") == scope

                scopes = [
                    {
                        "kind": "vault_document",
                        "path": "owned.md",
                        "expected_hash": "local-version",
                    },
                    {
                        "kind": "vault_documents",
                        "documents": [
                            {"path": "first.md", "expected_hash": "first-version"},
                            {"path": "second.md", "expected_hash": "second-version"},
                        ],
                    },
                ]
                for index, scope in enumerate(scopes):
                    page.goto(
                        base + "/?view=chat" + ("#" + existing if index == 0 else ""),
                        wait_until="networkidle",
                    )
                    state.update(busy=True, hold=False)
                    question = f"  keep exact local question {index}\n中文  "
                    draft(question, scope)
                    field.press("Enter")
                    expect(retry).to_be_visible()
                    check(question, scope)
                    original = dict(requests[-1])
                    session = original["session_id"]
                    assert original["context_scope"] == scope
                    assert original["message"] == question.strip()
                    assert not api.get(base + "/api/sessions/" + session + "/history").json()[
                        "messages"
                    ]
                    retry.focus()
                    retry.press("Enter")
                    expect(retry).to_be_visible()
                    assert requests[-1] == original
                    expect(page.locator(".user-bubble")).to_have_count(1)
                    check(question, scope)
                    switch(other)
                    draft("other task's own draft", None)
                    switch(session)
                    check(question, scope)
                    page.reload(wait_until="networkidle")
                    check(question, scope)
                    page.screenshot(path=str(out / f"{label}-{index}-reopened.png"))
                    field.press("Enter")
                    expect(retry).to_be_visible()
                    state["busy"] = False
                    retry.tap() if width == 390 else retry.press("Enter")
                    expect(page.locator(".ai-content").last).to_have_text("accepted local answer")
                    check("", None)
                    expect(page.locator(".user-bubble")).to_have_count(1)
                    assert requests[-1] == original
                    page.reload(wait_until="networkidle")
                    check("", None)
                    if index:
                        # The former new-task copy must not revive the consumed question.
                        page.goto(base + "/?view=chat", wait_until="networkidle")
                        check("", None)
                    switch(other)
                    check("other task's own draft", None)

                # Quota cannot revive a consumed old draft, including a task left during acceptance.
                for inactive in (False, True):
                    target = base + "/?view=chat" + ("#" + existing if inactive else "")
                    owner = existing if inactive else "new"
                    page.goto(target, wait_until="networkidle")
                    page.evaluate(
                        """id => {
                        localStorage.removeItem('aide-draft-v2-'+id);
                        localStorage.setItem('aide-draft-'+id, 'legacy question at quota');
                    }""",
                        owner,
                    )
                    page.reload(wait_until="networkidle")
                    check("legacy question at quota", None)
                    page.evaluate("""() => {
                        const original = Storage.prototype.setItem;
                        Storage.prototype.setItem = function(key,value) {
                            if(key.startsWith('aide-draft-v2-')) throw new DOMException('synthetic full storage', 'QuotaExceededError');
                            return original.call(this,key,value);
                        };
                    }""")
                    draft("legacy question at quota", scopes[0])
                    state.update(busy=True, hold=False)
                    field.press("Enter")
                    expect(retry).to_be_visible()
                    check("legacy question at quota", scopes[0])
                    state.update(busy=False, hold=inactive)
                    retry.press("Enter")
                    if inactive:
                        deadline = time.monotonic() + 5
                        while not held and time.monotonic() < deadline:
                            page.wait_for_timeout(10)
                        page.wait_for_timeout(100)
                        assert len(held) == 1
                        switch(other)
                        reply(held.pop())
                        expect(page.locator("#send-btn")).to_be_enabled()
                        switch(existing)
                    else:
                        expect(page.locator(".ai-content").last).to_have_text(
                            "accepted local answer"
                        )
                    check("", None)
                    page.goto(target, wait_until="networkidle")
                    check("", None)
                # Ordinary sends adopt files and a first scope selected during creation.
                creations = []
                for late_scope in (None, scopes[0]):
                    page.goto(base + "/?view=chat", wait_until="networkidle")
                    check("", None)
                    creations.clear()
                    state.update(busy=False, hold=False, hold_creation=True)
                    field.fill("ordinary pending task")
                    field.press("Enter")
                    deadline = time.monotonic() + 5
                    while not creations and time.monotonic() < deadline:
                        page.wait_for_timeout(10)
                    page.wait_for_timeout(100)
                    assert len(creations) == 1
                    page.locator("#file-input-hidden").set_input_files(
                        {
                            "name": "during-creation.txt",
                            "mimeType": "text/plain",
                            "buffer": b"owned local attachment",
                        }
                    )
                    expect(page.locator(".attach-chip.uploading")).to_have_count(0)
                    expect(page.locator(".attach-chip")).to_contain_text("during-creation.txt")
                    attached = page.locator(".attach-chip").get_attribute("data-id")
                    if late_scope:
                        page.evaluate("scope=>window._setAideDocumentScope(scope)", late_scope)
                    state["hold_creation"] = False
                    creations[0][0].fulfill(response=creations[0][1])
                    expect(page.locator(".ai-content").last).to_have_text("accepted local answer")
                    assert requests[-1]["file_ids"] == [attached]
                    assert requests[-1].get("context_scope") == late_scope
                    check("", None)
                    expect(page.locator(".attach-chip:visible")).to_have_count(0)

                # A newer scope adopted during task creation belongs to the next question.
                page.goto(base + "/?view=chat", wait_until="networkidle")
                creations.clear()
                state.update(busy=False, hold=True, hold_creation=True)
                question = "same text with a newer selection"
                draft(question, scopes[0])
                field.press("Enter")
                deadline = time.monotonic() + 5
                while not creations and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                page.wait_for_timeout(100)
                assert len(creations) == 1
                draft(question, scopes[1])
                state["hold_creation"] = False
                creations[0][0].fulfill(response=creations[0][1])
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                page.wait_for_timeout(100)
                assert len(held) == 1
                created = requests[-1]["session_id"]
                assert requests[-1]["message"] == question
                assert requests[-1]["context_scope"] == scopes[0]
                switch(other)
                reply(held.pop())
                expect(page.locator("#send-btn")).to_be_enabled()
                check("other task's own draft", None)
                switch(created)
                check(question, scopes[1])
                page.reload(wait_until="networkidle")
                check(question, scopes[1])
                page.screenshot(path=str(out / f"{label}-newer-scope.png"))

                # Programmatic sends consume their scope without consuming unsubmitted text.
                for unsent in ("", "   ", "another unsubmitted question"):
                    for inactive in (False, True):
                        switch(existing)
                        state.update(busy=False, hold=True)
                        draft(unsent, scopes[0])
                        page.evaluate("""() => {
                            void import('/static/js/chat.js').then(module => module.sendMessage('programmatic scoped question'));
                        }""")
                        deadline = time.monotonic() + 5
                        while not held and time.monotonic() < deadline:
                            page.wait_for_timeout(10)
                        page.wait_for_timeout(100)
                        assert len(held) == 1
                        assert requests[-1]["message"] == "programmatic scoped question"
                        assert requests[-1]["context_scope"] == scopes[0]
                        if inactive:
                            switch(other)
                        reply(held.pop())
                        expect(page.locator("#send-btn")).to_be_enabled()
                        if inactive:
                            switch(existing)
                        check(unsent, None)
                        page.reload(wait_until="networkidle")
                        check(unsent if unsent.strip() else "", None)

                # The first accepted retry still owns interruption recovery.
                for interruption in ("stop", "transport"):
                    switch(existing)
                    state.update(busy=True, hold=False)
                    interrupted = "keep this interrupted retry " + interruption
                    draft(interrupted, scopes[0])
                    field.press("Enter")
                    expect(retry).to_be_visible()
                    page.evaluate("""() => {
                        const original = window.fetch;
                        window.fetch = (url, options) => {
                            if (url !== '/api/chat') return original(url, options);
                            return Promise.resolve(new Response(new ReadableStream({
                                start(controller) {
                                    options.signal.addEventListener('abort', () => controller.error(new DOMException('stopped', 'AbortError')));
                                    window.failAcceptedStream = () => controller.error(new TypeError('synthetic interrupted stream'));
                                },
                            }), {headers:{'content-type':'text/event-stream'}}));
                        };
                    }""")
                    retry.press("Enter")
                    check("", None)
                    expect(page.locator("#send-btn")).to_be_disabled()
                    if interruption == "stop":
                        page.locator("#stop-btn").click()
                    else:
                        page.evaluate("window.failAcceptedStream()")
                    expect(page.locator("#send-btn")).to_be_enabled()
                    check(interrupted, scopes[0])
                    expect(retry).to_have_count(0)
                    page.reload(wait_until="networkidle")
                    check(interrupted, scopes[0])

                # Acceptance while another task is visible consumes only the originating draft.
                switch(existing)
                state.update(busy=False, hold=True)
                draft("accepted after switching", scopes[0])
                field.press("Enter")
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                page.wait_for_timeout(100)
                assert len(held) == 1
                switch(other)
                field.focus()
                reply(held.pop())
                expect(page.locator("#send-btn")).to_be_enabled()
                expect(field).to_be_focused()
                check("other task's own draft", None)
                switch(existing)
                check("", None)
                page.reload(wait_until="networkidle")
                check("", None)

                # Edits made before a refused request returns remain the current draft.
                state.update(busy=True, hold=True)
                draft("older pending question", scopes[0])
                field.press("Enter")
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                page.wait_for_timeout(100)
                assert len(held) == 1
                draft("newer exact question", scopes[1])
                field.focus()
                reply(held.pop())
                expect(retry).to_be_visible()
                check("newer exact question", scopes[1])
                expect(field).to_be_focused()
                state.update(busy=False, hold=False)
                retry.press("Enter")
                expect(page.locator(".ai-content").last).to_have_text("accepted local answer")
                check("newer exact question", scopes[1])
                page.reload(wait_until="networkidle")
                check("newer exact question", scopes[1])

                # Public acceptance after entering private mode consumes only the public record.
                state.update(busy=False, hold=True)
                draft("public request before privacy switch", scopes[0])
                field.press("Enter")
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(10)
                page.wait_for_timeout(100)
                assert len(held) == 1
                page.locator("#incognito-btn").click()
                expect(page.locator("#incognito-exit")).to_be_visible()
                draft("new private draft", scopes[1])
                field.focus()
                reply(held.pop())
                expect(page.locator("#send-btn")).to_be_enabled()
                check("new private draft", scopes[1])
                expect(field).to_be_focused()
                page.locator("#incognito-exit").click()
                switch(existing)
                check("", None)
                state["hold"] = False

                # Private refusal retains this tab's draft without writing browser drafts.
                stored = page.evaluate(
                    "Object.entries(localStorage).filter(([k])=>k.startsWith('aide-draft-')).sort()"
                )
                page.locator("#incognito-btn").click()
                state["busy"] = True
                draft("private refused question", scopes[0])
                field.press("Enter")
                expect(retry).to_be_visible()
                check("private refused question", scopes[0])
                assert (
                    page.evaluate(
                        "Object.entries(localStorage).filter(([k])=>k.startsWith('aide-draft-')).sort()"
                    )
                    == stored
                )
                state["busy"] = False
                retry.press("Enter")
                expect(page.locator(".ai-content").last).to_have_text("accepted local answer")
                check("", None)
                assert (
                    page.evaluate(
                        "Object.entries(localStorage).filter(([k])=>k.startsWith('aide-draft-')).sort()"
                    )
                    == stored
                )
                page.screenshot(path=str(out / f"{label}-private-recovered.png"))
                assert not errors and not blocked, (errors, blocked)
                assert all("409" in message for message in console), console
                row.update(
                    status="passed",
                    requests=len(requests),
                    boundary="actual local drafts and task history; synthetic refused/accepted HTTP responses, no provider",
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                try:
                    page.screenshot(path=str(out / f"{label}-final.png"))
                except Exception as capture_error:
                    row.update(status="failed", capture_error=str(capture_error))
                row.update(page_errors=errors, console_errors=console, blocked_external=blocked)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
