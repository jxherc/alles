"""Owned saved/current search -> real Aide reply -> persisted source-linked note."""

import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

CASES = (
    "saved-note",
    "current-unsaved",
    "current-scoped",
    "saved-retry",
    "saved-deleted",
    "bounded-cancel",
    "bounded-accept",
    "cross-retry",
    "busy-handoff",
    "origin-deleted",
    "saved-modified",
    "empty-excerpts",
    "empty-evidence",
)


class ContinuationModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        self.requests.append(body)
        if not body.get("stream"):
            payload = json.dumps(
                {"choices": [{"message": {"content": "owned search answer"}}]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        prompt = next(
            (
                m["content"]
                for m in reversed(body["messages"])
                if m["role"] == "user"
                and isinstance(m["content"], str)
                and m["content"].startswith(
                    "Explain this search in relation to its original query."
                )
            ),
            None,
        )
        answer = "owned search title"
        if prompt:
            captured = json.JSONDecoder().raw_decode(prompt.split("\n\n", 1)[1])[0]
            result = captured["results"][0]
            answer = (
                f"owned continuation received\n\n[source]({result['url']})\n\n{result['snippet']}"
            )
            if captured["origin"]:
                answer += f"\n\n[original search]({captured['origin']['url']})"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in (
            {"choices": [{"delta": {"content": answer}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ):
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run(context_factory=None):
    _require_throwaway_data_root()
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ContinuationModel)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api("POST", "/api/setup/dismiss", {})
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned continuation fixture",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["continuation-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint,
                "default_model": "continuation-fixture",
                "model_roles": {
                    "aide_chat": {"endpoint_id": endpoint, "model": "continuation-fixture"}
                },
            },
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 820, 390):
                for case in CASES:
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
                    page.set_default_timeout(7000)
                    context.tracing.start(screenshots=True, snapshots=True)
                    errors, console, forbidden, handoffs, held, chats, opens = (
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                        [],
                    )
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda msg: console.append(msg.text) if msg.type == "error" else None,
                    )
                    label = f"{width}-{case}"
                    query = f"compare the saved local evidence {label} !ai"
                    source_url = HOME + "/owned/continuation/" + label
                    passage = "the exact saved passage shows seven quiet mornings"
                    claim = "saved overview interprets the morning pattern"
                    result = {
                        "title": "owned morning source",
                        "url": source_url,
                        "snippet": "a weekly observation",
                    }
                    payload = {
                        "query": query,
                        "request": {
                            "query": query,
                            "category": "all",
                            "normal_results": True,
                            "overview": True,
                        },
                        "results": [result],
                        "evidence": [
                            {
                                "id": "s1",
                                "url": source_url,
                                "title": "owned morning source",
                                "passages": [passage],
                            }
                        ],
                        "overview": {
                            "status": "ready",
                            "claims": [
                                {
                                    "text": claim,
                                    "citations": [
                                        {"source_id": "s1", "url": source_url, "quote": passage}
                                    ],
                                }
                            ],
                        },
                    }
                    if case.startswith("bounded") or case == "origin-deleted":
                        payload["results"] = [
                            {
                                **result,
                                "title": f"result {i}",
                                "url": source_url + f"/{i}",
                                "snippet": f"whole source {i}: " + "exact text " * 40,
                            }
                            for i in range(600)
                        ]
                    if case == "saved-modified":
                        payload["verification"] = {
                            "status": "checked",
                            "result": {"counts": {"verified": 1}, "checked_on": "2026-10-03"},
                        }
                    if case.startswith("empty-"):
                        payload["results"] = (
                            [] if case == "empty-evidence" else [{**result, "snippet": "  "}]
                        )
                        payload["evidence"][0]["passages"] = [" ", "\n"]
                        payload["overview"] = {}
                    saved = (
                        api("POST", "/api/andromeda/saved", payload)
                        if not case.startswith("current-")
                        else None
                    )
                    scope = None
                    project = api("POST", "/api/projects", {"name": "owned continuation " + label})
                    if case == "current-scoped":
                        note = f"continuation/{label}.md"
                        api(
                            "POST",
                            "/api/vault-md/file",
                            {"path": note, "content": "# owned context\nquiet mornings\n"},
                        )
                        stored_note = api("GET", "/api/vault-md/file?path=" + quote(note, safe=""))
                        scope = {
                            "kind": "vault_document",
                            "path": note,
                            "expected_hash": stored_note["hash"],
                        }
                    before = len(ContinuationModel.requests)
                    cross = case in ("cross-retry", "busy-handoff")
                    base = HOME.replace("127.0.0.1", "andromeda.localhost") if cross else HOME
                    saved_path = "/api/andromeda/saved/" + saved["id"] if saved else ""
                    if case == "saved-deleted":
                        api("DELETE", saved_path)

                    def routes(route):
                        parsed = urlparse(route.request.url)
                        if (
                            parsed.port != urlparse(HOME).port
                            or parsed.hostname
                            not in (
                                "127.0.0.1",
                                "andromeda.localhost",
                                "aide.localhost",
                                "localhost",
                            )
                            or parsed.path.startswith("/owned/")
                        ):
                            forbidden.append(route.request.url)
                            route.abort()
                        elif parsed.path == "/api/chat" and route.request.method == "POST":
                            chats.append(route.request.post_data_json)
                            route.continue_()
                        elif (
                            parsed.path == "/api/auth/context-handoff"
                            and route.request.method == "POST"
                        ):
                            handoffs.append(route.request.post_data_json)
                            if case == "cross-retry" and len(handoffs) == 1:
                                route.fulfill(status=503, json={"detail": "owned handoff outage"})
                            elif case == "busy-handoff":
                                held.append(route)
                            else:
                                route.continue_()
                        elif parsed.path == saved_path:
                            opens.append(parsed.path)
                            if case == "origin-deleted" and len(opens) == 2:
                                held.append(route)
                            elif case == "saved-retry" and len(opens) == 1:
                                route.fulfill(
                                    status=503, json={"detail": "owned saved-search outage"}
                                )
                            else:
                                route.continue_()
                        elif (
                            parsed.path.startswith("/api/andromeda/verification")
                            and case == "saved-modified"
                        ):
                            model = {"model": "owned verifier", "privacy_class": "local"}
                            if parsed.path.endswith("/preview"):
                                route.fulfill(json={"status": "ready", "model": model})
                            elif route.request.method == "POST":
                                route.fulfill(
                                    json={"id": "owned-check", "status": "running", "model": model}
                                )
                            else:
                                route.fulfill(
                                    json={
                                        "id": "owned-check",
                                        "status": "checked",
                                        "model": model,
                                        "result": {
                                            "counts": {"corrected": 1},
                                            "corrected_claims": [
                                                {
                                                    "text": "newer checked claim",
                                                    "citations": payload["overview"]["claims"][0][
                                                        "citations"
                                                    ],
                                                }
                                            ],
                                        },
                                    }
                                )
                        elif parsed.path == "/api/andromeda/providers":
                            route.fulfill(
                                json={
                                    "selected": "fixture",
                                    "providers": [
                                        {
                                            "value": "fixture",
                                            "label": "owned fixture",
                                            "available": True,
                                        }
                                    ],
                                }
                            )
                        elif parsed.path == "/api/andromeda/search" and case.startswith("current-"):
                            route.fulfill(
                                json={
                                    "query": query,
                                    "used_no_ai": True,
                                    "overview_requested": False,
                                    "normal_results_enabled": True,
                                    "category": "all",
                                    "provider": "fixture",
                                    "status": "ready",
                                    "elapsed_ms": 1,
                                    "has_more": False,
                                    "results": [result],
                                }
                            )
                        elif parsed.path.startswith(
                            "/api/andromeda/"
                        ) and not parsed.path.startswith("/api/andromeda/saved"):
                            route.fulfill(
                                status=400, json={"detail": "owned fixture refuses providers"}
                            )
                        else:
                            route.continue_()

                    context.route("**/*", routes)
                    record = {
                        "scenario_id": "andromeda.continuation." + case,
                        "profile": str(width),
                        "status": "failed",
                    }
                    try:
                        target = (
                            base + "/?app=andromeda" + ("&saved=" + saved["id"] if saved else "")
                        )
                        target += "&project_id=" + project["id"]
                        if scope:
                            code = api(
                                "POST",
                                "/api/auth/context-handoff",
                                {"ask": query, "web": True, "document_scope": scope},
                            )["code"]
                            target += "&ctx=" + code
                        page.goto(target, wait_until="networkidle")
                        retry = page.locator("#andromeda-saved-retry")
                        ask = page.locator("#andromeda-explain")
                        if case in ("saved-retry", "saved-deleted"):
                            expect(retry).to_be_visible()
                            page.screenshot(path=str(out / (label + "-error.png")), full_page=True)
                            retry.focus()
                            retry.press("Enter")
                            if case == "saved-deleted":
                                expect(page.locator("#andromeda-save-recovery")).to_contain_text(
                                    "not found"
                                )
                                expect(retry).to_have_attribute("aria-disabled", "false")
                                assert len(opens) == 2
                            else:
                                expect(retry).to_be_hidden()
                                assert opens == [saved_path, saved_path]
                        if case != "saved-deleted":
                            if case == "current-unsaved":
                                page.locator("#andromeda-query").fill(query)
                                page.locator("#andromeda-query").press("Enter")
                                expect(page.locator(".andromeda-result-title")).to_have_text(
                                    result["title"]
                                )
                            elif saved:
                                if case.startswith("empty-"):
                                    expect(page.locator("#andromeda-query")).to_have_value(query)
                                else:
                                    expect(page.locator("#andromeda-claims")).to_contain_text(claim)
                            else:
                                expect(page.locator(".andromeda-result-title")).to_have_text(
                                    result["title"]
                                )
                            if case == "saved-modified":
                                page.locator("#andromeda-verification-retry").click()
                                expect(page.locator("#andromeda-claims")).to_contain_text(
                                    "newer checked claim"
                                )
                                if width == 820:
                                    page.locator("#app-drawer-btn").click()
                                else:
                                    page.locator("#app-drawer-btn").focus()
                                    page.locator("#app-drawer-btn").press("Enter")
                                page.locator('.app-drawer-item[data-view="today"]').click()
                                expect(page.locator("#andromeda-view")).to_be_hidden()
                                page.go_back(wait_until="networkidle")
                                expect(page.locator("#andromeda-claims")).to_contain_text(claim)
                                assert len(opens) == 2
                                record["status"] = "passed"
                                continue
                            if case == "origin-deleted":
                                page.locator("#andromeda-settings-button").click()
                                page.locator("#andromeda-saved-list").get_by_role(
                                    "button", name=query, exact=True
                                ).click()
                                assert len(held) == 1
                                page.locator("#andromeda-settings-close").click()
                            ask.focus()
                            ask.press("Enter")
                            if case.startswith("empty-"):
                                expect(page.locator("#andromeda-status")).to_contain_text(
                                    "no source excerpts to explain"
                                )
                                expect(ask).to_be_focused()
                                assert not chats and not handoffs
                                assert len(ContinuationModel.requests) == before
                                stored = api("GET", saved_path)
                                for field in ("results", "evidence", "overview"):
                                    assert stored[field] == payload[field]
                                assert not errors and not forbidden
                                assert not [line for line in console if "status of 400" not in line]
                                record["status"] = "passed"
                                continue
                            if case == "origin-deleted":
                                dialog = page.get_by_role("alertdialog")
                                expect(dialog).to_be_visible()
                                api("DELETE", saved_path)
                                held.pop().continue_()
                                expect(page.locator("#andromeda-save-message")).to_contain_text(
                                    "not found"
                                )
                                dialog.get_by_role("button", name="confirm", exact=True).click()
                                expect(page.locator("#andromeda-status")).to_contain_text(
                                    "saved search changed"
                                )
                                assert not chats
                                record["status"] = "passed"
                                continue
                            if case.startswith("bounded"):
                                dialog = page.get_by_role("alertdialog")
                                expect(dialog).to_contain_text("of 600 results")
                                record["confirmation"] = dialog.inner_text()
                                expect(
                                    dialog.get_by_role("button", name="cancel", exact=True)
                                ).to_be_focused()
                                assert not chats and len(ContinuationModel.requests) == before
                                page.screenshot(
                                    path=str(out / (label + "-confirm.png")), full_page=True
                                )
                                if case == "bounded-cancel":
                                    page.keyboard.press("Escape")
                                    expect(ask).to_be_focused()
                                    assert not chats
                                else:
                                    dialog.get_by_role("button", name="confirm", exact=True).click()
                            if case == "cross-retry":
                                expect(page.locator("#andromeda-status")).to_contain_text(
                                    "Aide handoff failed"
                                )
                                assert not chats
                                expect(page.locator("#andromeda-claims")).to_contain_text(claim)
                                ask.press("Enter")
                            if case == "busy-handoff":
                                expect(ask).to_have_attribute("aria-disabled", "true")
                                expect(ask).to_be_focused()
                                ask.press("Enter")
                                assert len(handoffs) == len(held) == 1
                                held.pop().continue_()
                            if case != "bounded-cancel":
                                expect(page.locator(".ai-body").last).to_contain_text(
                                    "owned continuation received"
                                )
                                expect(page.locator("#send-btn")).to_be_enabled()
                                prompts = [
                                    m["content"]
                                    for r in ContinuationModel.requests[before:]
                                    if r.get("stream")
                                    for m in r["messages"]
                                    if m["role"] == "user"
                                ]
                                record["model_user_messages"] = prompts
                                prompts = [
                                    p
                                    for p in prompts
                                    if p.startswith(
                                        "Explain this search in relation to its original query."
                                    )
                                ]
                                assert len(prompts) == 1, record["model_user_messages"]
                                captured = json.JSONDecoder().raw_decode(
                                    prompts[0].split("\n\n", 1)[1]
                                )[0]
                                assert captured["query"] == query
                                assert (
                                    captured["results"][0]["snippet"]
                                    == payload["results"][0]["snippet"]
                                )
                                assert len(chats) == 1
                                assert chats[0].get("context_scope") == scope
                                if scope:
                                    assert (
                                        scope["path"] in prompts[0]
                                        and "quiet mornings" in prompts[0]
                                    )
                                sessions = api("GET", "/api/sessions")
                                assert (
                                    next(
                                        item
                                        for group in sessions.values()
                                        for item in group
                                        if item["id"] == chats[0]["session_id"]
                                    )["project_id"]
                                    == project["id"]
                                )
                                if saved:
                                    assert captured["origin"]["saved_search_id"] == saved["id"]
                                    assert parse_qs(urlparse(captured["origin"]["url"]).query)[
                                        "project_id"
                                    ] == [project["id"]]
                                    assert captured["evidence"][0]["passages"] == [passage]
                                    if captured["coverage"]["overview_included"]:
                                        assert captured["overview"] == payload["overview"]
                                    else:
                                        assert (
                                            case == "bounded-accept"
                                            and captured["overview"] is None
                                        )
                                        assert "the overview is omitted" in record["confirmation"]
                                else:
                                    assert captured["origin"] is None
                                if case == "bounded-accept":
                                    assert len(prompts[0]) <= 20_000
                                    assert captured["coverage"]["results_total"] == 600
                                    assert (
                                        captured["coverage"]["results_included"]
                                        == len(captured["results"])
                                        < 600
                                    )
                                    for item in captured["results"]:
                                        assert (
                                            item["snippet"]
                                            == payload["results"][item["rank"] - 1]["snippet"]
                                        )
                                if cross:
                                    assert urlparse(page.url).hostname == "aide.localhost"
                                    assert "ask" not in parse_qs(urlparse(page.url).query)
                                    assert handoffs[-1]["ask"] == prompts[0]
                                if case == "saved-note":
                                    page.reload(wait_until="networkidle")
                                    if page.locator("#nav-backdrop").is_visible():
                                        page.locator("#nav-backdrop").click(
                                            position={
                                                "x": page.evaluate("innerWidth") - 20,
                                                "y": 80,
                                            }
                                        )
                                    expect(page.locator(".ai-body").last).to_contain_text(
                                        "owned continuation received"
                                    )
                                    page.get_by_role(
                                        "button", name="+note", exact=True
                                    ).last.click()
                                    open_note = page.locator("#aide-note-recovery .note-saved-open")
                                    expect(open_note).to_be_visible()
                                    note_path = (
                                        page.locator("#aide-note-recovery p")
                                        .inner_text()
                                        .removeprefix("saved to ")
                                    )
                                    content = api(
                                        "GET",
                                        "/api/vault-md/file?path=" + quote(note_path, safe=""),
                                    )["content"]
                                    assert (
                                        source_url in content
                                        and captured["origin"]["url"] in content
                                        and "[from Aide]" in content
                                    )
                                    open_note.click()
                                    preview = page.locator("#wiki-preview")
                                    expect(preview).to_contain_text("owned continuation received")
                                    link = preview.get_by_role(
                                        "link", name="original search", exact=True
                                    )
                                    assert link.get_attribute("href") == captured["origin"]["url"]
                                    with context.expect_page() as opened:
                                        link.click()
                                    returned = opened.value
                                    expect(returned.locator("#andromeda-claims")).to_contain_text(
                                        claim
                                    )
                                    assert parse_qs(urlparse(returned.url).query)["saved"] == [
                                        saved["id"]
                                    ]
                                    returned.close()
                        if saved and case != "saved-deleted":
                            stored = api("GET", saved_path)
                            assert stored["results"] == payload["results"]
                            assert stored["evidence"] == payload["evidence"]
                            assert stored["overview"] == payload["overview"]
                        assert not forbidden, forbidden
                        assert not errors, errors
                        unexpected = [
                            line
                            for line in console
                            if not any(f"status of {code}" in line for code in (400, 404, 503))
                        ]
                        assert not unexpected, unexpected
                        record["status"] = "passed"
                    except Exception:
                        record["error"] = traceback.format_exc()
                    finally:
                        for route in held:
                            route.abort()
                        record["rendered"] = page.evaluate(
                            "({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth})"
                        )
                        record["model_user_messages"] = [
                            m.get("content")
                            for r in ContinuationModel.requests[before:]
                            for m in r.get("messages", [])
                            if m.get("role") == "user"
                        ]
                        record["console"] = console
                        record["page_errors"] = errors
                        record["forbidden_requests"] = forbidden
                        if record["rendered"]["overflow"]:
                            record["status"] = "failed"
                            record["error"] = record.get("error", "") + "\npage overflow"
                        page.screenshot(path=str(out / (label + ".png")), full_page=True)
                        context.tracing.stop(path=str(out / (label + ".zip")))
                        rows.append(record)
                        context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows))
    if any(row["status"] != "passed" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
