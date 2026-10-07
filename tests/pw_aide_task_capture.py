"""Owned Aide reply -> reviewed task -> exact Plan/source/recovery workflow."""

import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

ANSWER = "# send the owned application\n\nkeep **this source detail** and [local note](/?doc=owned.md). 🌱"


class Model(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    holds = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        selected = any(
            "<alles_document_reference>" in str(message.get("content", ""))
            for message in body.get("messages", [])
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
                        if page.locator("#nav-backdrop").is_visible():
                            page.locator("#nav-backdrop").click(position={"x": width - 20, "y": 80})
                        if case == "private":
                            page.locator("#incognito-btn").click()
                            expect(page.locator("#incognito-bar")).to_be_visible()
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
                            page.locator("#wiki-ask-input").fill("use the owned source")
                            page.locator("#wiki-ask-go").click()
                        else:
                            page.locator("#composer-ta").fill("give me the owned application task")
                            page.locator("#send-btn").click()
                        expect(page.locator(".ai-body").last).to_contain_text(
                            "keep this source detail"
                        )
                        if source_case:
                            page.locator("#stop-btn").click()
                        expect(page.locator("#send-btn")).to_be_enabled()
                        reply = page.locator("#messages .ai-wrap").last
                        message = reply.locator("xpath=..").get_attribute("data-msg-id")
                        session = reply.get_attribute("data-session-id")
                        if source_case:
                            for _ in range(100):
                                history = api("GET", f"/api/sessions/{session}/history")["messages"]
                                if history and history[-1]["role"] == "assistant":
                                    break
                                page.wait_for_timeout(20)
                            canonical = history[-1]
                            assert canonical["meta"]["interrupted"] is True
                            for hold in Model.holds:
                                hold.set()
                            message = canonical["id"]
                            expected = canonical["content"].strip()
                            assert "[[source:" not in expected and "doc_hash=" in expected
                            assert "> owned source passage" in expected
                            if page.locator("#nav-backdrop").is_visible():
                                page.locator("#nav-backdrop").click(
                                    position={"x": width - 20, "y": 80}
                                )
                        if case == "history":
                            page.reload(wait_until="networkidle")
                            if page.locator("#nav-backdrop").is_visible():
                                page.locator("#nav-backdrop").click(
                                    position={"x": width - 20, "y": 80}
                                )
                        button = reply.locator('button[title="review this reply as a plan task"]')
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
                            button.click()
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
                        button.focus()
                        button.press("Enter")
                        if case == "source-stale":
                            old_button = button.element_handle()
                            expect(button).to_have_attribute("aria-disabled", "true")
                            if not page.locator("#new-chat-btn").is_visible():
                                page.get_by_role(
                                    "button", name="toggle Aide sidebar", exact=True
                                ).click()
                            page.locator("#new-chat-btn").click()
                            if page.locator("#aide-document-scope-remove").is_visible():
                                page.locator("#aide-document-scope-remove").click()
                            page.locator("#composer-ta").fill("another owned task")
                            page.locator("#send-btn").click()
                            expect(page.locator(".ai-body").last).to_contain_text(
                                "keep this source detail"
                            )
                            expect(page.locator("#send-btn")).to_be_enabled()
                            reply = page.locator("#messages .ai-wrap").last
                            message = reply.locator("xpath=..").get_attribute("data-msg-id")
                            session = reply.get_attribute("data-session-id")
                            expected = ANSWER
                            button = reply.locator(
                                'button[title="review this reply as a plan task"]'
                            )
                            button.click()
                        if case == "source-busy":
                            expect(button).to_have_attribute("aria-disabled", "true")
                            button.press("Enter")
                            assert len(held) == 1 and not writes
                            held.pop().continue_()
                        expect(page.locator("#capture-title")).to_be_visible()
                        expect(page.locator("#capture-notes")).to_have_value(expected)
                        assert not writes
                        title = f"owned reviewed {case} {width}"
                        page.locator("#capture-title").fill(title)
                        if case == "cancel":
                            page.locator("#capture-cancel").click()
                            expect(page.locator("#capture-title")).to_be_hidden()
                            expect(button).to_be_focused()
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
                                    if page.locator("#nav-backdrop").is_visible():
                                        page.locator("#nav-backdrop").click(
                                            position={"x": width - 20, "y": 80}
                                        )
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
                                    if not page.locator("#new-chat-btn").is_visible():
                                        page.get_by_role(
                                            "button", name="toggle Aide sidebar", exact=True
                                        ).click()
                                    page.locator("#new-chat-btn").click()
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
