"""Aide composer reachability with owned data and a simulated loopback provider."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]
from pw_aide_continuity import Provider  # noqa: E402
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

PASSWORD = "composer-owned-synthetic-password"
SIMULATION = "real local Alles UI/backend; simulated delayed assistant on loopback"


def serve():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text() == os.environ["ALLES_TEST_RUN_ID"]
    import uvicorn

    from app import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), proxy_headers=False)


def until(page, check):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        page.wait_for_timeout(50)
    raise AssertionError("owned assistant state did not settle")


def tab_to(page, target):
    visited = []
    for _ in range(32):
        if target.evaluate("e => e === document.activeElement"):
            return visited
        page.keyboard.press("Tab")
        visited.append(page.evaluate("document.activeElement.id"))
    raise AssertionError(f"control not reachable by Tab: {visited}")


def geometry(page):
    result = page.evaluate("""() => ({
      width: innerWidth, height: innerHeight, pageWidth: document.documentElement.scrollWidth,
      input: document.getElementById('composer-ta').getBoundingClientRect().toJSON(),
      jump: document.getElementById('jump-latest').hidden ? null :
        document.getElementById('jump-latest').getBoundingClientRect().toJSON(),
      controls: [...document.querySelectorAll('.composer-box button')]
        .filter(e => e.getBoundingClientRect().width && getComputedStyle(e).visibility !== 'hidden')
        .map(e => { const r = e.getBoundingClientRect(); return {
          id: e.id, disabled: e.disabled, rect: r.toJSON(),
          reachable: e.disabled || [[.1,.1],[.9,.1],[.5,.5],[.1,.9],[.9,.9]]
            .every(([x,y]) => e.contains(document.elementFromPoint(r.x+r.width*x,r.y+r.height*y)))
        }; })
    })""")
    assert result["pageWidth"] == result["width"], result
    if result["jump"]:
        a, b = result["input"], result["jump"]
        assert (
            a["right"] <= b["left"]
            or a["left"] >= b["right"]
            or a["bottom"] <= b["top"]
            or a["top"] >= b["bottom"]
        ), result
    for control in result["controls"]:
        r = control["rect"]
        assert r["width"] >= 44 and r["height"] >= 44, control
        assert r["left"] >= 0 and r["top"] >= 0, control
        assert r["right"] <= result["width"] and r["bottom"] <= result["height"], control
        assert control["reachable"], control
    return result


def run():
    from playwright.sync_api import expect, sync_playwright

    from services.appearance import from_legacy

    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS", "/tmp/alles-aide-composer"))
    out.mkdir(parents=True, exist_ok=True)
    state = Provider()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), state.handler())
    provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    rows = []
    process = None
    fixture = {"provider_port": provider.server_port}
    try:
        with owned_data() as (data, runid):
            port = free_port()
            fixture.update(data_root=str(data), port=port, run_id=runid)
            env = isolated_environment(data, runid, port, out)
            env.update(
                AUTH_ENABLED="true",
                AUTH_PASSWORD=PASSWORD,
                SECRET_KEY="composer-owned-synthetic-key",
            )
            log = (out / "server.log").open("w")
            process = None
            try:
                process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--server"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=False,
                )
                fixture["pid"] = process.pid
                wait_for_server(process, port, runid, 60)
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    (out / "environment.json").write_text(
                        json.dumps({"browser": browser.version, "simulation": SIMULATION}, indent=2)
                    )
                    try:
                        for width in (320, 390, 1440):
                            for theme in ("light", "dark"):
                                label = f"{width}-{theme}"
                                dest = out / label
                                dest.mkdir(exist_ok=True)
                                context = browser.new_context(
                                    base_url=f"http://127.0.0.1:{port}",
                                    viewport={
                                        "width": width,
                                        "height": 844 if width < 700 else 900,
                                    },
                                    is_mobile=width < 700,
                                    has_touch=width < 700,
                                    reduced_motion="reduce",
                                    locale="en-US",
                                    timezone_id="UTC",
                                    service_workers="block",
                                )
                                context.tracing.start(
                                    screenshots=True, snapshots=True, sources=True
                                )
                                events = {
                                    "console": [],
                                    "pageerrors": [],
                                    "failed": [],
                                    "http": [],
                                    "chat": [],
                                    "stop": [],
                                    "outbound": [],
                                }
                                result = {
                                    "scenario_id": "aide.composer-responsive",
                                    "profile": "phone" if width < 700 else "desktop",
                                    "width": width,
                                    "theme": theme,
                                    "simulation": SIMULATION,
                                    "status": "running",
                                    "geometry": {},
                                }
                                rows.append(result)
                                try:
                                    api = context.request

                                    def request(method, path, body=None):
                                        response = api.fetch(path, method=method, data=body)
                                        assert response.ok, (
                                            method,
                                            path,
                                            response.status,
                                            response.text(),
                                        )
                                        return response.json()

                                    request("POST", "/api/auth/login", {"password": PASSWORD})
                                    request("POST", "/api/setup/dismiss")
                                    request("PUT", "/api/appearance", from_legacy(theme, None))
                                    endpoint = request(
                                        "POST",
                                        "/api/models/endpoint",
                                        {
                                            "name": label,
                                            "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                                            "provider_adapter": "manual",
                                        },
                                    )
                                    request(
                                        "PATCH",
                                        f"/api/models/endpoint/{endpoint['id']}",
                                        {"models": ["continuity-fixture"]},
                                    )
                                    request(
                                        "PATCH",
                                        "/api/settings",
                                        {
                                            "default_endpoint_id": endpoint["id"],
                                            "default_model": "continuity-fixture",
                                            "model_roles": {
                                                "aide_chat": {
                                                    "endpoint_id": endpoint["id"],
                                                    "model": "continuity-fixture",
                                                }
                                            },
                                            "memory_policy": "off",
                                            "memory_auto_inject": False,
                                            "intent_suggestions": False,
                                            "auto_compact": False,
                                        },
                                    )
                                    session = request(
                                        "POST",
                                        "/api/sessions",
                                        {
                                            "model": "continuity-fixture",
                                            "endpoint_id": endpoint["id"],
                                            "mode": "agent",
                                            "name": label,
                                        },
                                    )
                                    sid = session["id"]
                                    result["session_id"] = sid
                                    page = context.new_page()
                                    page.set_default_timeout(15000)
                                    page.on(
                                        "console",
                                        lambda e: events["console"].append((e.type, e.text)),
                                    )
                                    page.on(
                                        "pageerror", lambda e: events["pageerrors"].append(str(e))
                                    )
                                    page.on(
                                        "requestfailed",
                                        lambda r: events["failed"].append(
                                            (r.method, urlsplit(r.url).path, r.failure)
                                        ),
                                    )
                                    page.on(
                                        "response",
                                        lambda r: (
                                            events["http"].append(
                                                (r.request.method, urlsplit(r.url).path, r.status)
                                            )
                                            if r.status >= 400
                                            else None
                                        ),
                                    )

                                    def on_request(r):
                                        path = urlsplit(r.url).path
                                        if path == "/api/chat":
                                            events["chat"].append(r.post_data_json)
                                        if path.startswith("/api/chat/stop/"):
                                            events["stop"].append((r.method, path))

                                    page.on("request", on_request)

                                    def guard(route):
                                        if urlsplit(route.request.url).hostname != "127.0.0.1":
                                            events["outbound"].append(route.request.url)
                                            route.abort("blockedbyclient")
                                        else:
                                            route.continue_()

                                    context.route("**/*", guard)
                                    page.goto(f"/?view=chat#{sid}", wait_until="networkidle")
                                    expect(page.locator("#setup-wizard")).to_be_hidden()
                                    expect(page.locator("#composer-ta")).to_be_visible()

                                    def close_history():
                                        backdrop = page.locator("#nav-backdrop")
                                        if width < 700 and backdrop.is_visible():
                                            box = backdrop.bounding_box()
                                            backdrop.click(
                                                position={"x": box["width"] - 12, "y": 200}
                                            )
                                            expect(backdrop).to_be_hidden()

                                    close_history()

                                    def snapshot(name):
                                        page.screenshot(path=str(dest / f"{name}.png"))
                                        result["geometry"][name] = geometry(page)

                                    snapshot("01-empty")
                                    key = f"{label}-early-stop"
                                    state.plan(key)
                                    first = f"Respond with fixture text for {key}"
                                    page.locator("#composer-ta").click()
                                    page.locator("#composer-ta").fill(first)
                                    send = page.get_by_role("button", name="send", exact=True)
                                    send.tap() if width < 700 else send.click()
                                    until(
                                        page,
                                        lambda: any(
                                            e["event"] == "provider_request" and e.get("key") == key
                                            for e in state.events
                                        ),
                                    )
                                    stop = page.get_by_role("button", name="stop", exact=True)
                                    expect(stop).to_be_visible()
                                    expect(send).to_be_disabled()
                                    snapshot("02-pending")
                                    box = send.bounding_box()
                                    page.mouse.click(
                                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                                    )
                                    assert len(events["chat"]) == 1, events
                                    result["stop_tab_path"] = tab_to(page, stop)
                                    snapshot("02b-keyboard-stop")
                                    page.keyboard.press("Enter")
                                    expect(send).to_be_enabled()
                                    expect(stop).to_be_hidden()
                                    expect(page.locator(".aide-interruption")).to_have_text(
                                        "response interrupted"
                                    )
                                    until(
                                        page,
                                        lambda: (
                                            not request(
                                                "GET", f"/api/agent/runs/active?session_id={sid}"
                                            )
                                        ),
                                    )
                                    stopped = request("GET", f"/api/sessions/{sid}/history")[
                                        "messages"
                                    ]
                                    assert [m["role"] for m in stopped] == ["user", "assistant"], (
                                        stopped
                                    )
                                    assert (
                                        stopped[0]["content"] == first
                                        and stopped[1]["meta"]["interrupted"]
                                    ), stopped
                                    assert not any(
                                        e["event"] == "partial_sent" and e.get("key") == key
                                        for e in state.events
                                    )
                                    state.releases[key].set()
                                    page.reload(wait_until="networkidle")
                                    close_history()
                                    expect(page.locator("#messages .user-bubble")).to_have_text(
                                        first
                                    )
                                    expect(page.locator(".aide-interruption")).to_have_text(
                                        "response interrupted"
                                    )
                                    assert (
                                        request("GET", f"/api/sessions/{sid}/history")["messages"]
                                        == stopped
                                    )
                                    snapshot("03-stopped-reload")
                                    key = f"{label}-complete"
                                    state.plan(key)
                                    state.releases[key].set()
                                    second = f"Respond with fixture text for {key}"
                                    page.locator("#composer-ta").click()
                                    page.locator("#composer-ta").fill(second)
                                    page.locator("#chat").hover()
                                    page.mouse.wheel(0, -200)
                                    jump = page.get_by_role(
                                        "button", name="jump to latest ↓", exact=True
                                    )
                                    expect(jump).to_be_visible()
                                    snapshot("03a-draft-jump")
                                    jump.tap() if width < 700 else jump.click()
                                    expect(jump).to_be_hidden()
                                    expect(page.locator("#composer-ta")).to_have_value(second)
                                    page.locator("#composer-ta").click()
                                    result["send_tab_path"] = tab_to(page, send)
                                    snapshot("03b-keyboard-send")
                                    page.keyboard.press("Enter")
                                    expect(
                                        page.locator("#messages .ai-content").last
                                    ).to_contain_text(f"finished for {key}.")
                                    expect(send).to_be_enabled()
                                    expect(stop).to_be_hidden()
                                    history = request("GET", f"/api/sessions/{sid}/history")[
                                        "messages"
                                    ]
                                    assert [m["role"] for m in history] == [
                                        "user",
                                        "assistant",
                                        "user",
                                        "assistant",
                                    ], history
                                    assert [
                                        m["content"] for m in history if m["role"] == "user"
                                    ] == [first, second], history
                                    assert not history[-1].get("meta", {}).get("interrupted"), (
                                        history
                                    )
                                    page.reload(wait_until="networkidle")
                                    close_history()
                                    expect(page.locator("#messages .user-bubble")).to_have_count(2)
                                    expect(
                                        page.locator("#messages .ai-content").last
                                    ).to_contain_text(f"finished for {key}.")
                                    assert (
                                        request("GET", f"/api/sessions/{sid}/history")["messages"]
                                        == history
                                    )
                                    snapshot("04-completed-reload")
                                    result["history"] = history
                                    assert len(events["chat"]) == 2 and all(
                                        e["session_id"] == sid for e in events["chat"]
                                    ), events
                                    assert events["stop"] == [("POST", f"/api/chat/stop/{sid}")], (
                                        events
                                    )
                                    assert Counter(events["failed"]) == Counter(
                                        {("POST", "/api/chat", "net::ERR_ABORTED"): 1}
                                    ), events
                                    assert Counter(events["console"]) == Counter(
                                        {
                                            (
                                                "warning",
                                                "Service Worker registration blocked by Playwright",
                                            ): 6
                                        }
                                    ), events
                                    assert (
                                        not events["http"]
                                        and not events["pageerrors"]
                                        and not events["outbound"]
                                    ), events
                                    result["status"] = "passed"
                                except BaseException as exc:
                                    result.update(
                                        status="failed", error=f"{type(exc).__name__}: {exc}"
                                    )
                                    if "page" in locals():
                                        try:
                                            page.screenshot(path=str(dest / "failure.png"))
                                        except Exception:
                                            pass
                                    raise
                                finally:
                                    try:
                                        (dest / "events.json").write_text(
                                            json.dumps(events, indent=2)
                                        )
                                        (dest / "observations.json").write_text(
                                            json.dumps(result, indent=2)
                                        )
                                        context.tracing.stop(path=str(dest / "trace.zip"))
                                    finally:
                                        context.close()
                    finally:
                        browser.close()
            finally:
                try:
                    if process:
                        stop_process(process, process_group=False)
                finally:
                    log.close()
    finally:
        for release in state.releases.values():
            release.set()
        provider.shutdown()
        provider.server_close()
        thread.join(5)
        fixture["data_removed"] = not Path(fixture.get("data_root", "/nonexistent")).exists()
        for name in ("port", "provider_port"):
            if name in fixture:
                with socket.socket() as sock:
                    fixture[name + "_closed"] = sock.connect_ex(("127.0.0.1", fixture[name])) != 0
        fixture["server_stopped"] = process is None or process.poll() is not None
        (out / "owned-fixtures.json").write_text(json.dumps(fixture, indent=2))
        (out / "provider-events.json").write_text(json.dumps(state.events, indent=2))
        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps({"status": "passed", "scenarios": len(rows), "cleanup": fixture}))


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    serve() if sys.argv[1:] == ["--server"] else run()
