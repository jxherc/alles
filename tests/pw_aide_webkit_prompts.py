"""Owner prompts reach the page in WebKit (Safari, iPad) as well as Chromium.

WebKit hands a page only the first server-sent event of a network packet until the next packet
arrives, so an approval or a question sent just before the turn waits used to never show there.
This drives the real page against an owned server and a loopback model: an approval inside the
folder, one outside it (with its resolved path), a question in the reply, and a background run's
question, on desktop and an iPad-sized touch screen.
"""

import json
import os
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

OUTSIDE = {"path": ""}
QUESTION = {
    "title": "pick one",
    "questions": [
        {
            "id": "color",
            "prompt": "which colour?",
            "choices": [{"id": "red", "label": "red"}, {"id": "blue", "label": "blue"}],
        }
    ],
}


def _tool_call(name, args):
    return [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]


def _text(words):
    return [
        {"choices": [{"delta": {"content": words}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


class PromptModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        model = request.get("model", "")
        answered = any(m.get("role") == "tool" for m in request.get("messages") or [])
        if not request.get("stream"):
            payload = json.dumps({"choices": [{"message": {"content": "prompt check"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if answered:
            chunks = _text(f"{model} answered")
        elif model == "inside":
            chunks = _tool_call("write_file", {"path": "inside.txt", "content": "ok"})
        elif model == "outside":
            chunks = _tool_call("write_file", {"path": OUTSIDE["path"], "content": "no"})
        else:
            chunks = _tool_call("ask_user", QUESTION)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _no_sideways_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def run():
    _require_throwaway_data_root()
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS") or tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="alles-webkit-prompts-")).resolve()
    folder, outside = work / "task", work / "elsewhere"
    folder.mkdir()
    outside.mkdir()
    OUTSIDE["path"] = str(outside / "not-written.txt")
    server = ThreadingHTTPServer(("127.0.0.1", 0), PromptModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = api(
        "POST",
        "/api/models/endpoint",
        {
            "name": "prompt fixture",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "provider_adapter": "manual",
        },
    )["id"]
    api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["inside", "outside", "ask"]})
    api("POST", "/api/setup/dismiss", {})

    def session(model, name, **extra):
        body = {"name": name, "model": model, "endpoint_id": endpoint, "mode": "agent"}
        return api("POST", "/api/sessions", {**body, "working_dir": str(folder), **extra})["id"]

    rows = []
    try:
        with sync_playwright() as pw:
            for engine in ("webkit", "chromium"):
                browser = getattr(pw, engine).launch()
                for label, options in (
                    ("desktop", {"viewport": {"width": 1440, "height": 900}}),
                    ("ipad", {"viewport": {"width": 820, "height": 1180}, "has_touch": True}),
                ):
                    profile = f"{engine}-{label}"
                    record = {"profile": profile, "status": "failed"}
                    rows.append(record)
                    context = browser.new_context(
                        service_workers="block", reduced_motion="reduce", **options
                    )
                    context.add_init_script("localStorage.setItem('aide-perm-mode', 'approve')")
                    errors = []
                    page = None
                    press = (
                        (lambda loc: loc.tap())
                        if options.get("has_touch")
                        else (lambda loc: loc.click())
                    )

                    def fresh(sid, context=context, errors=errors):
                        # a new tab per task, the way the owner opens one
                        for old in context.pages:
                            old.close()
                        tab = context.new_page()
                        tab.set_default_timeout(8000)
                        tab.on("pageerror", lambda e: errors.append(str(e)))
                        tab.on(
                            "console",
                            lambda m: errors.append(m.text) if m.type == "error" else None,
                        )
                        tab.goto(f"{HOME}/?view=chat#{sid}", wait_until="networkidle")
                        return tab

                    def send(sid, words="go", fresh=fresh):
                        tab = fresh(sid)
                        tab.locator("#composer-ta").fill(words)
                        tab.keyboard.press("Enter")
                        return tab

                    try:
                        # an approval inside the folder: the card shows while the turn waits
                        page = send(session("inside", f"{profile} inside"))
                        started = time.monotonic()
                        expect(page.locator(".agent-perm")).to_be_visible(timeout=5000)
                        record["inside_card_seconds"] = round(time.monotonic() - started, 2)
                        assert _no_sideways_scroll(page)
                        page.screenshot(path=str(out / f"{profile}-inside.png"))
                        press(page.locator(".agent-perm-allow"))
                        expect(page.locator("#messages .ai-content").last).to_contain_text(
                            "inside answered", timeout=10000
                        )
                        assert (folder / "inside.txt").read_text() == "ok"
                        (folder / "inside.txt").unlink()

                        # an approval outside it names the resolved path; a no writes nothing
                        page = send(session("outside", f"{profile} outside"))
                        card = page.locator(".agent-perm-outside")
                        expect(card).to_have_text(
                            f"writes outside this task's folder: {OUTSIDE['path']}", timeout=5000
                        )
                        assert card.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
                        assert _no_sideways_scroll(page)
                        page.screenshot(path=str(out / f"{profile}-outside.png"))
                        press(page.locator(".agent-perm-deny"))
                        expect(page.locator("#messages .ai-content").last).to_contain_text(
                            "outside answered", timeout=10000
                        )
                        assert not Path(OUTSIDE["path"]).exists()

                        # a question in the reply
                        page = send(session("ask", f"{profile} question"))
                        question = page.locator(".aide-question-card").last
                        expect(question).to_be_visible(timeout=5000)
                        press(question.locator('[data-choice-id="blue"]'))
                        press(question.locator(".aide-question-submit"))
                        expect(page.locator("#messages .ai-content").last).to_contain_text(
                            "ask answered", timeout=10000
                        )

                        # a background run's question, which the page reads by polling
                        sid = session("ask", f"{profile} background")
                        api(
                            "POST",
                            "/api/agent/background",
                            {"session_id": sid, "message": "ask me", "mode": "agent"},
                        )
                        page = fresh(sid)
                        expect(page.locator(".bg-reattach .aide-question-card")).to_be_visible(
                            timeout=10000
                        )
                        assert _no_sideways_scroll(page)
                        page.screenshot(path=str(out / f"{profile}-background.png"))
                        assert not errors, errors
                        record["status"] = "passed"
                    except Exception as exc:
                        record["error"] = f"{type(exc).__name__}: {exc}"[:800]
                        if page is not None:
                            page.screenshot(path=str(out / f"{profile}-failed.png"))
                    finally:
                        context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        try:
            api("DELETE", f"/api/models/endpoint/{endpoint}")
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=1))
    if any(r["status"] != "passed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
