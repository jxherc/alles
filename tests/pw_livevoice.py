"""Voice UI lifecycle with synthetic media and provider responses on an owned server."""

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

BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])

MEDIA = """
window.__voice = { mode: 'allow', requests: 0, stopped: 0, peers: [], tracks: [] };
navigator.mediaDevices.getUserMedia = async () => {
  const fixture = window.__voice;
  fixture.requests++;
  if (fixture.mode === 'deny') throw new DOMException('synthetic denial', 'NotAllowedError');
  const track = new EventTarget();
  track.enabled = true;
  track.stop = () => { fixture.stopped++; };
  fixture.tracks.push(track);
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  if (fixture.mode === 'pending') return new Promise(resolve => { fixture.resolveMedia = () => resolve(stream); });
  return stream;
};
window.RTCPeerConnection = class extends EventTarget {
  constructor() { super(); this.connectionState = 'new'; window.__voice.peers.push(this); }
  addTrack() {}
  createDataChannel() {
    const channel = new EventTarget(); channel.readyState = 'open'; channel.send = () => {};
    channel.close = () => { channel.readyState = 'closed'; channel.dispatchEvent(new Event('close')); };
    return this.channel = channel;
  }
  async createOffer() { return { type: 'offer', sdp: 'v=0\\r\\nsynthetic offer' }; }
  async setLocalDescription() {}
  async setRemoteDescription() { this.setState('connected'); }
  setState(value) { this.connectionState = value; this.dispatchEvent(new Event('connectionstatechange')); }
  close() { this.setState('closed'); }
};
"""


def run(browser, width, theme):
    context = browser.new_context(
        viewport={"width": width, "height": 900}, reduced_motion="reduce", color_scheme=theme
    )
    context.add_init_script(MEDIA)
    events = {
        "errors": [],
        "external": [],
        "calls": [],
        "offers": [],
        "hangups": [],
        "confirmations": [],
        "expected_http_errors": [],
        "console_http_errors": [],
    }
    available = False
    auth_mode = "required"

    def auth_failure(route, status, code):
        events["expected_http_errors"].append({"url": route.request.url, "status": status})
        return route.fulfill(status=status, json={"code": code})

    def boundary(route):
        nonlocal auth_mode
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(request.url)
            return route.abort()
        if url.path == "/api/voice/realtime/status":
            return route.fulfill(
                json={
                    "available": available,
                    "reason": "synthetic unavailable" if not available else "",
                    "model": "synthetic-realtime" if available else "",
                }
            )
        if url.path == "/api/aide/calls" and request.method == "POST":
            events["calls"].append(request.post_data_json)
            return route.fulfill(
                json={"id": request.post_data_json["request_id"], "session_id": "synthetic-primary"}
            )
        if url.path == "/api/auth/reauth":
            assert request.post_data_json == {"password": "synthetic test password"}
            events["confirmations"].append(auth_mode)
            if auth_mode == "wrong":
                return auth_failure(route, 401, "invalid_password")
            auth_mode = "fresh"
            return route.fulfill(json={"ok": True})
        if url.path.startswith("/api/aide/calls/"):
            if url.path.endswith("/offer"):
                events["offers"].append({"path": url.path, "sdp": request.post_data})
                if auth_mode != "fresh":
                    return auth_failure(route, 403, "recent_auth_required")
                return route.fulfill(content_type="application/sdp", body="v=0\r\nsynthetic answer")
            if url.path.endswith("/hangup"):
                events["hangups"].append(url.path)
                return route.fulfill(json={"state": "ended", "tasks_cancelled": False})
        return route.continue_()

    context.route("**/*", boundary)
    page = context.new_page()
    page.on("pageerror", lambda error: events["errors"].append(str(error)))

    def console(message):
        if message.type != "error":
            return
        for failure in events["expected_http_errors"]:
            reason = "Forbidden" if failure["status"] == 403 else "Unauthorized"
            expected = f"Failed to load resource: the server responded with a status of {failure['status']} ({reason})"
            if message.text == expected and message.location.get("url") == failure["url"]:
                events["console_http_errors"].append(failure)
                return
        events["errors"].append(message.text)

    page.on("console", console)
    label = f"{width}-{theme}"
    try:
        assert context.request.post(BASE + "/api/setup/dismiss").ok
        assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.locator("#composer-ta").fill("keep the conversation draft")
        page.locator("#aide-call-open").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#aide-call-title")).to_have_text("calling unavailable")
        expect(page.locator("#aide-call-back")).to_be_focused()
        assert page.evaluate("window.__voice.requests") == 0
        page.screenshot(path=str(OUT / f"unavailable-{label}.png"))
        available = True
        page.locator("#aide-call-retry").click()
        expect(page.locator("#aide-call-title")).to_have_text("ready to talk")
        assert page.evaluate("window.__voice.requests") == 0
        page.locator("#aide-call-start").click()
        password = page.locator('.dialog-input[type="password"]')
        expect(password).to_be_focused()
        expect(page.locator('.dialog-card[role="dialog"]')).to_contain_text(
            "needed to start this voice call"
        )
        assert len(events["offers"]) == len(events["calls"]) == 1
        assert not events["confirmations"]
        page.keyboard.press("Shift+Tab")
        expect(page.locator("[data-dialog-confirm]")).to_be_focused()
        page.keyboard.press("Tab")
        expect(password).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / f"owner-confirmation-{label}.png"))
        password.fill("synthetic test password")
        page.keyboard.press("Enter")
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        expect(page.locator('.dialog-card[role="dialog"]')).to_have_count(0)
        assert events["offers"][0] == events["offers"][1]
        assert events["confirmations"] == ["required"]
        page.locator("#aide-call-mute").click()
        expect(page.locator("#aide-call-title")).to_have_text("microphone muted")
        assert page.evaluate("window.__voice.tracks.at(-1).enabled") is False
        page.locator("#aide-call-mute").click()
        page.evaluate("window.__voice.peers.at(-1).setState('disconnected')")
        expect(page.locator("#aide-call-title")).to_have_text("reconnecting")
        boxes = page.locator("#aide-call-workspace button:visible").evaluate_all(
            "items => items.map(item => ({id:item.id, width:item.getBoundingClientRect().width, height:item.getBoundingClientRect().height}))"
        )
        assert all(box["width"] >= 44 and box["height"] >= 44 for box in boxes), boxes
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / f"reconnecting-{label}.png"))
        page.evaluate("window.__voice.peers.at(-1).setState('connected')")
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        assert len(events["calls"]) == 1
        page.keyboard.press("Escape")
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
        expect(page.locator("#composer-ta")).to_have_value("keep the conversation draft")
        expect(page.locator("#aide-call-open")).to_be_focused()
        page.locator("#aide-mode-coding").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "coding")
        page.locator("#aide-call-open").click()
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        assert page.evaluate("window._navigateTo('today')") is True
        expect(page.locator("#today-view")).to_be_visible()
        expect(page.locator("#aide-call-workspace")).to_be_hidden()
        page.evaluate("window.__voice.peers.at(-1).setState('disconnected')")
        expect(page.locator("#aide-call-workspace")).to_be_hidden()
        page.evaluate("window.__voice.peers.at(-1).setState('connected')")
        expect(page.locator("#aide-call-workspace")).to_be_hidden()
        assert page.evaluate("window.__voice.stopped") == 0
        page.locator("#aide-call-return").click()
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        page.keyboard.press("Escape")
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "coding")
        expect(page.locator("#composer-ta")).to_have_value("keep the conversation draft")
        expect(page.locator("#aide-call-open")).to_be_focused()
        page.locator("#aide-call-open").click()
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        page.locator("#aide-call-end").click()
        expect(page.locator("#aide-call-title")).to_have_text("call ended")
        assert page.evaluate("window.__voice.stopped") == 1
        page.evaluate("window.__voice.mode = 'deny'")
        page.locator("#aide-call-start").click()
        expect(page.locator("#aide-call-description")).to_contain_text(
            "microphone access was denied"
        )
        assert len(events["calls"]) == 1
        page.screenshot(path=str(OUT / f"denied-{label}.png"))
        page.evaluate("window.__voice.mode = 'pending'")
        page.locator("#aide-call-start").click()
        expect(page.locator("#aide-call-title")).to_have_text("connecting")
        page.locator("#aide-call-end").click()
        expect(page.locator("#aide-call-title")).to_have_text("call ended")
        page.evaluate("window.__voice.resolveMedia()")
        page.wait_for_function("window.__voice.stopped === 2")
        assert len(events["calls"]) == 1
        page.evaluate("window.__voice.mode = 'allow'")
        page.locator("#aide-call-start").click()
        expect(page.locator("#aide-call-title")).to_have_text("connected")
        page.evaluate("window.__voice.peers.at(-1).setState('failed')")
        expect(page.locator("#aide-call-title")).to_have_text("call interrupted")
        page.wait_for_function("window.__voice.stopped === 3")
        auth_mode = "required"
        page.locator("#aide-call-start").click()
        expect(password).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#aide-call-description")).to_contain_text(
            "call cancelled before connecting"
        )
        page.wait_for_function("window.__voice.stopped === 4")
        assert len(events["offers"]) == 4
        assert events["confirmations"] == ["required"]
        auth_mode = "wrong"
        page.locator("#aide-call-start").click()
        expect(password).to_be_focused()
        password.fill("synthetic test password")
        page.keyboard.press("Enter")
        expect(page.locator("#aide-call-description")).to_contain_text(
            "password confirmation failed"
        )
        page.wait_for_function("window.__voice.stopped === 5")
        assert len(events["offers"]) == 5
        assert events["confirmations"] == ["required", "wrong"]
        page.screenshot(path=str(OUT / f"owner-confirmation-failed-{label}.png"))
        page.locator("#aide-call-back").click()
        page.locator("#aide-mode-coding").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "coding")
        page.locator("#aide-call-open").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "call")
        page.locator("#aide-call-back").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "coding")
        requests_before = page.evaluate("window.__voice.requests")
        page.evaluate("window._openSettings('voice')")
        expect(page.locator("#s-mic-select")).to_be_visible()
        assert page.evaluate("window.__voice.requests") == requests_before
        page.screenshot(path=str(OUT / f"settings-{label}.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not events["errors"] and not events["external"], events
        assert len(events["calls"]) == len(events["hangups"]) == 4
        assert len(events["expected_http_errors"]) == len(events["console_http_errors"]) == 4
        return {
            "profile": label,
            "status": "passed",
            "simulation": "fake media, WebRTC and provider responses; no real audio or provider",
            **events,
        }
    except Exception:
        page.screenshot(path=str(OUT / f"failure-{label}.png"))
        raise
    finally:
        (OUT / f"events-{label}.json").write_text(json.dumps(events, indent=2) + "\n")
        context.close()


def main():
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme in [(1440, "dark"), (390, "light")]:
                rows.append(run(browser, width, theme))
        finally:
            browser.close()
            (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
