"""Owned Aide reply -> reviewed task -> exact Plan/source/recovery workflow."""

import json
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

ANSWER = "# send the owned application\n\nkeep **this source detail** and [local note](/?doc=owned.md). 🌱"


def current_model_turn(messages):
    """Ignore retained conversation history; include only this user's tool results."""
    start = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        len(messages),
    )
    return messages[start:]


def close_archive(page):
    close = page.locator("#aide-sidebar-close")
    if close.is_visible():
        close.click()
    expect(page.locator("#nav-backdrop")).not_to_be_visible()


def private_conversation(page):
    close_archive(page)
    page.locator("#aide-more-btn").click()
    page.get_by_role("menuitem", name="private conversation", exact=True).click()
    expect(page.locator("#incognito-bar")).to_be_visible()


def new_task(page):
    close_archive(page)
    # Central Aide hides legacy sidebar navigation. Its documented shortcut
    # still starts an independent task through the real keyboard handler.
    page.keyboard.press("Alt+n")
    expect(page.locator("#messages .ai-wrap")).to_have_count(0)
    expect(page.locator("#composer-ta")).to_be_focused()


def submitted_reply(page, question, submit):
    """Pin the row created by this request, never a live `.last` historical reply."""
    with page.expect_request(
        lambda request: (
            urlparse(request.url).path == "/api/chat"
            and request.method == "POST"
            and request.post_data_json.get("message") == question
        )
    ):
        submit()
    # A failed send may leave the same user bubble before a retry. The latest
    # matching user is resolved once, after its exact request has started.
    bubble = page.locator("#messages").get_by_text(question, exact=True)
    expect(bubble.last).to_be_attached()
    reply = (
        bubble.last.locator("xpath=ancestor::*[contains(@class,'msg-row')][1]")
        .locator("xpath=following-sibling::*[1]")
        .locator(".ai-wrap")
    )
    expect(reply).to_have_count(1)
    token = uuid.uuid4().hex
    reply.evaluate("(element, token) => element.dataset.ownedTurn = token", token)
    return page.locator(f'#messages .ai-wrap[data-owned-turn="{token}"]')


def settled_reply(page, reply):
    expect(reply.locator(".msg-actions")).to_have_count(1)
    expect(page.locator("#send-btn")).to_be_enabled()
    expect(page.locator("#stop-btn")).not_to_be_visible()
    assert reply.get_attribute("data-session-id"), "new reply lacks session identity"


def canonical_reply(page, reply):
    """Match the persisted reply by its immutable message/provenance identity."""
    identity = reply.evaluate("""element => ({
        session: element.dataset.sessionId, source: element.sourceReplyId,
        message: element.closest('.msg-row').dataset.msgId
    })""")
    assert identity.get("source") or identity.get("message"), identity
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        history = api("GET", f"/api/sessions/{identity['session']}/history")["messages"]
        matches = [
            message
            for message in history
            if message["role"] == "assistant"
            and (
                message.get("id") == identity.get("message")
                or identity.get("source")
                and message.get("meta", {}).get("context_provenance", {}).get("reply_id")
                == identity["source"]
            )
        ]
        if matches:
            assert len(matches) == 1, identity
            return matches[0]
        page.wait_for_timeout(20)
    raise AssertionError(f"new reply was not persisted: {identity}")


def persisted_reply(page, message):
    reply = page.locator(f'#messages .msg-row[data-msg-id="{message}"] .ai-wrap')
    expect(reply).to_have_count(1)
    return reply


def reply_action(page, reply, name):
    """Open the actual menu after streaming/focus scrolling has settled."""
    trigger = reply.get_by_role("button", name="more reply actions", exact=True)
    trigger.scroll_into_view_if_needed()
    trigger.focus()
    trigger.evaluate("""element => new Promise((resolve, reject) => {
      const deadline = performance.now() + 3000;
      let previous = '', stable = 0;
      const sample = () => {
        const box = element.getBoundingClientRect();
        const chat = document.getElementById('chat');
        const current = JSON.stringify([box.x, box.y, chat.scrollTop, chat.scrollLeft]);
        stable = current === previous ? stable + 1 : 0;
        previous = current;
        if (stable >= 3) return resolve();
        if (performance.now() > deadline) return reject(new Error('reply scroll did not settle'));
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    })""")
    menu = reply.get_by_role("menu", name="reply actions")
    if not menu.is_visible():
        trigger.press("ArrowDown")
    expect(menu).to_be_visible()
    action = menu.get_by_role("menuitem", name=name, exact=True)
    expect(action).to_be_visible()
    action.focus()
    expect(action).to_be_focused()
    # Its accessible name changes while preparing/saved. Pin this element so
    # subsequent busy-state assertions cannot lose it or select a different action.
    token = action.get_attribute("data-owned-action") or uuid.uuid4().hex
    action.evaluate("(element, token) => element.dataset.ownedAction = token", token)
    return reply.locator(f'[data-owned-action="{token}"]')


class Model(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    holds = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        selected = any(
            "<alles_document_reference>" in str(message.get("content", ""))
            for message in current_model_turn(body.get("messages", []))
        )
        answer = "keep **this source detail** [[source:1:2-2]]" if selected else ANSWER
        if not body.get("stream"):
            payload = json.dumps(
                {"choices": [{"message": {"content": "owned task capture"}}]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in [
            {"choices": [{"delta": {"content": answer}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]:
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.flush()
            if selected and chunk["choices"][0]["delta"].get("content"):
                hold = threading.Event()
                self.holds.append(hold)
                hold.wait(15)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run(context_factory=None, cases=None):
    _require_throwaway_data_root()
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api("POST", "/api/setup/dismiss", {})
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned task fixture",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["task-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint,
                "default_model": "task-fixture",
                "model_roles": {"aide_chat": {"endpoint_id": endpoint, "model": "task-fixture"}},
            },
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 820, 390):
                for case in cases or (
                    "cancel",
                    "accept",
                    "retry",
                    "reload",
                    "private",
                    "history",
                    "cross",
                    "source",
                    "source-fail",
                    "source-pending",
                    "source-busy",
                    "source-stale",
                    "deleted",
                ):
                    context = (
                        context_factory(pw, width)
                        if context_factory
                        else browser.new_context(
                            viewport={"width": width, "height": 900},
                            service_workers="block",
                            reduced_motion="reduce",
                        )
                    )
                    page = context.new_page()
                    page.set_default_timeout(9000)
                    writes = []
                    errors = []
                    console = []
                    forbidden = []
                    held = []
                    source_case = case.startswith("source")
                    expected = ANSWER
                    before = {
                        r["id"] for r in api("GET", "/api/tasks") + api("GET", "/api/tasks/done")
                    }

                    def routes(route):
                        parsed = urlparse(route.request.url)
                        if parsed.port != urlparse(HOME).port or parsed.hostname not in (
                            "127.0.0.1",
                            "aide.localhost",
                            "plan.localhost",
                        ):
                            forbidden.append(route.request.url)
                            route.abort()
                        elif parsed.path == "/api/tasks" and route.request.method == "POST":
                            writes.append(route.request.post_data_json)
                            if case == "source-busy" and len(writes) == 1:
                                held.append(route)
                            elif case in ("retry", "reload") and len(writes) == 1:
                                response = route.fetch()
                                assert response.ok
                                route.fulfill(
                                    status=503, json={"detail": "owned lost acknowledgement"}
                                )
                            else:
                                route.continue_()
                        else:
                            route.continue_()

                    context.route("**/*", routes)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console", lambda m: console.append(m.text) if m.type == "error" else None
                    )
                    record = {
                        "scenario_id": "aide.task." + case,
                        "profile": str(width),
                        "status": "failed",
                    }
                    try:
                        base = (
                            f"http://aide.localhost:{urlparse(HOME).port}"
                            if case in ("cross", "deleted")
                            else HOME
                        )
                        page.goto(base + "/?app=aide", wait_until="networkidle")
                        close_archive(page)
                        if case == "private":
                            private_conversation(page)
                        if case == "deleted":
                            # The primary conversation is deliberately protected.
                            # Exercise missing-source recovery on a deletable Aide task.
                            new_task(page)
                        question = f"owned task {width}-{case}: give me the application task"
                        if source_case:
                            path = f"task-{width}-{case}/source.md"
                            api(
                                "POST",
                                "/api/vault-md/file",
                                {
                                    "path": path,
                                    "content": "# source\nowned source passage\n",
                                },
                            )
                            page.goto(
                                HOME + "/?app=docs&doc=" + quote(path, safe=""),
                                wait_until="networkidle",
                            )
                            expect(page.locator("#wiki-preview")).to_contain_text(
                                "owned source passage"
                            )
                            page.locator("#wiki-ask-btn").click()
                            page.locator("#wiki-ask-input").fill(question)
                            reply = submitted_reply(
                                page, question, page.locator("#wiki-ask-go").click
                            )
                        else:
                            page.locator("#composer-ta").fill(question)
                            reply = submitted_reply(page, question, page.locator("#send-btn").click)
                        expect(reply.locator(".ai-body")).to_contain_text("keep this source detail")
                        if source_case:
                            expect(page.locator("#stop-btn")).to_be_visible()
                            if case != "source":
                                # the page hears its stop wasn't taken, so it lets go at once,
                                # like a closed page: the server keeps the reply as interrupted
                                # and the page never sees it saved, so +plan task has to read the
                                # history (the path these cases break)
                                page.route(
                                    "**/api/chat/stop/**",
                                    lambda route: route.fulfill(
                                        json={"ok": False, "reason": "turn_changed"}
                                    ),
                                )
                            page.locator("#stop-btn").click()
                        settled_reply(page, reply)
                        message = reply.locator("xpath=..").get_attribute("data-msg-id")
                        session = reply.get_attribute("data-session-id")
                        if source_case:
                            canonical = canonical_reply(page, reply)
                            assert canonical["meta"]["interrupted"] is True
                            for hold in Model.holds:
                                hold.set()
                            message = canonical["id"]
                            expected = canonical["content"].strip()
                            assert "[[source:" not in expected and "doc_hash=" in expected
                            assert "> owned source passage" in expected
                            assert quote(path, safe="") in expected, expected
                            close_archive(page)
                        if case == "history":
                            page.reload(wait_until="networkidle")
                            close_archive(page)
                            reply = persisted_reply(page, message)
                        record["reply_identity"] = {
                            "question": question,
                            "session": session,
                            "message": message,
                        }
                        button = reply.locator('button[title="review this reply as a plan task"]')
                        history_reads = []
                        if case == "source":
                            # a confirmed stop reads the stream to its end: the saved reply,
                            # citations and all, is already on the page
                            expect(reply.locator(".ai-body")).to_contain_text(
                                "owned source passage"
                            )
                            page.on(
                                "request",
                                lambda request: (
                                    history_reads.append(request.url)
                                    if urlparse(request.url).path
                                    == f"/api/sessions/{session}/history"
                                    else None
                                ),
                            )
                        if case in ("source-fail", "source-pending"):
                            page.route(
                                f"**/api/sessions/{session}/history",
                                lambda route: (
                                    route.fulfill(
                                        status=503, json={"detail": "owned unavailable history"}
                                    )
                                    if case == "source-fail"
                                    else route.fulfill(json={"messages": []})
                                ),
                                times=1,
                            )
                            reply_action(page, reply, "+plan task").press("Enter")
                            expect(page.locator("#aide-task-recovery")).to_contain_text(
                                "try +plan task again"
                            )
                            expect(page.locator("#capture-title")).to_have_count(0)
                            assert not writes
                        if case in ("source-busy", "source-stale"):
                            page.route(
                                f"**/api/sessions/{session}/history",
                                lambda route: held.append(route),
                                times=1,
                            )
                        button = reply_action(page, reply, "+plan task")
                        button.press("Enter")
                        if case == "source-stale":
                            old_button = button.element_handle()
                            expect(button).to_have_attribute("aria-disabled", "true")
                            new_task(page)
                            if page.locator("#aide-document-scope-remove").is_visible():
                                page.locator("#aide-document-scope-remove").click()
                            record["superseded_reply_identity"] = record["reply_identity"]
                            question = f"another owned task {width}-{case}"
                            page.locator("#composer-ta").fill(question)
                            reply = submitted_reply(page, question, page.locator("#send-btn").click)
                            expect(reply.locator(".ai-body")).to_contain_text(
                                "keep this source detail"
                            )
                            settled_reply(page, reply)
                            message = reply.locator("xpath=..").get_attribute("data-msg-id")
                            session = reply.get_attribute("data-session-id")
                            expected = ANSWER
                            record["reply_identity"] = {
                                "question": question,
                                "session": session,
                                "message": message,
                            }
                            button = reply_action(page, reply, "+plan task")
                            button.press("Enter")
                        if case == "source-busy":
                            expect(button).to_have_attribute("aria-disabled", "true")
                            # Targeted keyboard re-entry on the visible disabled item;
                            # ordinary menu arrow navigation intentionally skips it.
                            reply_action(page, reply, "preparing…").press("Enter")
                            assert len(held) == 1 and not writes
                            page.keyboard.press("Escape")
                            held.pop().continue_()
                        expect(page.locator("#capture-title")).to_be_visible()
                        expect(page.locator("#capture-notes")).to_have_value(expected)
                        assert not writes
                        # +plan task needed nothing more from the server for a confirmed stop
                        assert not history_reads, history_reads
                        title = f"owned reviewed {case} {width}"
                        page.locator("#capture-title").fill(title)
                        if case == "cancel":
                            page.locator("#capture-cancel").click()
                            expect(page.locator("#capture-title")).to_be_hidden()
                            expect(
                                reply.get_by_role("button", name="more reply actions", exact=True)
                            ).to_be_focused()
                            assert not writes
                            assert {
                                r["id"]
                                for r in api("GET", "/api/tasks") + api("GET", "/api/tasks/done")
                            } == before
                        else:
                            if case == "private":
                                expect(page.locator(".capture-review")).to_contain_text(
                                    "outside this private conversation"
                                )
                            page.screenshot(
                                path=str(out / f"{width}-{case}-review.png"), full_page=True
                            )
                            page.locator("#capture-accept").click()
                            if case == "source-busy":
                                expect(page.locator("#capture-accept")).to_be_disabled()
                                page.keyboard.press("Enter")
                                assert len(writes) == 1 and len(held) == 1
                                held.pop().continue_()
                            if case in ("retry", "reload"):
                                expect(page.locator(".capture-status")).to_contain_text(
                                    "will not add a duplicate"
                                )
                                if case == "reload":
                                    page.reload(wait_until="networkidle")
                                    close_archive(page)
                                    page.get_by_role(
                                        "button", name="review pending capture", exact=True
                                    ).click()
                                page.get_by_role(
                                    "button", name="retry confirmation", exact=True
                                ).click()
                                assert len(writes) == 2 and writes[0] == writes[1]
                            expect(page.locator("#capture-open")).to_be_visible()
                            created = [r for r in api("GET", "/api/tasks") if r["id"] not in before]
                            assert len(created) == 1, created
                            saved = created[0]
                            assert saved["title"] == title and saved["notes"] == expected
                            assert (
                                saved["source"]["excerpt"] == expected
                                and saved["source"]["kind"] == "aide"
                            )
                            if case == "private":
                                assert (
                                    saved["source"]["private"]
                                    and not saved["source"]["session_id"]
                                    and not saved["source"]["message_id"]
                                )
                            else:
                                assert (
                                    saved["source"]["session_id"] == session
                                    and saved["source"]["message_id"] == message
                                ), (saved["source"], session, message)
                            if case == "source-stale":
                                page.locator("#capture-cancel").click()
                                assert len(held) == 1
                                held.pop().fulfill(
                                    status=503, json={"detail": "owned late history failure"}
                                )
                                page.wait_for_function(
                                    "button => !button.hasAttribute('aria-disabled')",
                                    arg=old_button,
                                )
                                expect(page.locator("#aide-task-saved")).to_contain_text(
                                    "saved in plan: " + title
                                )
                                page.locator("#aide-task-saved").get_by_role(
                                    "button", name="open in plan", exact=True
                                ).click()
                            elif case == "reload":
                                page.locator("#capture-cancel").click()
                                saved_action = page.locator("#aide-task-saved").get_by_role(
                                    "button", name="open in plan", exact=True
                                )
                                expect(saved_action).to_be_focused()
                                expect(page.locator("[data-capture-recovery]")).to_have_count(0)
                                saved_action.press("Enter")
                            else:
                                page.locator("#capture-open").press("Enter")
                            expect(page.locator("#te-title")).to_have_value(title)
                            expect(page.locator("#te-notes")).to_have_value(expected)
                            plan_url = page.url
                            if case in ("cross", "deleted"):
                                assert urlparse(plan_url).hostname == "plan.localhost"
                            page.reload(wait_until="networkidle")
                            expect(page.locator("#te-title")).to_have_value(title)
                            if case == "private":
                                expect(page.locator("#te-source")).to_have_count(0)
                                expect(page.locator(".task-editor")).to_contain_text(
                                    "private Aide reply"
                                )
                            else:
                                if case == "deleted":
                                    api("DELETE", f"/api/sessions/{session}")
                                page.get_by_role(
                                    "button", name="open original reply", exact=True
                                ).click()
                                if case == "deleted":
                                    expect(page.locator("#toast-container")).to_contain_text(
                                        "original conversation or reply is unavailable"
                                    )
                                else:
                                    target = page.locator(
                                        f'#messages .msg-row[data-msg-id="{message}"]'
                                    )
                                    expect(target).to_be_focused()
                                    expect(target).to_contain_text("keep this source detail")
                                if case in ("cross", "deleted"):
                                    assert urlparse(page.url).hostname == "aide.localhost"
                                assert parse_qs(urlparse(page.url).query)["message"] == [message]
                                page.reload(wait_until="networkidle")
                                if case == "deleted":
                                    expect(page.locator("#toast-container")).to_contain_text(
                                        "original conversation or reply is unavailable"
                                    )
                                    assert urlparse(page.url).fragment == session
                                    page.screenshot(
                                        path=str(out / f"{width}-deleted-source-error.png"),
                                        full_page=True,
                                    )
                                    new_task(page)
                                    assert "message" not in parse_qs(urlparse(page.url).query)
                                    assert not urlparse(page.url).fragment
                                    page.reload(wait_until="networkidle")
                                    expect(page.locator("#toast-container")).not_to_contain_text(
                                        "original conversation or reply is unavailable"
                                    )
                                else:
                                    expect(
                                        page.locator(f'#messages .msg-row[data-msg-id="{message}"]')
                                    ).to_be_focused()
                                page.goto(plan_url, wait_until="networkidle")
                                expect(page.locator("#te-title")).to_have_value(title)
                            page.locator("#te-cancel").click()
                            row = page.locator(f'#tasks-view [data-id="{saved["id"]}"]')
                            row.locator(".task-check").click()
                            expect(row).to_have_count(0)
                            done = next(
                                r for r in api("GET", "/api/tasks/done") if r["id"] == saved["id"]
                            )
                            assert (
                                done["done"]
                                and done["notes"] == expected
                                and done["source"] == saved["source"]
                            )
                            record["saved"] = saved
                        assert not errors and not forbidden, (errors, forbidden)
                        assert not [line for line in console if "status of 503" not in line], (
                            console
                        )
                        record["status"] = "passed"
                    except Exception:
                        record["error"] = traceback.format_exc()
                    finally:
                        for hold in Model.holds:
                            hold.set()
                        for route in held:
                            route.abort()
                        record.update(
                            writes=writes, page_errors=errors, console=console, forbidden=forbidden
                        )
                        record["rendered"] = page.evaluate(
                            "({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth})"
                        )
                        if record["rendered"]["overflow"]:
                            record["status"] = "failed"
                            record["error"] = record.get("error", "") + "\npage overflow"
                        page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                        rows.append(record)
                        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                        context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(
        json.dumps(
            [
                {
                    "case": r["scenario_id"],
                    "profile": r["profile"],
                    "status": r["status"],
                    "error": r.get("error", "")[-400:],
                }
                for r in rows
            ]
        )
    )
    if any(r["status"] != "passed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
