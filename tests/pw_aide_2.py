"""ui-2a/2b/2c behavioral — mock models/sessions/rag/research so we can drive aide without a real
provider. Proves: docs-ask & research SEND on a fresh session (2a), each answer lands in its OWN box
(2b), and research shows a warming state then a report (2c). Run with the server on :8870."""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://aide.localhost:8870"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "ui-2"
IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    errs, r = [], {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        # block the service worker so page.route actually intercepts /api/* (the SW would
        # otherwise re-issue the requests and bypass the mocks)
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGN)
                else None
            ),
        )

        # a fake configured endpoint so ensureSession() can make a session
        pg.route(
            "**/api/models",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    [
                        {
                            "id": "e1",
                            "name": "test",
                            "provider": "openai",
                            "models": ["m1"],
                            "cached_models": ["m1"],
                            "enabled": True,
                        }
                    ]
                ),
            ),
        )

        # POST → a new session; GET → the grouped shape loadSessions expects
        def sessions_route(route):
            if route.request.method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"id": "s1", "name": "new"}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"today": [], "yesterday": [], "earlier": []}),
                )

        pg.route("**/api/sessions", sessions_route)

        # rag returns a different answer each call so we can tell the boxes apart
        n = {"i": 0}

        def rag(route):
            n["i"] += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"answer": f"ANSWER {n['i']}", "sources": ["notes/a.md"]}),
            )

        pg.route("**/api/rag/ask", rag)

        # research: a complete SSE body (reader consumes it in one pass)
        sse = (
            'data: {"type":"step","text":"searching the web"}\n\n'
            'data: {"type":"done","report":"# Findings\\nthe answer","sources":[]}\n\n'
            "data: [DONE]\n\n"
        )
        pg.route(
            "**/api/research",
            lambda route: (
                route.fulfill(status=200, content_type="text/event-stream", body=sse)
                if route.request.method == "POST"
                else route.continue_()
            ),
        )

        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#composer-ta", timeout=15000)
        # wait until models have loaded + an endpoint is selected (async on boot)
        pg.wait_for_function("() => (window._endpoints||[]).length > 0", timeout=10000)
        pg.wait_for_timeout(400)

        def send(text):
            pg.fill("#composer-ta", text)
            pg.focus("#composer-ta")
            pg.keyboard.press("Enter")

        # ── docs-ask: two questions on a fresh chat ───────────────────────────
        pg.eval_on_selector("#docs-toggle-btn", "el => el.click()")
        send("first question")
        pg.wait_for_selector(".rag-ans", state="attached", timeout=8000)
        pg.wait_for_timeout(500)
        send("second question")
        pg.wait_for_timeout(1000)

        boxes = pg.eval_on_selector_all(".rag-ans", "els => els.map(e => e.textContent.trim())")
        r["docs_sent_on_fresh_session"] = len(boxes) >= 1  # 2a
        r["docs_two_separate_boxes"] = len(boxes) == 2  # 2b
        r["docs_first_box_keeps_first_answer"] = boxes and "ANSWER 1" in boxes[0]
        r["docs_second_box_has_second_answer"] = len(boxes) == 2 and "ANSWER 2" in boxes[1]
        pg.screenshot(path=str(EVID / "docs-two-answers.png"))

        # ── research: fresh run renders a report (not blank) ──────────────────
        pg.eval_on_selector("#docs-toggle-btn", "el => el.click()")  # turn docs off
        pg.eval_on_selector("#research-toggle-btn", "el => el.click()")
        send("what is rust")
        pg.wait_for_selector(".rs-report", state="attached", timeout=8000)
        pg.wait_for_timeout(700)
        report = pg.eval_on_selector(".rs-report", "e => e.textContent") or ""
        r["research_sent_on_fresh_session"] = True
        r["research_report_not_blank"] = "answer" in report.lower() or "findings" in report.lower()
        pg.screenshot(path=str(EVID / "research-report.png"))
        pg.close()
        b.close()

    r["zero_console_errors"] = len(errs) == 0
    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"errors: {errs[:5]}")
    print("\n".join(lines))
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
