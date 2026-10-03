"""Aide tool sources through a local model, real tools, persistence and Docs navigation."""

import json
import os
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api


class SourceModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        messages = request.get("messages", [])
        question = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        found = re.search(r"source-(1440|820|390)\.md", question)
        results = [m for m in messages if m.get("role") == "tool"]
        call = None
        if found and request.get("tools"):
            path = found.group()
            if not results:
                call = ("docs_search", {"query": "owned source phrase"})
            elif len(results) == 1:
                call = ("note_read", {"name": path.removesuffix(".md")})
            elif len(results) == 2:
                call = ("docs_read", {"path": "missing-owned-source.md"})
            elif len(results) == 3:
                snapshot = json.loads(results[1]["content"])
                call = (
                    "docs_write",
                    {
                        "path": path,
                        "content": "denied replacement",
                        "expected_hash": snapshot["hash"],
                    },
                )
        if call:
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"source-call-{len(results)}",
                        "type": "function",
                        "function": {"name": call[0], "arguments": json.dumps(call[1])},
                    }
                ]
            }
        else:
            delta = {
                "content": "owned source inspected; missing read and change were not completed"
            }
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in (
            {"choices": [{"delta": delta}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls" if call else "stop"}]},
        ):
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run(context_factory=None):
    _require_throwaway_data_root()
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    data = Path(os.environ["ALLES_DATA"])
    rows = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), SourceModel)
    provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        api("POST", "/api/setup/dismiss", {})
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned source fixture",
                "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["source-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint,
                "default_model": "source-fixture",
                "model_roles": {"aide_chat": {"endpoint_id": endpoint, "model": "source-fixture"}},
            },
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in (1440, 820, 390):
                    path = f"source-{width}.md"
                    api(
                        "POST",
                        "/api/vault-md/file",
                        {"path": path, "content": "owned source phrase\noriginal local content"},
                    )
                    original = api("GET", "/api/vault-md/file?path=" + path)
                    context = (
                        context_factory(pw, width)
                        if context_factory
                        else browser.new_context(
                            viewport={"width": width, "height": 900},
                            reduced_motion="reduce",
                            service_workers="block",
                        )
                    )
                    context.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if urlparse(route.request.url).netloc == urlparse(HOME).netloc
                            else route.abort()
                        ),
                    )
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            errors.append(message.text) if message.type == "error" else None
                        ),
                    )
                    phase = "read-search-denied-reload"

                    def close_sidebar():
                        backdrop = page.locator("#nav-backdrop")
                        if backdrop.is_visible():
                            backdrop.click(
                                position={"x": page.evaluate("innerWidth") - 20, "y": 80}
                            )
                        expect(backdrop).not_to_be_visible()

                    def passed(case):
                        rows.append(
                            {
                                "profile": str(width),
                                "case": case,
                                "status": "passed",
                                "rendered": page.evaluate(
                                    "({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme})"
                                ),
                            }
                        )

                    try:
                        page.goto(HOME + "/?app=aide", wait_until="networkidle")
                        close_sidebar()
                        page.locator("#perm-mode-btn").click()
                        page.locator('#perm-menu [data-v="approve"]').click()
                        page.locator("#composer-ta").fill(f"inspect the owned source {path}")
                        page.locator("#send-btn").click()
                        expect(page.locator(".agent-perm-deny")).to_be_visible()
                        page.locator(".agent-perm-deny").click()
                        expect(page.locator(".ai-body").last).to_contain_text(
                            "owned source inspected"
                        )
                        expect(page.locator("#send-btn")).to_be_enabled()
                        conversation = page.url
                        page.reload(wait_until="networkidle")
                        close_sidebar()
                        button = page.locator("[data-agent-sources]").last
                        rid = button.get_attribute("data-agent-sources")
                        sources_url = f"/api/agent/runs/{rid}/sources"
                        sources = api("GET", sources_url)
                        assert sources["outcomes"] == {
                            "succeeded": 2,
                            "failed": 2,
                            "unfinished": 0,
                            "unknown": 0,
                        }, sources
                        assert sources["files"] == [path], sources
                        assert (
                            api("GET", "/api/vault-md/file?path=" + path)["hash"]
                            == original["hash"]
                        )
                        button.focus()
                        button.press("Enter")
                        panel = page.locator(".agent-sources")
                        expect(panel).to_contain_text("2 failed or denied")
                        expect(panel).to_contain_text("search results")
                        expect(panel).not_to_contain_text("missing-owned-source")
                        expect(button).to_have_attribute("aria-expanded", "true")
                        expect(button).to_be_focused()
                        exact_link = panel.locator('a[href*="doc_hash="]')
                        expect(exact_link).to_have_count(1)
                        assert f"doc_hash={original['hash']}" in exact_link.get_attribute("href")
                        exact_link.focus()
                        expect(exact_link).to_be_focused()
                        expect(exact_link).to_be_in_viewport()
                        assert exact_link.bounding_box()["height"] >= 44
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(path=str(out / f"{width}-sources.png"), full_page=True)
                        assert not errors, errors
                        passed(phase)

                        phase = "source-link-and-changed-version"
                        exact_link.press("Enter")
                        expect(page.locator("#wiki-preview")).to_contain_text(
                            "original local content"
                        )
                        api(
                            "POST",
                            "/api/vault-md/safety/save",
                            {
                                "path": path,
                                "content": "changed local source",
                                "expected_hash": original["hash"],
                            },
                        )
                        page.goto(conversation, wait_until="networkidle")
                        close_sidebar()
                        page.locator("[data-agent-sources]").last.click()
                        page.locator('.agent-sources a[href*="doc_hash="]').click()
                        expect(
                            page.get_by_role("button", name="open current version", exact=True)
                        ).to_be_visible()
                        page.get_by_role("button", name="open current version", exact=True).click()
                        expect(page.locator("#wiki-preview")).to_contain_text(
                            "changed local source"
                        )
                        assert not errors, errors
                        passed(phase)

                        phase = "failed-load-retry"
                        page.goto(conversation, wait_until="networkidle")
                        close_sidebar()
                        button = page.locator("[data-agent-sources]").last
                        pattern = "**" + sources_url

                        def failed(route):
                            route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"owned failure"}',
                            )

                        page.route(pattern, failed)
                        button.click()
                        expect(button).to_have_text("retry sources")
                        expect(button).to_be_enabled()
                        expect(button).to_be_focused()
                        assert len(errors) == 1 and "503" in errors[0], errors
                        errors.clear()
                        page.unroute(pattern, failed)
                        button.focus()
                        button.press("Enter")
                        expect(page.locator(".agent-sources")).to_contain_text("confirmed reads")
                        expect(button).to_have_text("sources")
                        assert not errors, errors
                        passed(phase)

                        phase = "event-rollover-reload"
                        run_path = data / "agent_runs" / f"{rid}.json"
                        saved = json.loads(run_path.read_text())
                        saved["events"] = [{"type": "status", "data": {"i": i}} for i in range(300)]
                        run_path.write_text(json.dumps(saved))
                        page.reload(wait_until="networkidle")
                        close_sidebar()
                        page.locator("[data-agent-sources]").last.click()
                        expect(page.locator('.agent-sources a[href*="doc_hash="]')).to_have_count(1)
                        assert api("GET", sources_url)["outcomes"]["succeeded"] == 2
                        assert not errors, errors
                        passed(phase)

                        phase = "legacy-history-uncertainty"
                        saved.pop("source_tracking", None)
                        for step in saved["tool_steps"]:
                            step.pop("completed", None)
                        run_path.write_text(json.dumps(saved))
                        page.reload(wait_until="networkidle")
                        close_sidebar()
                        page.locator("[data-agent-sources]").last.click()
                        expect(page.locator(".agent-sources")).to_contain_text("incomplete history")
                        expect(page.locator(".agent-sources")).to_contain_text(
                            "4 with an unknown outcome"
                        )
                        expect(page.locator(".agent-sources a")).to_have_count(0)
                        assert not errors, errors
                        passed(phase)
                    except Exception as exc:
                        rows.append(
                            {
                                "profile": str(width),
                                "case": phase,
                                "status": "failed",
                                "error": str(exc),
                                "traceback": traceback.format_exc(),
                            }
                        )
                        page.screenshot(path=str(out / f"{width}-failure.png"), full_page=True)
                    finally:
                        context.close()
                        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
            finally:
                browser.close()
    finally:
        provider.shutdown()
        thread.join(timeout=5)
        provider.server_close()
    print(json.dumps(rows, indent=2))
    assert rows and all(row["status"] == "passed" for row in rows)


if __name__ == "__main__":
    run()
