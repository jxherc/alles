"""Compare response recovery and confirmed votes on an owned local application."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]]
profiles += [(1440, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce",
                "has_touch": width == 390,
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    profile / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(**options)
            state = {"beta": "http", "offline": False, "lose_vote_reply": True}
            starts, streams, votes, held, errors, console = [], [], [], [], [], []
            requests = {}

            def route(request):
                url = urlparse(request.request.url)
                if url.netloc != urlparse(base).netloc:
                    return request.abort()
                path = url.path
                if path == "/api/models":
                    return request.fulfill(
                        json=[
                            {
                                "id": "owned",
                                "name": "local fixture",
                                "enabled": True,
                                "models": ["synthetic alpha", "synthetic beta"],
                            }
                        ]
                    )
                if path == "/api/compare" and request.request.method == "POST":
                    body = request.request.post_data_json
                    starts.append(body)
                    if state["offline"]:
                        return request.abort("internetdisconnected")
                    identity = f"owned-{len(starts)}"
                    requests[identity] = body
                    return request.fulfill(
                        json={"compare_id": identity, "count": len(body["models"])}
                    )
                if path.startswith("/api/compare/owned-"):
                    if request.request.method == "DELETE":
                        return request.fulfill(json={"ok": True})
                    identity, _, index = path.removeprefix("/api/compare/").partition("/stream/")
                    model = requests[identity]["models"][int(index)]["model"]
                    streams.append({"identity": identity, "model": model})
                    mode = state["beta"] if model == "synthetic beta" else "success"
                    if mode == "http":
                        return request.fulfill(
                            status=503, json={"detail": "synthetic model unavailable"}
                        )
                    if mode == "hold":
                        held.append(request)
                        return None
                    if mode == "sse":
                        body = 'data: {"delta":"partial beta answer"}\n\ndata: {"error":"HTTP 429: synthetic limit"}\n\ndata: [DONE]\n\n'
                    elif mode == "empty_delta":
                        body = 'data: {"delta":""}\n\ndata: {"error":"synthetic retry failure"}\n\n'
                    elif mode == "whitespace_delta":
                        body = (
                            'data: {"delta":"   "}\n\ndata: {"error":"synthetic retry failure"}\n\n'
                        )
                    elif mode == "empty_answer":
                        body = 'data: {"done":true}\n\n'
                    elif mode == "empty_error":
                        body = 'data: {"delta":"unfinished beta answer"}\n\ndata: {"error":""}\n\ndata: [DONE]\n\n'
                    elif mode == "malformed_done":
                        body = 'data: {"delta":"unfinished beta answer","done":"false"}\n\n'
                    elif mode == "interrupted":
                        body = 'data: {"delta":"interrupted beta answer"}\n\n'
                    else:
                        body = f'data: {json.dumps({"delta": "successful " + model})}\n\ndata: {{"done":true}}\n\ndata: [DONE]\n\n'
                    return request.fulfill(content_type="text/event-stream", body=body)
                if path == "/api/compare/vote" and request.request.method == "POST":
                    votes.append(request.request.post_data_json)
                    response = request.fetch()
                    assert response.ok
                    if state["lose_vote_reply"]:
                        state["lose_vote_reply"] = False
                        return request.fulfill(
                            status=503, json={"detail": "synthetic acknowledgement lost"}
                        )
                    return request.fulfill(response=response)
                return request.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "compare.response-recovery", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                before_votes = context.request.get(base + "/api/compare/stats").json()["votes"]
                page.goto(base + "/?view=compare", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate("""async () => {
                        const tab = (await chrome.tabs.query({})).find(t => t.url.startsWith('http://127.0.0.1:'));
                        await chrome.tabs.setZoom(tab.id, 2); return chrome.tabs.getZoom(tab.id);
                    }""")
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                for name in ["synthetic alpha", "synthetic beta"]:
                    page.get_by_role("checkbox", name=name, exact=True).press("Space")
                prompt = "compare these local plans\nkeep this exact submitted question"
                page.locator("#compare-input").fill(prompt)
                page.locator("#compare-send-btn").press("Enter")
                alpha, beta = page.locator("#compare-col-0"), page.locator("#compare-col-1")
                retry = beta.get_by_role("button", name="retry", exact=True)
                expect(alpha).to_have_attribute("data-state", "complete")
                assert (
                    alpha.locator(".compare-body").evaluate(
                        "el=>parseFloat(getComputedStyle(el).fontSize)"
                    )
                    >= 16
                )
                expect(beta).to_have_attribute("data-state", "error")
                expect(page.locator("#compare-submitted-prompt")).to_have_text(prompt)
                expect(beta.locator(".compare-column-status")).to_contain_text(
                    "temporarily unavailable"
                )
                expect(alpha.get_by_role("button", name="pick winner")).to_be_disabled()
                expect(beta.get_by_role("button", name="pick winner")).to_be_disabled()
                page.evaluate("window._pickWinner(1)")
                assert not votes
                expect(retry).to_be_visible()
                for selector in [
                    "[data-compare-stop]",
                    "[data-compare-retry]",
                    "[data-compare-settings]",
                    ".compare-error-detail",
                ]:
                    expect(alpha.locator(selector)).to_be_hidden()
                expect(beta.locator("[data-compare-stop]")).to_be_hidden()
                geometry = page.evaluate("""() => {
                    const results=document.querySelector('#compare-results');
                    const grid=document.querySelector('#compare-grid');
                    return {width:results.getBoundingClientRect().width, scroll:grid.scrollWidth, client:grid.clientWidth,
                        columns:[...grid.querySelectorAll('.compare-col')].map(el=>({left:el.getBoundingClientRect().left,top:el.getBoundingClientRect().top}))};
                }""")
                if geometry["width"] <= 620:
                    assert geometry["scroll"] <= geometry["client"]
                    assert abs(geometry["columns"][0]["left"] - geometry["columns"][1]["left"]) <= 1
                    assert geometry["columns"][1]["top"] > geometry["columns"][0]["top"]
                beta.locator(".compare-column-status").scroll_into_view_if_needed()
                page.screenshot(path=str(out / f"{label}-http-partial.png"))
                settings = beta.get_by_role("button", name="model settings")
                settings.press("Enter")
                expect(page.locator("#s-pane-models")).to_be_visible()
                page.keyboard.press("Escape")
                expect(settings).to_be_focused()
                page.locator("#compare-input").fill("next draft must survive every recovery")
                state["beta"] = "sse"
                if width == 390:
                    retry.tap()
                else:
                    retry.press("Enter")
                expect(beta.locator(".compare-column-status")).to_contain_text("reached its limit")
                expect(beta.locator(".compare-body")).to_have_text("partial beta answer")
                beta.locator("summary").press("Enter")
                expect(beta.locator("pre")).to_contain_text("HTTP 429")
                for mode in ["empty_delta", "whitespace_delta", "empty_answer"]:
                    state["beta"] = mode
                    retry.press("Enter")
                    expect(beta).to_have_attribute("data-state", "error")
                    expect(beta.locator(".compare-body")).to_have_text("partial beta answer")
                    expect(beta.locator("[data-compare-winner]")).to_be_disabled()
                state["offline"] = True
                context.set_offline(True)
                retry.press("Enter")
                expect(beta.locator(".compare-column-status")).to_contain_text("you are offline")
                expect(beta.locator(".compare-body")).to_have_text("partial beta answer")
                context.set_offline(False)
                state["offline"] = False
                state["beta"] = "interrupted"
                retry.press("Enter")
                expect(beta).to_have_attribute("data-state", "error")
                expect(beta.locator("pre")).to_contain_text("stopped before it finished")
                expect(beta.locator(".compare-body")).to_have_text("interrupted beta answer")
                state["beta"] = "malformed_done"
                retry.press("Enter")
                expect(beta).to_have_attribute("data-state", "error")
                expect(beta.locator("pre")).to_contain_text("stopped before it finished")
                expect(beta.locator(".compare-body")).to_have_text("unfinished beta answer")
                expect(beta.locator("[data-compare-winner]")).to_be_disabled()
                state["beta"] = "empty_error"
                retry.press("Enter")
                expect(beta).to_have_attribute("data-state", "error")
                expect(beta.locator("pre")).to_contain_text("without details")
                expect(beta.locator("[data-compare-winner]")).to_be_disabled()
                state["beta"] = "hold"
                retry.press("Enter")
                expect(beta.get_by_role("button", name="retrying…", exact=True)).to_have_attribute(
                    "aria-disabled", "true"
                )
                page.wait_for_function(
                    "document.querySelector('#compare-col-1').dataset.state === 'streaming'"
                )
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(10)
                assert len(held) == 1
                beta.get_by_role("button", name="stop response").press("Enter")
                expect(beta).to_have_attribute("data-state", "stopped")
                expect(retry).to_be_focused()
                expect(beta.locator("[data-compare-stop]")).to_be_hidden()
                expect(beta.locator("[data-compare-settings]")).to_be_hidden()
                expect(beta.locator(".compare-body")).to_have_text("unfinished beta answer")
                try:
                    held.pop().fulfill(
                        content_type="text/event-stream",
                        body='data: {"delta":"stale answer must not appear"}\n\ndata: [DONE]\n\n',
                    )
                except Exception:
                    pass  # The stopped browser request may already be canceled.
                expect(beta.locator(".compare-body")).not_to_contain_text("stale answer")
                page.screenshot(path=str(out / f"{label}-stopped.png"))
                state["beta"] = "success"
                retry.press("Enter")
                expect(beta).to_have_attribute("data-state", "complete")
                for selector in [
                    "[data-compare-stop]",
                    "[data-compare-retry]",
                    "[data-compare-settings]",
                    ".compare-error-detail",
                ]:
                    expect(beta.locator(selector)).to_be_hidden()
                expect(beta.locator(".compare-body")).to_have_text("successful synthetic beta")
                expect(alpha.locator(".compare-body")).to_have_text("successful synthetic alpha")
                expect(page.locator("#compare-input")).to_have_value(
                    "next draft must survive every recovery"
                )
                expect(page.locator("#compare-submitted-prompt")).to_have_text(prompt)
                assert len([s for s in streams if s["model"] == "synthetic alpha"]) == 1
                assert all(
                    s["message"] == prompt
                    and len(s["models"]) == 1
                    and s["models"][0]["model"] == "synthetic beta"
                    for s in starts[1:]
                )
                winner = alpha.get_by_role("button", name="pick winner", exact=True)
                expect(winner).to_be_enabled()
                winner.press("Enter")
                expect(alpha.get_by_role("button", name="retry vote", exact=True)).to_be_enabled()
                expect(page.locator("#compare-results-status")).to_contain_text(
                    "may be partly saved"
                )
                assert (
                    context.request.get(base + "/api/compare/stats").json()["votes"]
                    == before_votes + 1
                )
                assert "compare-winner" not in (alpha.get_attribute("class") or "")
                alpha.get_by_role("button", name="retry vote", exact=True).press("Enter")
                expect(
                    alpha.get_by_role("button", name="winner saved", exact=True)
                ).to_be_disabled()
                expect(page.locator("#compare-results-status")).to_have_text(
                    "winner saved to the leaderboard."
                )
                assert len(votes) == 2 and votes[0] == votes[1]
                assert (
                    context.request.get(base + "/api/compare/stats").json()["votes"]
                    == before_votes + 1
                )
                page.screenshot(path=str(out / f"{label}-winner-saved.png"))
                # A later comparison owns its output even if an old response arrives late.
                state["beta"] = "hold"
                page.locator("#compare-input").fill("old comparison waiting for beta")
                page.locator("#compare-send-btn").press("Enter")
                for _ in range(100):
                    if held:
                        break
                    page.wait_for_timeout(10)
                assert len(held) == 1
                obsolete = held.pop()
                state["beta"] = "success"
                next_prompt = (
                    "new comparison · 中文 · " + "keep the original question readable " * 12
                )
                page.locator("#compare-input").fill(next_prompt)
                page.locator("#compare-send-btn").press("Enter")
                expect(page.locator("#compare-submitted-prompt")).to_have_text(next_prompt)
                expect(beta).to_have_attribute("data-state", "complete")
                for selector in [
                    "[data-compare-stop]",
                    "[data-compare-retry]",
                    "[data-compare-settings]",
                    ".compare-error-detail",
                ]:
                    expect(beta.locator(selector)).to_be_hidden()
                try:
                    obsolete.fulfill(
                        content_type="text/event-stream",
                        body='data: {"delta":"obsolete comparison response"}\n\ndata: [DONE]\n\n',
                    )
                except Exception:
                    pass
                expect(beta.locator(".compare-body")).to_have_text("successful synthetic beta")
                expect(page.locator("#compare-submitted-prompt")).to_have_text(next_prompt)
                page.locator("#compare-submitted-prompt").focus()
                page.screenshot(path=str(out / f"{label}-long-question.png"))
                assert not errors, errors
                assert all(
                    "503" in message or "ERR_INTERNET_DISCONNECTED" in message
                    for message in console
                ), console
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                row.update(
                    status="passed", starts=starts, streams=streams, votes=votes, native_zoom=zoom
                )
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                context.set_offline(False)
                page.screenshot(path=str(out / f"{label}-final.png"))
                row.update(page_errors=list(errors), console_errors=list(console))
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()

raise SystemExit(any(row["status"] != "passed" for row in rows))
