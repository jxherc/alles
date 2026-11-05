"""Messages sent while aide replies wait their turn, in the real page, in WebKit.

A loopback model streams a long reply slowly. While it runs the gate sends three more messages,
removes one, and checks: each shows at once under the reply, the reply is never cut, the follow
scroll stays at the end, a reload keeps what waits, and the next turn answers what is left as one
question. Stop still stops, and the send and stop buttons share one slot without shifting.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api

sys.path.insert(0, str(Path.cwd()))
from services.appearance import from_legacy  # noqa: E402

SIZES = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
    "ipad-landscape": {"viewport": {"width": 1180, "height": 820}, "has_touch": True},
    "ipad-portrait": {"viewport": {"width": 820, "height": 1180}, "has_touch": True},
    "phone": {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True},
}
SLOW = float(os.environ.get("QUEUE_SLOW_SECONDS", "10"))
PARAGRAPHS = 48


class SlowModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    asked = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        last = (request.get("messages") or [{}])[-1].get("content", "")
        if not request.get("stream"):
            payload = json.dumps({"choices": [{"message": {"content": "queue check"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        SlowModel.asked.append(last)
        slow = str(last).startswith("first")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        count = PARAGRAPHS if slow else 15
        pause = SLOW / PARAGRAPHS if slow else 0.2
        try:
            for n in range(count):
                words = f"got: {last}\n\n" if n == 0 else ""
                words += (
                    f"paragraph {n}: the reply keeps going so the page has something to follow.\n\n"
                )
                chunk = {"choices": [{"delta": {"content": words}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(pause)
            done = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def at_end(page):
    return page.evaluate(
        "(() => { const c = document.getElementById('chat'); return c.scrollHeight - c.scrollTop - c.clientHeight < 80; })()"
    )


def no_sideways_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def run():
    _require_throwaway_data_root()
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS") or tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    only = [s for s in os.environ.get("QUEUE_SIZES", ",".join(SIZES)).split(",") if s]
    engines = os.environ.get("QUEUE_ENGINES", "webkit").split(",")
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = api(
        "POST",
        "/api/models/endpoint",
        {
            "name": "queue fixture",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "provider_adapter": "manual",
        },
    )["id"]
    api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["slow"]})
    api("POST", "/api/setup/dismiss", {})
    api(
        "PATCH",
        "/api/settings",
        {
            "default_endpoint_id": endpoint,
            "default_model": "slow",
            "model_roles": {},
            "memory_policy": "off",
            "memory_auto_inject": False,
            "intent_suggestions": False,
            "auto_compact": False,
        },
    )
    rows = []

    def session(name):
        return api(
            "POST",
            "/api/sessions",
            {"name": name, "model": "slow", "endpoint_id": endpoint, "mode": "chat"},
        )["id"]

    def queued_on_server(sid):
        return [m["message"] for m in api("GET", f"/api/chat/queue/{sid}")["queued"]]

    try:
        with sync_playwright() as pw:
            for engine in engines:
                browser = getattr(pw, engine).launch()
                for size in only:
                    for theme in ("dark", "light"):
                        profile = f"{engine}-{size}-{theme}"
                        record = {"profile": profile, "status": "failed"}
                        rows.append(record)
                        api("PUT", "/api/appearance", from_legacy(theme, None))
                        context = browser.new_context(service_workers="block", **SIZES[size])
                        errors = []
                        reloading = False
                        step = ["start"]
                        page = context.new_page()
                        page.set_default_timeout(15000)
                        page.on(
                            "pageerror",
                            lambda e: (
                                errors.append(f"{step[0]}: {e}")
                                if not (reloading and "access control checks" in str(e))
                                else None
                            ),
                        )
                        page.on(
                            "console",
                            lambda m: (
                                errors.append(f"{step[0]}: {m.text}")
                                if m.type == "error"
                                and not (reloading and "access control checks" in m.text)
                                else None
                            ),
                        )

                        def open_task(sid):
                            # a changed hash alone is not a new page load
                            page.goto("about:blank")
                            page.goto(f"{HOME}/?view=chat#{sid}", wait_until="networkidle")
                            shown = page.evaluate(
                                "document.documentElement.dataset.theme || 'dark'"
                            )
                            assert shown == theme, (shown, theme)

                        def send(words):
                            page.locator("#composer-ta").fill(words)
                            page.keyboard.press("Enter")

                        def shot(name):
                            page.screenshot(path=str(out / f"{profile}-{name}.png"))

                        try:
                            # 1. three messages during one reply, one removed
                            SlowModel.asked.clear()
                            sid = session(f"{profile} flow")
                            open_task(sid)
                            send("first question")
                            expect(page.locator("#stop-btn")).to_be_visible()
                            expect(page.locator("#messages .ai-content").first).to_contain_text(
                                "got: first question"
                            )
                            before = page.locator("#messages .ai-content").first.inner_text()
                            for words in ("second", "third", "fourth"):
                                send(words)
                                expect(
                                    page.locator(
                                        f'#messages [data-queued] .user-bubble:text-is("{words}")'
                                    )
                                ).to_be_visible()
                            queued = page.locator("#messages [data-queued]")
                            expect(queued).to_have_count(3)
                            assert page.locator("#composer-ta").input_value() == ""
                            assert queued_on_server(sid) == ["second", "third", "fourth"]
                            order = page.evaluate(
                                "[...document.querySelectorAll('#messages > .msg-row')].map(r => r.dataset.queued ? 'queued' : r.querySelector('.user-bubble') ? 'user' : 'ai')"
                            )
                            assert order == ["user", "ai", "queued", "queued", "queued"], order
                            # the reply was not cut
                            page.wait_for_timeout(800)
                            assert len(
                                page.locator("#messages .ai-content").first.inner_text()
                            ) > len(before)
                            expect(page.locator("#stop-btn")).to_be_visible()
                            assert at_end(page), "follow the reply broke with queued messages"
                            assert no_sideways_scroll(page)
                            # remove button: 44px target, keyboard focus, hover
                            third = page.locator(
                                '#messages [data-queued] .user-bubble:text-is("third")'
                            ).locator("xpath=ancestor::*[@data-queued]")
                            remove = third.locator(".msg-unqueue-btn")
                            box = remove.bounding_box()
                            assert box["height"] >= 44 and box["width"] >= 44, box
                            gaps = page.evaluate(
                                "(() => { const r = [...document.querySelectorAll('#messages [data-queued]')].map(e => e.getBoundingClientRect()); return r.slice(1).map((b, i) => Math.round(b.top - r[i].bottom)); })()"
                            )
                            assert all(g >= 0 for g in gaps), gaps
                            shot("queued")
                            touch = SIZES[size].get("has_touch")
                            if not touch:
                                remove.hover()
                                shot("remove-hover")
                            remove.focus()
                            ring = remove.evaluate(
                                "el => [el.matches(':focus-visible'), getComputedStyle(el, '::before').borderTopWidth, getComputedStyle(el, '::before').borderTopColor]"
                            )
                            if not touch:
                                assert ring[0] and ring[1] == "1px", ring
                            shot("remove-focus")
                            # removed from the keyboard: focus goes back to the box
                            page.keyboard.press("Enter")
                            expect(queued).to_have_count(2)
                            assert page.evaluate("document.activeElement.id") == "composer-ta"
                            assert queued_on_server(sid) == ["second", "fourth"]
                            # 2. the reply ends, then the rest is answered together as one question
                            expect(page.locator("#messages .ai-content").nth(1)).to_contain_text(
                                "got: second", timeout=int(SLOW * 1500)
                            )
                            second = page.locator("#messages .ai-content").nth(1)
                            expect(second).to_contain_text("fourth")
                            assert "third" not in second.inner_text()
                            expect(page.locator("#messages [data-queued]")).to_have_count(0)
                            expect(page.locator("#stop-btn")).to_be_hidden(timeout=15000)
                            first_text = page.locator("#messages .ai-content").first.inner_text()
                            assert f"paragraph {PARAGRAPHS - 1}" in first_text, (
                                "the first reply was cut off"
                            )
                            assert queued_on_server(sid) == []
                            shot("answered")
                            history = api("GET", f"/api/sessions/{sid}/history")
                            roles = [m["role"] for m in history["messages"]]
                            assert roles == ["user", "assistant", "user", "assistant"], roles
                            assert history["messages"][2]["content"] == "second\n\nfourth"
                            assert not history["messages"][1]["meta"].get("interrupted")
                            assert SlowModel.asked[-1].endswith("second\n\nfourth"), SlowModel.asked
                            record["flow"] = "ok"

                            step[0] = "reload scenario"
                            # 3. reload in the middle of the queue: nothing is lost
                            SlowModel.asked.clear()
                            sid = session(f"{profile} reload")
                            open_task(sid)
                            send("first again")
                            expect(page.locator("#messages .ai-content").first).to_contain_text(
                                "got: first again"
                            )
                            send("after reload one")
                            send("after reload two")
                            expect(page.locator("#messages [data-queued]")).to_have_count(2)
                            assert queued_on_server(sid) == ["after reload one", "after reload two"]
                            # hold the page's check of the queue back so the restored rows can be seen
                            held = []
                            page.route("**/api/chat/queue/*", lambda route: held.append(route))
                            # a reload cuts the running reply's requests; the browser logs those
                            reloading = True
                            step[0] = "reload"
                            page.reload(wait_until="domcontentloaded")
                            expect(page.locator("#messages [data-queued]")).to_have_count(
                                2, timeout=20000
                            )
                            shown = [
                                t.strip()
                                for t in page.locator(
                                    "#messages [data-queued] .user-bubble"
                                ).all_text_contents()
                            ]
                            assert shown == ["after reload one", "after reload two"], shown
                            shot("after-reload")
                            for route in held:
                                route.continue_()
                            expect(page.locator("#messages .ai-content").last).to_contain_text(
                                "got: after reload one", timeout=30000
                            )
                            reloading = False
                            tail = page.locator("#messages .ai-content").last.inner_text()
                            assert "after reload two" in tail, tail
                            page.unroute("**/api/chat/queue/*")
                            expect(page.locator("#stop-btn")).to_be_hidden(timeout=15000)
                            assert queued_on_server(sid) == []
                            history = api("GET", f"/api/sessions/{sid}/history")
                            assert [
                                m["content"] for m in history["messages"] if m["role"] == "user"
                            ] == ["first again", "after reload one\n\nafter reload two"]
                            record["reload"] = "ok"

                            step[0] = "stop scenario"
                            # 4. the stop button and the send button share one slot
                            if size == "desktop" and theme == "dark":
                                sid = session(f"{profile} stop")
                                open_task(sid)
                                mic = (
                                    page.locator("#composer-ta")
                                    .locator("xpath=ancestor::*[contains(@class,'composer-box')]")
                                    .locator(".c-tool")
                                    .last
                                )
                                send("first stop me")
                                expect(page.locator("#stop-btn")).to_be_visible()
                                expect(page.locator("#send-btn")).to_be_hidden()
                                slot = page.locator("#stop-btn").bounding_box()
                                tool_before = mic.bounding_box()
                                page.locator("#composer-ta").fill("one waiting")
                                expect(page.locator("#send-btn")).to_be_visible()
                                expect(page.locator("#stop-btn")).to_be_hidden()
                                swapped = page.locator("#send-btn").bounding_box()
                                assert (
                                    abs(swapped["x"] - slot["x"]) < 1
                                    and abs(swapped["y"] - slot["y"]) < 1
                                ), (slot, swapped)
                                assert mic.bounding_box() == tool_before, (
                                    "the tools beside send moved"
                                )
                                page.keyboard.press("Enter")
                                expect(page.locator("#messages [data-queued]")).to_have_count(1)
                                expect(page.locator("#stop-btn")).to_be_visible()
                                page.locator("#stop-btn").click()
                                expect(page.locator("#messages .ai-content").last).to_contain_text(
                                    "got: one waiting", timeout=20000
                                )
                                # a message sent during that answer is answered after it
                                send("after the answer")
                                expect(page.locator("#messages .ai-content").last).to_contain_text(
                                    "got: after the answer", timeout=20000
                                )
                                expect(page.locator("#stop-btn")).to_be_hidden(timeout=15000)
                                history = api("GET", f"/api/sessions/{sid}/history")
                                assert history["messages"][1]["meta"].get("interrupted"), (
                                    "stop did not stop the first reply"
                                )
                                assert queued_on_server(sid) == []
                                record["stop"] = "ok"
                            assert not errors, errors
                            record["status"] = "passed"
                        except Exception as exc:
                            where = traceback.extract_tb(exc.__traceback__)[-1].lineno
                            record["error"] = f"line {where} {type(exc).__name__}: {exc}"[:900]
                            try:
                                page.screenshot(path=str(out / f"{profile}-failed.png"))
                            except Exception:
                                pass
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
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=1))
    shutil.rmtree(out / "tmp", ignore_errors=True)
    if any(r["status"] != "passed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
