"""Selected notes to cited answer to a recoverable Markdown note, on the real server."""

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api


class SourceModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests = []
    holds = []

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        messages = request.get("messages", [])
        selected = any("<alles_document_reference>" in str(m.get("content", "")) for m in messages)
        if selected:
            self.requests.append(request)
        question = str(messages[-1].get("content", "")) if messages else ""
        if "question-uncited" in question:
            content = "**comparison**: an answer without passage coordinates"
        elif "question-invalid" in question:
            content = "**comparison**: check this [[source:7:4-99]]"
        else:
            content = "**comparison**: the notes disagree [[source:1:2-2]] [[source:2:2-2]]"
        if not request.get("stream"):
            payload = json.dumps(
                {"choices": [{"message": {"content": "source comparison"}}]}
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
        for delta in (content, ""):
            event = {
                "choices": [
                    {"delta": {"content": delta}, "finish_reason": None if delta else "stop"}
                ]
            }
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
            if delta and "question-interrupted" in question:
                hold = threading.Event()
                self.holds.append(hold)
                hold.wait(15)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run():
    _require_throwaway_data_root()
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SourceModel)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    records, failures = [], []
    try:
        api("POST", "/api/setup/dismiss", {})
        eid = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned sources",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{eid}", {"models": ["source-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": eid,
                "default_model": "source-fixture",
                "model_roles": {"aide_chat": {"endpoint_id": eid, "model": "source-fixture"}},
            },
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width, height in ((1440, 900), (820, 900), (390, 900), (720, 450)):
                cases = (
                    "success",
                    "changed",
                    "save-lost",
                    "uncited",
                    "invalid",
                    "literal",
                    "dirty",
                    "reopen",
                    "rejected",
                    "edit-during-check",
                    "rapid",
                    "many",
                    "interrupted",
                    "interrupted-history-fail",
                    "interrupted-pending",
                    "interrupted-private",
                    "validation-retry",
                    "citation-labels",
                )
                for case in (
                    case
                    for case in cases
                    if (width != 720 or case == "many")
                    and (not sys.argv[1:] or case in sys.argv[1:])
                ):
                    label = f"{width}-{case}"
                    record = {
                        "scenario_id": f"knowledge.selected-{case}",
                        "profile": "phone"
                        if width == 390
                        else "tablet"
                        if width == 820
                        else "desktop",
                        "status": "failed",
                        "evidence": [label + ".zip", label + ".png", label + ".json"],
                        "simulation": "synthetic loopback model; save-lost replaces one acknowledged real save with HTTP503; other APIs real",
                    }
                    records.append(record)
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        is_mobile=width == 390,
                        has_touch=width == 390,
                        reduced_motion="reduce",
                        service_workers="block",
                        color_scheme="light" if case == "uncited" else "dark",
                    )
                    context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    errors, requests, notes = [], [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda msg: (
                            errors.append(msg.text)
                            if msg.type == "error" and "503" not in msg.text
                            else None
                        ),
                    )
                    path1, path2 = f"{label}/one/source.md", f"{label}/two/source.md"
                    if case == "many":
                        folder = label + "/" + "x" * 90 + "/" + "y" * 90
                        path1, path2 = folder + "/one.md", folder + "/two.md"
                    expected_paths = [path1, path2]
                    api(
                        "POST",
                        "/api/vault-md/file",
                        {"path": path1, "content": "# source\nopen on monday\n"},
                    )
                    api(
                        "POST",
                        "/api/vault-md/file",
                        {"path": path2, "content": "# source\nclosed on monday\n"},
                    )
                    question = f"question-{case}: compare the notes"
                    first_line = "open on monday"
                    if case == "literal":
                        first_line = "**literal** $x$ [brackets] <mark>text</mark>"
                        current = api("GET", "/api/vault-md/file?path=" + quote(path1, safe=""))
                        api(
                            "POST",
                            "/api/vault-md/safety/save",
                            {
                                "path": path1,
                                "content": "# source\n" + first_line + "\n",
                                "expected_hash": current["hash"],
                            },
                        )
                    try:
                        page.goto(
                            HOME + "/?app=docs&doc=" + quote(path1, safe=""),
                            wait_until="networkidle",
                        )
                        expect(page.locator("#wiki-preview")).to_contain_text("source")
                        if case == "interrupted-private":
                            page.locator("#app-drawer-btn").click()
                            page.locator('.app-drawer-item[data-view="chat"]').click()
                            if page.locator("#nav-backdrop").is_visible():
                                page.locator("#nav-backdrop").click(
                                    position={"x": width - 20, "y": 80}
                                )
                            page.locator("#incognito-btn").click()
                            expect(page.locator("#incognito-bar")).to_be_visible()
                            page.go_back(wait_until="networkidle")
                            expect(page.locator("#wiki-preview")).to_contain_text("source")
                        if case == "dirty":
                            page.locator("#wiki-edit-btn").click()
                            page.locator("#wiki-source-btn").click()
                            first_line = "saved edited source"
                            page.locator("#wiki-source").fill("# source\n" + first_line + "\n")
                        ask = page.locator("#wiki-ask-btn")
                        ask.focus()
                        page.keyboard.press("Enter")
                        expect(page.locator("#wiki-ask-sources")).to_contain_text(path1)
                        page.locator("#wiki-ask-search").fill(path2)
                        match = page.locator("#wiki-ask-matches").get_by_role(
                            "button", name=path2, exact=True
                        )
                        expect(match).to_be_visible()
                        if case == "reopen":
                            page.locator("#wiki-ask-close").click()
                            page.locator("#wiki-ask-btn").click()
                            expect(match).to_be_visible()
                        held = []
                        if case == "rapid":
                            page.route(
                                "**/api/vault-md/file?path=" + quote(path2, safe=""),
                                lambda route: held.append(route),
                                times=1,
                            )
                        match.click()
                        if case == "rapid":
                            expect(page.locator("#wiki-ask-go")).to_be_disabled()
                            third = f"{label}/three/source.md"
                            api(
                                "POST",
                                "/api/vault-md/file",
                                {"path": third, "content": "# source\nthird passage"},
                            )
                            page.locator("#wiki-ask-search").fill(third)
                            page.locator("#wiki-ask-matches").get_by_role(
                                "button", name=third, exact=True
                            ).click()
                            expect(
                                page.locator("#wiki-ask-sources span").filter(has_text=third)
                            ).to_have_count(1)
                            assert len(held) == 1
                            held.pop().continue_()
                            expected_paths.append(third)
                        expect(
                            page.locator("#wiki-ask-sources span").filter(has_text=path2)
                        ).to_have_count(1)
                        if case == "many":
                            for index in range(3, 9):
                                extra = folder + f"/extra-{index}.md"
                                api(
                                    "POST",
                                    "/api/vault-md/file",
                                    {"path": extra, "content": "# source\nextra passage"},
                                )
                                expected_paths.append(extra)
                                page.locator("#wiki-ask-search").fill(extra)
                                page.locator("#wiki-ask-matches").get_by_role(
                                    "button", name=extra, exact=True
                                ).click()
                            expect(page.locator("#wiki-ask-sources span")).to_have_count(8)
                        if case == "validation-retry":
                            third = f"{label}/three/source.md"
                            api(
                                "POST",
                                "/api/vault-md/file",
                                {"path": third, "content": "third source"},
                            )
                            page.locator("#wiki-ask-search").fill(third)
                            expect(
                                page.locator("#wiki-ask-matches").get_by_role(
                                    "button", name=third, exact=True
                                )
                            ).to_be_visible()
                        page.locator("#wiki-ask-input").fill(question)
                        for element in page.locator("#wiki-ask button, #wiki-ask input").all():
                            box = element.bounding_box()
                            if box:
                                assert box["height"] >= 43.5, box
                                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, box
                        before = len(SourceModel.requests)
                        if case in ("changed", "validation-retry"):
                            read = api("GET", "/api/vault-md/file?path=" + quote(path2, safe=""))
                            api(
                                "POST",
                                "/api/vault-md/safety/save",
                                {
                                    "path": path2,
                                    "content": "newer version",
                                    "expected_hash": read["hash"],
                                },
                            )
                        if case == "edit-during-check":
                            page.locator("#wiki-edit-btn").click()
                            page.locator("#wiki-source-btn").click()
                            page.route(
                                "**/api/vault-md/file?path=" + quote(path1, safe=""),
                                lambda route: held.append(route),
                                times=1,
                            )
                        if case in ("rejected", "many"):
                            page.route(
                                "**/api/chat",
                                lambda route: route.fulfill(
                                    status=503,
                                    content_type="application/json",
                                    body='{"detail":"fixture temporarily unavailable"}',
                                ),
                                times=1,
                            )
                        page.locator("#wiki-ask-go").click()
                        if case == "edit-during-check":
                            first_line = "edited during validation"
                            page.locator("#wiki-source").fill("# source\n" + first_line + "\n")
                            assert len(held) == 1
                            held.pop().continue_()
                            expect(page.locator("#wiki-ask-results")).to_contain_text(
                                "changed while checking"
                            )
                            assert len(SourceModel.requests) == before
                            expect(page.locator("#wiki-source")).to_have_value(
                                "# source\n" + first_line + "\n"
                            )
                            page.locator("#wiki-ask-go").click()
                        if case in ("rejected", "many"):
                            expect(page.locator("#composer-ta")).to_have_value(question)
                            expect(page.locator("#aide-document-scope-name")).to_contain_text(
                                f"{len(expected_paths)} notes only"
                            )
                            assert len(SourceModel.requests) == before
                            if (
                                width == 390
                                and page.locator("body.is-aide:not(.sidebar-hidden)").count()
                            ):
                                page.locator("#nav-backdrop").click(
                                    position={"x": width - 20, "y": 80}
                                )
                            expect(page.locator("#composer-ta")).to_be_in_viewport()
                            expect(page.locator(".error-msg").last).to_be_in_viewport()
                            if case == "many":
                                sources = page.locator("details.user-context-scope").last
                                expect(sources).not_to_have_attribute("open", "")
                                sources.locator("summary").focus()
                                page.keyboard.press("Enter")
                                expect(sources.locator("li")).to_have_count(8)
                                page.keyboard.press("Enter")
                                scope = page.locator("#aide-document-scope-name")
                                scope.focus()
                                page.keyboard.press("End")
                                page.wait_for_function(
                                    "document.getElementById('aide-document-scope-name').scrollTop > 0"
                                )
                                assert page.evaluate(
                                    "document.documentElement.scrollWidth <= innerWidth + 1"
                                )
                                page.screenshot(path=str(output / (label + "-recovery.png")))
                            page.locator("#send-btn").click()
                        if case in ("changed", "validation-retry"):
                            expect(page.locator("#wiki-ask-results")).to_contain_text(
                                "changed or is missing"
                            )
                            expect(page.locator("#wiki-ask-input")).to_have_value(question)
                            assert len(SourceModel.requests) == before
                            if case == "validation-retry":
                                page.locator("#wiki-ask-matches").get_by_role(
                                    "button", name=third, exact=True
                                ).click()
                                expect(
                                    page.locator("#wiki-ask-sources span").filter(has_text=third)
                                ).to_have_count(1)
                        else:
                            expect(page.locator(".ai-content").last).to_contain_text("comparison")
                            if case.startswith("interrupted"):
                                page.locator("#stop-btn").click()
                                expect(page.locator("#send-btn")).to_be_enabled()
                                if page.locator("#nav-backdrop").is_visible():
                                    page.locator("#nav-backdrop").click(
                                        position={"x": width - 20, "y": 80}
                                    )
                                session = page.evaluate("window._currentSession.id")
                                for _ in range(100):
                                    messages = api("GET", f"/api/sessions/{session}/history")[
                                        "messages"
                                    ]
                                    if messages and messages[-1]["role"] == "assistant":
                                        break
                                    page.wait_for_timeout(20)
                                assert messages[-1]["meta"]["interrupted"] is True
                                save = page.get_by_role("button", name="+note", exact=True).last
                                note_writes = []
                                page.on(
                                    "request",
                                    lambda request: (
                                        note_writes.append(request.post_data_json)
                                        if request.url.endswith("/api/vault-md/file")
                                        and request.method == "POST"
                                        else None
                                    ),
                                )
                                if case in ("interrupted-history-fail", "interrupted-pending"):
                                    page.route(
                                        f"**/api/sessions/{session}/history",
                                        lambda route: (
                                            route.fulfill(
                                                status=503, json={"detail": "fixture unavailable"}
                                            )
                                            if case == "interrupted-history-fail"
                                            else route.fulfill(json={"messages": []})
                                        ),
                                        times=1,
                                    )
                                    save.click()
                                    expect(page.locator("#aide-note-recovery")).to_contain_text(
                                        "try +note again"
                                    )
                                    expect(save).to_be_enabled()
                                    assert not note_writes
                                save.click()
                                expect(
                                    page.locator("#aide-note-recovery .note-saved-open")
                                ).to_be_visible()
                                saved_path = (
                                    page.locator("#aide-note-recovery p")
                                    .inner_text()
                                    .removeprefix("saved to ")
                                )
                                stored = api(
                                    "GET", "/api/vault-md/file?path=" + quote(saved_path, safe="")
                                )
                                assert "[[source:" not in stored["content"], stored["content"]
                                assert len(note_writes) == 1
                                if case == "interrupted-private":
                                    assert (
                                        "saved from a private Aide conversation"
                                        in stored["content"]
                                    )
                                    assert "[from Aide]" not in stored["content"]
                                assert (
                                    "doc_hash=" in stored["content"]
                                    and "> open on monday" in stored["content"]
                                )
                                expect(page.locator(".ai-content blockquote").first).to_have_text(
                                    "open on monday"
                                )
                                page.locator("#aide-note-recovery .note-saved-open").click()
                                expect(page.locator("#wiki-preview")).to_contain_text(
                                    "source passages"
                                )
                                page.screenshot(path=str(output / (label + ".png")), full_page=True)
                                assert not errors, errors
                                record["status"] = "passed"
                                continue
                            if case == "citation-labels":
                                expect(
                                    page.locator(".ai-content").last.get_by_role(
                                        "link", name=f"2. {path2}, lines 2–2", exact=True
                                    )
                                ).to_be_visible()
                            expect(page.locator(".source-citation-status").last).to_be_visible()
                            expect(page.locator("#send-btn")).to_be_enabled()
                            assert len(SourceModel.requests) == before + 1
                            model = SourceModel.requests[-1]
                            assert not model.get("tools")
                            assert len(model["messages"]) == 2
                            session = page.evaluate("window._currentSession.id")
                            saved_url = page.url
                            history = api("GET", f"/api/sessions/{session}/history")["messages"][-1]
                            assert (
                                history["meta"]["context_provenance"]["document"]["kind"]
                                == "vault_documents"
                            )
                            snapshots = history["meta"]["context_provenance"]["document"][
                                "documents"
                            ]
                            assert {item["path"] for item in snapshots} == set(expected_paths)
                            assert snapshots[0]["content"] == "# source\n" + first_line + "\n"
                            status = (
                                "uncited"
                                if case == "uncited"
                                else "needs_review"
                                if case == "invalid"
                                else "cited"
                            )
                            assert history["meta"]["source_citations"]["status"] == status
                            page.reload(wait_until="networkidle")
                            if width == 390 and not page.locator("body.sidebar-hidden").count():
                                page.locator("#nav-backdrop").click(
                                    position={"x": width - 20, "y": 80}
                                )
                            expect(page.locator(".source-citation-status")).to_be_visible()
                            page.locator(".context-provenance > summary").click()
                            page.locator(".source-snapshot > summary").first.click()
                            expect(page.locator(".source-snapshot pre").first).to_contain_text(
                                first_line
                            )
                            page.locator(".context-provenance > summary").click()
                            if case == "literal":
                                expect(page.locator(".ai-content blockquote").first).to_have_text(
                                    first_line
                                )
                            if case in ("success", "save-lost", "literal", "citation-labels"):
                                save = page.get_by_role("button", name="+note", exact=True).last
                                if case == "save-lost":

                                    def lost(route):
                                        if route.request.method != "POST":
                                            route.continue_()
                                            return
                                        requests.append(route.request.post_data_json)
                                        response = route.fetch()
                                        notes.append(response.json())
                                        assert response.ok
                                        route.fulfill(
                                            status=503,
                                            content_type="application/json",
                                            body='{"detail":"fixture reply lost"}',
                                        )

                                    page.route("**/api/vault-md/file", lost, times=1)
                                save.click()
                                if case == "save-lost":
                                    expect(
                                        page.locator("#aide-note-recovery .note-retry")
                                    ).to_be_visible()
                                    page.reload(wait_until="networkidle")
                                    if (
                                        width == 390
                                        and not page.locator("body.sidebar-hidden").count()
                                    ):
                                        page.locator("#nav-backdrop").click(
                                            position={"x": width - 20, "y": 80}
                                        )
                                    expect(
                                        page.locator("#aide-note-recovery .note-retry")
                                    ).to_be_visible()
                                    page.locator("#aide-note-recovery .note-retry").click()
                                open_note = page.locator("#aide-note-recovery .note-saved-open")
                                expect(open_note).to_be_visible()
                                if case == "save-lost":
                                    repeat_posts = []
                                    page.on(
                                        "request",
                                        lambda request: (
                                            repeat_posts.append(request.post_data_json)
                                            if request.method == "POST"
                                            and request.url.endswith("/api/vault-md/file")
                                            else None
                                        ),
                                    )
                                    original_feedback = page.locator(
                                        "#aide-note-recovery p"
                                    ).inner_text()
                                    saved_button = page.locator(".ai-wrap").last.get_by_role(
                                        "button", name="saved note", exact=True
                                    )
                                    expect(saved_button).to_be_visible()
                                    saved_button.focus()
                                    page.keyboard.press("Enter")
                                    expect(open_note).to_be_visible()
                                    page.wait_for_timeout(100)
                                    assert not repeat_posts, repeat_posts
                                    assert (
                                        page.locator("#aide-note-recovery p").inner_text()
                                        == original_feedback
                                    )
                                    with page.expect_response(
                                        lambda response: response.url.endswith(
                                            f"/api/sessions/{session}/history"
                                        )
                                    ):
                                        page.evaluate("window._reloadActiveSession()")
                                    expect(saved_button).to_be_visible()
                                    saved_button.click()
                                    page.wait_for_timeout(100)
                                    assert not repeat_posts, repeat_posts

                                saved_path = (
                                    page.locator("#aide-note-recovery p")
                                    .inner_text()
                                    .removeprefix("saved to ")
                                )
                                stored = api(
                                    "GET", "/api/vault-md/file?path=" + quote(saved_path, safe="")
                                )
                                assert stored["content"].startswith("**comparison**")
                                assert (
                                    "[from Aide](/?app=aide#" + session + ")" in stored["content"]
                                )
                                assert "doc_hash=" in stored["content"]
                                assert (
                                    "> open on monday" in stored["content"]
                                    if case != "literal"
                                    else r"\*\*literal\*\*" in stored["content"]
                                )
                                if case == "save-lost":
                                    assert saved_path == notes[0]["path"]
                                open_note.click()
                                expect(page.locator("#wiki-preview")).to_contain_text(
                                    "source passages"
                                )
                                with page.expect_popup() as source_page:
                                    page.locator("#wiki-preview").get_by_role(
                                        "link", name="from Aide", exact=True
                                    ).click()
                                source_page = source_page.value
                                expect(source_page.locator(".ai-content").last).to_be_visible()
                                expect(source_page.locator(".ai-content").last).to_contain_text(
                                    "comparison"
                                )
                                assert source_page.evaluate("window._currentSession.id") == session
                                source_page.close()

                                assert page.evaluate("window._currentSession.id") == session
                                read = api(
                                    "GET", "/api/vault-md/file?path=" + quote(path1, safe="")
                                )
                                api(
                                    "POST",
                                    "/api/vault-md/safety/save",
                                    {
                                        "path": path1,
                                        "content": "new current source",
                                        "expected_hash": read["hash"],
                                    },
                                )
                                href = snapshots[0]["url"]
                                page.goto(HOME + href, wait_until="networkidle")
                                expect(page.locator("#wiki-inline-message")).to_contain_text(
                                    "changed after this answer"
                                )
                                expect(page.locator("#wiki-preview")).not_to_contain_text(
                                    "new current source"
                                )
                                page.get_by_role(
                                    "button", name="open current version", exact=True
                                ).click()
                                expect(page.locator("#wiki-preview")).to_contain_text(
                                    "new current source"
                                )
                                page.goto(saved_url, wait_until="networkidle")
                                expect(page.locator(".ai-content").last).to_contain_text(first_line)
                        if (
                            width == 390
                            and page.locator("body.is-aide:not(.sidebar-hidden)").count()
                        ):
                            page.locator("#nav-backdrop").click(position={"x": width - 20, "y": 80})
                        page.screenshot(path=str(output / (label + ".png")), full_page=True)
                        assert not errors, errors
                        record["status"] = "passed"
                    except Exception as error:
                        record["error"] = str(error)
                        failures.append(label + ": " + traceback.format_exc())
                        page.screenshot(path=str(output / (label + "-failed.png")), full_page=True)
                    finally:
                        for hold in SourceModel.holds:
                            hold.set()
                        SourceModel.holds.clear()
                        (output / (label + ".json")).write_text(
                            json.dumps(
                                {"errors": errors, "requests": requests, "notes": notes}, indent=2
                            )
                        )
                        context.tracing.stop(path=str(output / (label + ".zip")))
                        context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))
        (output / "provider.json").write_text(json.dumps(SourceModel.requests, indent=2))
    if failures:
        raise AssertionError("\n".join(failures))


if __name__ == "__main__":
    run()
