"""Aide question input/recovery against an owned server and a loopback provider.

The provider and one rejected answer POST are simulated. Answers, cancellation,
run history and reload use real local APIs. No live model or Discord is certified.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from pw_aide_questions_real import (  # noqa: E402
    HOME,
    QuestionModelHandler,
    _require_throwaway_data_root,
    api,
)

from services.appearance import from_legacy  # noqa: E402

SIMULATION = "loopback question provider and one HTTP 503; real local answers and run history"
CONTROLS = {
    "choice": "dynamic.f8b6a09b1910",
    "text": "dynamic.100541e5fdf1",
    "cancel": "dynamic.f0fc7bba2ed2",
    "continue": "dynamic.2ed229150bb8",
}
ANSWER = {
    "cancelled": False,
    "answers": {
        "surface": {"selected": ["aide"], "free_text": "Keep this answer 中文"},
        "proof": {"selected": ["desktop", "phone"], "free_text": ""},
    },
}


def footer_geometry(card):
    result = card.locator(".aide-question-footer").evaluate("""e => ({
      width: innerWidth, height: innerHeight,
      documentWidth: document.documentElement.scrollWidth,
      controls: [...e.querySelectorAll('button')].map(x => {
        const r = x.getBoundingClientRect();
        return {text:x.textContent, width:x.clientWidth, contentWidth:x.scrollWidth,
          rect:r.toJSON(), reachable:[[.1,.1],[.9,.1],[.5,.5],[.1,.9],[.9,.9]]
            .every(([a,b]) => x.contains(document.elementFromPoint(r.x+r.width*a,r.y+r.height*b)))};
      })
    })""")
    assert result["documentWidth"] <= result["width"], result
    for control in result["controls"]:
        rect = control["rect"]
        assert control["contentWidth"] <= control["width"], result
        assert rect["width"] >= 44 and rect["height"] >= 44, result
        assert 0 <= rect["left"] < rect["right"] <= result["width"], result
        assert 0 <= rect["top"] < rect["bottom"] <= result["height"], result
        assert control["reachable"], result
    return result


def run_profile(browser, endpoint, output, records, controls, width, theme):
    profile = "phone" if width < 700 else "desktop"
    label = f"{width}-{theme}"
    directory = output / label
    directory.mkdir()
    context = browser.new_context(
        viewport={"width": width, "height": 900},
        is_mobile=profile == "phone",
        has_touch=profile == "phone",
        reduced_motion="reduce",
        service_workers="block",
        locale="en-US",
        timezone_id="UTC",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(15000)
    events = {
        "console": [],
        "pageerror": [],
        "failed": [],
        "http": [],
        "answers": [],
        "outbound": [],
    }
    page.on("console", lambda m: events["console"].append({"type": m.type, "text": m.text}))
    page.on("pageerror", lambda e: events["pageerror"].append(str(e)))
    page.on("requestfailed", lambda r: events["failed"].append({"url": r.url, "error": r.failure}))
    page.on(
        "response",
        lambda r: (
            events["http"].append({"url": r.url, "status": r.status}) if r.status >= 400 else None
        ),
    )

    def request_seen(request):
        url = urlsplit(request.url)
        if url.scheme in {"http", "https"} and url.hostname != "127.0.0.1":
            events["outbound"].append(request.url)
        if url.path.startswith("/api/agent/questions/") and request.method == "POST":
            events["answers"].append({"url": request.url, "body": request.post_data_json})

    page.on("request", request_seen)
    answer_row = {
        "scenario_id": "aide.question-answer-recovery",
        "profile": profile,
        "width": width,
        "theme": theme,
        "status": "failed",
        "simulation": SIMULATION,
    }
    cancel_row = {**answer_row, "scenario_id": "aide.question-cancel", "status": "untested"}
    records.extend([answer_row, cancel_row])
    card = page.locator(".bg-reattach .aide-question-card")

    def close_history():
        backdrop = page.locator("#nav-backdrop")
        if profile == "phone" and backdrop.is_visible():
            rect = backdrop.bounding_box()
            backdrop.tap(position={"x": rect["width"] - 12, "y": 200})
            expect(backdrop).to_be_hidden()

    def reload():
        page.reload(wait_until="domcontentloaded")
        assert_theme()

    def assert_theme():
        page.wait_for_function(
            "theme => (document.documentElement.dataset.theme || 'dark') === theme", arg=theme
        )

    def begin_question(kind):
        session = api(
            "POST",
            "/api/sessions",
            {
                "name": f"{label}-{kind}",
                "mode": "jarvis",
                "endpoint_id": endpoint,
                "model": "question-model",
            },
        )
        api(
            "POST",
            "/api/agent/background",
            {
                "session_id": session["id"],
                "message": "ask me for the verification scope",
                "mode": "agent",
            },
        )
        page.goto(f"{HOME}/?app=aide#{session['id']}", wait_until="domcontentloaded")
        expect(card).to_be_visible()
        assert_theme()
        close_history()
        return session["id"]

    def saved_answer(session_id, expected):
        runs = api("GET", "/api/agent/runs?limit=50")
        run = next(r for r in runs if r.get("session_id") == session_id)
        resolved = [e for e in run["events"] if e["type"] == "user_question_resolved"]
        assert len(resolved) == 1 and resolved[0]["data"]["answer"] == expected, run
        assert run["pending_question"] is None, run
        return resolved[0]

    try:
        api("PUT", "/api/appearance", from_legacy(theme, None))
        session_id = begin_question("answer")
        request_id = card.get_attribute("data-aide-question-request")
        reload()
        expect(card).to_have_attribute("data-aide-question-request", request_id)
        close_history()
        expect(card.locator(".aide-question-submit")).to_be_disabled()
        assert card.locator("input[type=radio],input[type=checkbox],select").count() == 0
        if profile == "desktop":
            expect(card.locator('[data-choice-id="files"]')).to_be_focused()
            page.keyboard.press("ArrowDown")
            expect(card.locator('[data-choice-id="aide"]')).to_be_focused()
            page.keyboard.press("Enter")
            page.keyboard.press("Tab")
            expect(card.locator("textarea")).to_be_focused()
            page.keyboard.insert_text(ANSWER["answers"]["surface"]["free_text"])
            page.keyboard.press("Tab")
            expect(card.locator('[data-choice-id="desktop"]')).to_be_focused()
            page.keyboard.press("Space")
            page.keyboard.press("Tab")
            expect(card.locator('[data-choice-id="phone"]')).to_be_focused()
            page.keyboard.press("Space")
        else:
            card.locator('[data-choice-id="aide"]').tap()
            card.locator("textarea").fill(ANSWER["answers"]["surface"]["free_text"])
            card.locator('[data-choice-id="desktop"]').tap()
            card.locator('[data-choice-id="phone"]').tap()
        for choice in ("aide", "desktop", "phone"):
            expect(card.locator(f'[data-choice-id="{choice}"]')).to_have_attribute(
                "aria-checked", "true"
            )
        answer_row["targets"] = card.locator("button, textarea").evaluate_all(
            "nodes => nodes.map(e => ({name:e.textContent, rect:e.getBoundingClientRect().toJSON()}))"
        )
        assert all(
            item["rect"]["width"] >= 44 and item["rect"]["height"] >= 44
            for item in answer_row["targets"]
        ), answer_row["targets"]
        answer_url = f"{HOME}/api/agent/questions/{request_id}/answer"
        page.route(
            answer_url,
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"simulated save failure"}',
            ),
            times=1,
        )
        if profile == "desktop":
            for _ in range(3):
                page.keyboard.press("Tab")
            expect(card.locator(".aide-question-submit")).to_be_focused()
            page.keyboard.press("Enter")
        else:
            card.locator(".aide-question-submit").tap()
        expect(card.locator("[data-question-status]")).to_have_text("could not save - try again")
        expect(card.locator("textarea")).to_have_value(ANSWER["answers"]["surface"]["free_text"])
        page.screenshot(path=str(directory / "failed-save-retained.png"))
        answer_row["geometry"] = footer_geometry(card)
        if profile == "desktop":
            # Disabling the saving button blurs it; traverse the recovery actions.
            page.keyboard.press("Shift+Tab")
            expect(card.locator(".aide-question-cancel")).to_be_focused()
            page.keyboard.press("Tab")
            expect(card.locator(".aide-question-submit")).to_be_focused()
            page.keyboard.press("Enter")
        else:
            card.locator(".aide-question-submit").tap()
        expect(page.locator("#messages")).to_contain_text("question answer received", timeout=30000)
        reload()
        expect(page.locator("#messages")).to_contain_text("question answer received")
        close_history()
        expect(page.locator(".aide-question-card:not(.answered):not(.cancelled)")).to_have_count(0)
        answer_row["saved"] = saved_answer(session_id, ANSWER)
        page.screenshot(path=str(directory / "answer-reloaded.png"))
        answer_row["status"] = "passed"

        cancel_row["status"] = "failed"
        cancel_session = begin_question("cancel")
        cancel_id = card.get_attribute("data-aide-question-request")
        if profile == "desktop":
            expect(card.locator('[data-choice-id="files"]')).to_be_focused()
            for selector in (
                '[data-choice-id="aide"]',
                "textarea",
                '[data-choice-id="desktop"]',
                '[data-choice-id="phone"]',
                '[data-choice-id="keyboard"]',
                ".aide-question-cancel",
            ):
                page.keyboard.press("Tab")
                expect(card.locator(selector)).to_be_focused()
            page.keyboard.press("Enter")
        else:
            card.locator(".aide-question-cancel").tap()
        expect(page.locator("#messages")).to_contain_text("question answer received", timeout=30000)
        reload()
        expect(page.locator("#messages")).to_contain_text("question answer received")
        close_history()
        expect(page.locator(".aide-question-card:not(.answered):not(.cancelled)")).to_have_count(0)
        cancel_row["saved"] = saved_answer(cancel_session, {"cancelled": True, "answers": {}})
        assert events["answers"] == [
            {"url": answer_url, "body": ANSWER},
            {"url": answer_url, "body": ANSWER},
            {
                "url": f"{HOME}/api/agent/questions/{cancel_id}/answer",
                "body": {"cancelled": True, "answers": {}},
            },
        ], events["answers"]
        assert events["http"] == [{"url": answer_url, "status": 503}], events
        assert not events["pageerror"] and not events["failed"] and not events["outbound"], events
        assert Counter((e["type"], e["text"]) for e in events["console"]) == Counter(
            {
                ("warning", "Service Worker registration blocked by Playwright"): 10,
                (
                    "error",
                    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                ): 1,
            }
        ), events["console"]
        cancel_row["status"] = "passed"
        for name, control_id in CONTROLS.items():
            controls.append(
                {
                    "control_id": control_id,
                    "profile": profile,
                    "width": width,
                    "theme": theme,
                    "status": "passed",
                    "detail": f"question {name}: input, visible state and real saved answer/cancellation after reload",
                }
            )
    except Exception as exc:
        if answer_row["status"] != "passed":
            answer_row["error"] = repr(exc)
        else:
            cancel_row["error"] = repr(exc)
        page.screenshot(path=str(directory / "failure.png"))
        raise
    finally:
        (directory / "events.json").write_text(json.dumps(events, indent=2))
        try:
            context.tracing.stop(path=str(directory / "trace.zip"))
        finally:
            context.close()


def run():
    _require_throwaway_data_root()
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records, controls = [], []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), QuestionModelHandler)
    provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    try:
        api("POST", "/api/setup/dismiss", {})
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "owned question fixture",
                "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["question-model"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint,
                "default_model": "question-model",
                "model_roles": {"aide_chat": {"endpoint_id": endpoint, "model": "question-model"}},
            },
        )
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for width in (1440, 820, 390, 320):
                    for theme in ("light", "dark"):
                        run_profile(browser, endpoint, output, records, controls, width, theme)
            finally:
                browser.close()
    finally:
        try:
            provider.shutdown()
        finally:
            provider.server_close()
            thread.join(5)
            (output / "scenarios.json").write_text(json.dumps(records, indent=2))
            (output / "controls.json").write_text(json.dumps(controls, indent=2))
    print(json.dumps({"status": "passed", "scenario_count": len(records)}))


if __name__ == "__main__":
    run()
