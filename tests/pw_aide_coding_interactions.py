"""Rendered coding responses with synthetic SSE and protocol-validated answers."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402
from services.coding_backends.dsh import _answer_result  # noqa: E402

BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])

SSE = """
window.__codingSources = [];
window.EventSource = class extends EventTarget {
  constructor(url) {
    super(); this.url = url; this.readyState = 0;
    window.__codingSources.push(this);
    setTimeout(() => this.reopen(), 0);
  }
  reopen() { this.readyState = 1; this.onopen?.(new Event('open')); }
  emit(frame) { this.onmessage?.(new MessageEvent('message', {data: JSON.stringify(frame)})); }
  disconnect() { this.readyState = 0; this.onerror?.(new Event('error')); }
  close() { this.readyState = 2; }
};
"""


def frame(kind, rpc_id, **payload):
    return {
        "type": "server-request",
        "rpcId": rpc_id,
        "method": kind,
        "payload": {"type": kind, "sessionId": "synthetic-session", **payload},
    }


def run(browser, width, theme):
    context = browser.new_context(
        viewport={"width": width, "height": 900 if width > 390 else 844},
        has_touch=width == 390,
        reduced_motion="reduce",
        color_scheme=theme,
        service_workers="block",
    )
    context.add_init_script(SSE)
    events = {"errors": [], "external": [], "responses": []}
    pending = {}
    receipt = {"accepted": True}
    saved_run = {
        "id": "synthetic-run",
        "provider_session_id": "synthetic-session",
        "prompt": "check the coding interaction",
        "state": "running",
        "terminal": False,
        "workspace_path": "/synthetic/workspace",
        "created_at": "2026-10-16T12:00:00Z",
        "updated_at": "2026-10-16T12:01:00Z",
    }
    history = [
        {
            "type": "tool/call",
            "call_id": "call-test",
            "summary": "test command",
            "arguments": '{"command":"python -m unittest tests.test_example"}',
        }
    ]

    def boundary(route):
        request, url = route.request, urlsplit(route.request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(request.url)
            return route.abort()
        prefix = "/api/aide/coding/"
        if not url.path.startswith(prefix):
            return route.continue_()
        path = url.path.removeprefix(prefix)
        if path == "status":
            return route.fulfill(json={"configured": True, "available": True})
        if path == "workspaces":
            return route.fulfill(
                json={"items": [{"workspace_id": "synthetic", "title": "test project"}]}
            )
        if path == "runs":
            return route.fulfill(json={"items": [saved_run]})
        if path.endswith("/events"):
            return route.fulfill(json={"items": [], "remote_events": history})
        if path.endswith("/refresh"):
            return route.fulfill(json={**saved_run, "remote_events": history})
        if path.endswith("/respond"):
            body = request.post_data_json
            rpc_id = body.pop("rpc_id")
            result = _answer_result(pending[rpc_id], **body)
            events["responses"].append({"rpc_id": rpc_id, **body, "result": result})
            return route.fulfill(json=receipt)
        raise AssertionError(f"unexpected coding route: {path}")

    context.route("**/*", boundary)
    page = context.new_page()
    page.on("pageerror", lambda error: events["errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["errors"].append(message.text) if message.type == "error" else None,
    )
    label = f"{width}-{theme}"

    def emit(item):
        if item["method"].endswith("/requested"):
            pending[item["rpcId"]] = item
        page.evaluate("frame => window.__codingSources.at(-1).emit(frame)", item)

    target = page.locator("#aide-coding-pending")
    try:
        assert context.request.post(BASE + "/api/setup/dismiss").ok
        assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.locator("#aide-mode-coding").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#aide-coding-live-status")).to_have_text("live DSH activity")
        assert page.evaluate("window.__codingSources.at(-1).url") == (
            "/api/aide/coding/runs/synthetic-run/live"
        )
        approval = frame(
            "approval/requested",
            "approval-rpc",
            approvalId="approval-id",
            toolName="bash",
            callId="call-test",
            reason="run tests <script>unsafe()</script>",
        )
        emit(approval)
        expect(target).to_contain_text(approval["payload"]["reason"])
        expect(target.locator("script")).to_have_count(0)
        expect(target.locator("pre")).to_contain_text("python -m unittest")
        page.screenshot(path=str(OUT / f"approval-{label}.png"))
        target.get_by_role("button", name="allow once", exact=True).focus()
        page.keyboard.press("Enter")
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["outcome"] == "allowed-once"
        emit({**approval, "rpcId": "reject-rpc"})
        target.get_by_role("button", name="reject", exact=True).click()
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["outcome"] == "rejected"

        emit(
            {
                **approval,
                "rpcId": "details-rpc",
                "payload": {**approval["payload"], "callId": "call-waiting"},
            }
        )
        expect(target.get_by_role("button", name="allow once", exact=True)).to_be_disabled()
        expect(target.get_by_role("button", name="reject", exact=True)).to_be_enabled()
        expect(target).to_contain_text("waiting for tool details")
        history.append(
            {
                "type": "tool/call",
                "call_id": "call-waiting",
                "arguments": '{"command":"synthetic inspected command"}',
            }
        )
        page.locator('#aide-coding-run-actions [data-run-action="refresh"]').click()
        expect(target.locator("pre")).to_contain_text("synthetic inspected command")
        expect(target.get_by_role("button", name="allow once", exact=True)).to_be_enabled()
        target.get_by_role("button", name="reject", exact=True).click()
        expect(target.locator("form")).to_have_count(0)

        question = frame(
            "question/requested",
            "question-rpc",
            questions=[
                {
                    "id": "scope",
                    "question": "which change should run?",
                    "options": [{"label": "small"}, {"label": "full"}],
                }
            ],
        )
        emit(question)
        target.get_by_role("button", name="small", exact=True).focus()
        page.keyboard.press("Enter")
        expect(target.get_by_role("button", name="small", exact=True)).to_be_focused()
        expect(target.get_by_role("button", name="small", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        target.get_by_role("button", name="send answer", exact=True).click()
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["answers"] == [{"id": "scope", "selected": ["small"]}]

        emit({**question, "rpcId": "draft-rpc"})
        target.get_by_label("your answer", exact=True).fill("keep this answer")
        page.evaluate("window.__codingSources.at(-1).disconnect()")
        expect(page.locator("#aide-coding-live-status")).to_contain_text("reconnecting")
        expect(target.get_by_label("your answer", exact=True)).to_have_value("keep this answer")
        expect(target.get_by_role("button", name="send answer", exact=True)).to_be_disabled()
        page.screenshot(path=str(OUT / f"question-disconnected-{label}.png"))
        page.evaluate("window.__codingSources.at(-1).reopen()")
        expect(target.locator("form")).to_have_count(0)
        emit({**question, "rpcId": "draft-rpc"})
        expect(target.get_by_label("your answer", exact=True)).to_have_value("keep this answer")
        target.get_by_role("button", name="send answer", exact=True).click()
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["answers"] == [
            {"id": "scope", "selected": [], "custom": "keep this answer"}
        ]

        multi = frame(
            "question/requested",
            "multi-rpc",
            questions=[
                {
                    "id": "checks",
                    "question": "which checks?",
                    "multiSelect": True,
                    "options": [{"label": "unit tests"}, {"label": "browser"}],
                },
                {"id": "detail", "question": "anything else?"},
            ],
        )
        emit(multi)
        target.get_by_role("button", name="unit tests", exact=True).click()
        target.get_by_role("button", name="browser", exact=True).click()
        target.get_by_label("your answer", exact=True).nth(1).fill("include recovery")
        boxes = target.locator("button:visible, textarea:visible").evaluate_all(
            "items => items.map(item => ({width:item.getBoundingClientRect().width,height:item.getBoundingClientRect().height}))"
        )
        assert all(box["width"] >= 44 and box["height"] >= 44 for box in boxes), boxes
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / f"questions-{label}.png"))
        target.get_by_role("button", name="send answer", exact=True).click()
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["answers"] == [
            {"id": "checks", "selected": ["unit tests", "browser"]},
            {"id": "detail", "selected": [], "custom": "include recovery"},
        ]
        emit({**question, "rpcId": "cancel-rpc"})
        target.get_by_role("button", name="cancel question", exact=True).click()
        expect(target.locator("form")).to_have_count(0)
        assert events["responses"][-1]["result"]["error"]["code"] == "cancelled"

        receipt = {"accepted": False, "reason": "not-pending"}
        emit({**question, "rpcId": "resolved-rpc"})
        target.get_by_label("your answer", exact=True).fill("retain after stale receipt")
        target.get_by_role("button", name="send answer", exact=True).click()
        expect(page.locator("#aide-coding-error")).to_contain_text("no longer waiting")
        expect(target.get_by_label("your answer", exact=True)).to_have_value(
            "retain after stale receipt"
        )
        emit(frame("question/resolved", "resolved-event", questionRpcId="resolved-rpc"))
        expect(target.locator("form")).to_have_count(0)
        page.locator("#aide-mode-conversation").click()
        assert page.evaluate("window.__codingSources.at(-1).readyState") == 2
        page.locator("#aide-mode-coding").click()
        page.wait_for_function("window.__codingSources.length === 2")
        expect(page.locator("#aide-coding-live-status")).to_have_text("live DSH activity")
        assert not events["errors"] and not events["external"], events
        return {"profile": label, "status": "passed", "synthetic": True, **events}
    except Exception:
        page.screenshot(path=str(OUT / f"failure-{label}.png"))
        raise
    finally:
        (OUT / f"events-{label}.json").write_text(json.dumps(events, indent=2) + "\n")
        context.close()


if __name__ == "__main__":
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme in [(1440, "dark"), (390, "light")]:
                rows.append(run(browser, width, theme))
        finally:
            browser.close()
            (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
