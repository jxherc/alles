"""Reviewed Aide edits preserve concurrent Docs changes and support exact restoration.

The model is a controlled loopback provider. Approval, tools, persistence, run
history and Docs restoration use the real application and disposable owner data.
"""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api


class DocumentModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests = []

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
        messages = request.get("messages") or []
        text = "\n".join(
            str(message.get("content", "")) for message in messages if message.get("role") == "user"
        )
        found = re.search(r"fixture-(?:1440|390)-(?:accepted|conflict|denied)\.md", text)
        results = [message for message in messages if message.get("role") == "tool"]
        call = None
        content = "fixture ready"
        if found and request.get("tools"):
            path = found.group()
            if not results:
                call = ("docs_read", {"path": path})
            elif len(results) == 1:
                output = str(results[0].get("content", ""))
                snapshot, _ = json.JSONDecoder().raw_decode(output[output.index("{") :])
                call = (
                    "docs_write",
                    {
                        "path": path,
                        "content": "accepted source\n",
                        "expected_hash": snapshot["hash"],
                    },
                )
            else:
                outcome = str(results[-1].get("content", ""))
                content = (
                    "document conflict retained"
                    if "document changed" in outcome
                    else "document change denied"
                    if "denied" in outcome.lower()
                    else "document saved"
                )
        self.requests.append(
            {
                "path": found.group() if found else "",
                "tool": call[0] if call else "",
                "result": content,
            }
        )
        if call:
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": f"{call[0]}-{len(results)}",
                                        "type": "function",
                                        "function": {
                                            "name": call[0],
                                            "arguments": json.dumps(call[1]),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"content": content}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def run():
    _require_throwaway_data_root()
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    data = Path(os.environ["ALLES_DATA"]).resolve()
    records = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), DocumentModelHandler)
    provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        api("POST", "/api/setup/dismiss", {})
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned document fixture",
                "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["document-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint,
                "default_model": "document-fixture",
                "model_roles": {
                    "aide_chat": {"endpoint_id": endpoint, "model": "document-fixture"}
                },
            },
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in (1440, 390):
                    for outcome in ("accepted", "conflict", "denied"):
                        label = f"{width}-{outcome}"
                        path = f"fixture-{label}.md"
                        initial = "owner source\r\n"
                        api("POST", "/api/vault-md/file", {"path": path, "content": initial})
                        context = browser.new_context(
                            viewport={"width": width, "height": 900},
                            is_mobile=width == 390,
                            has_touch=width == 390,
                            reduced_motion="reduce",
                            service_workers="block",
                        )
                        page = context.new_page()
                        page.set_default_timeout(20000)
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on(
                            "console",
                            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
                        )
                        try:
                            page.goto(HOME + "/?app=aide", wait_until="networkidle")
                            page.locator("#perm-mode-btn").click()
                            page.locator('#perm-menu [data-v="approve"]').click()
                            page.locator("#composer-ta").fill(
                                f"use docs_read then docs_write to replace {path} with the reviewed text"
                            )
                            page.locator("#send-btn").click()
                            approval = page.locator(".agent-perm-allow")
                            expect(approval).to_be_visible()
                            diff = page.locator(".agent-step-diff").last
                            expect(diff).to_contain_text("-owner source")
                            expect(diff).to_contain_text("+accepted source")
                            assert (
                                api("GET", "/api/vault-md/file?path=" + path)["content"] == initial
                            )
                            approval.scroll_into_view_if_needed()
                            expect(diff).to_be_in_viewport()
                            page.screenshot(path=str(out / f"{label}-review.png"), full_page=True)
                            if outcome == "conflict":
                                # An external client saves after the owner sees the proposal.
                                current = api("GET", "/api/vault-md/file?path=" + path)
                                api(
                                    "POST",
                                    "/api/vault-md/safety/save",
                                    {
                                        "path": path,
                                        "content": "newer owner source\r\n",
                                        "expected_hash": current["hash"],
                                    },
                                )
                            page.locator(
                                ".agent-perm-deny" if outcome == "denied" else ".agent-perm-allow"
                            ).click()
                            final = (
                                "document conflict retained"
                                if outcome == "conflict"
                                else "document change denied"
                                if outcome == "denied"
                                else "document saved"
                            )
                            expect(page.locator(".ai-body").last).to_contain_text(final)
                            expect(page.locator("#send-btn")).to_be_enabled()
                            expect(page.locator(".agent-revert-btn")).to_have_count(0)
                            saved_url = page.url
                            page.reload(wait_until="networkidle")
                            expect(page.locator(".ai-body").last).to_contain_text(final)
                            expect(page.locator(".agent-revert-btn")).to_have_count(0)
                            read = api("GET", "/api/vault-md/file?path=" + path)
                            expected = (
                                "newer owner source\r\n"
                                if outcome == "conflict"
                                else initial
                                if outcome == "denied"
                                else "accepted source\n"
                            )
                            assert read["content"] == expected, read
                            if outcome == "conflict":
                                conflicts = [
                                    json.loads(p.read_text())
                                    for p in (data / ".document-safety/conflicts").glob(
                                        "*/meta.json"
                                    )
                                ]
                                conflict = next(item for item in conflicts if item["path"] == path)
                                copies = api(
                                    "GET", "/api/vault-md/safety/conflicts/" + conflict["id"]
                                )
                                assert copies["local"] == "accepted source\n"
                                assert copies["external"] == expected
                            page.goto(HOME + "/?app=docs&doc=" + path, wait_until="networkidle")
                            expect(page.locator("#wiki-preview")).to_contain_text(expected.strip())
                            if outcome == "accepted":
                                if not page.locator("#wiki-history-btn").is_visible():
                                    page.locator("#wiki-more-btn").click()
                                page.locator("#wiki-history-btn").click()
                                page.locator("#docs-dialog-body [data-revision]").first.click()
                                page.get_by_role(
                                    "button", name="restore revision", exact=True
                                ).click()
                                expect(page.locator("#wiki-preview")).to_contain_text(
                                    "owner source"
                                )
                                restored = api("GET", "/api/vault-md/file?path=" + path)
                                assert restored["content"] == initial
                                page.reload(wait_until="networkidle")
                                expect(page.locator("#wiki-preview")).to_contain_text(
                                    "owner source"
                                )
                            assert not errors, errors
                            page.screenshot(path=str(out / f"{label}-result.png"), full_page=True)
                            records.append(
                                {
                                    "profile": label,
                                    "status": "passed",
                                    "conversation": saved_url,
                                    "result": "reviewed edit, version outcome, conversation reload, document reopen and applicable revision restore",
                                }
                            )
                        finally:
                            page.screenshot(path=str(out / f"{label}-final.png"), full_page=True)
                            context.close()
                            (out / "scenarios.json").write_text(json.dumps(records, indent=2))
            finally:
                browser.close()
    finally:
        provider.shutdown()
        thread.join(timeout=5)
        provider.server_close()
        (out / "provider-requests.json").write_text(
            json.dumps(DocumentModelHandler.requests, indent=2)
        )
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    run()
