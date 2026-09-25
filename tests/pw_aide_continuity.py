"""Aide continuity through real UI and backend, with a delayed loopback-only provider.

This verifies no live credentials/model service. Run via the isolated browser runner.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

SIMULATION = "real Alles server/UI; controlled delayed OpenAI-compatible provider on loopback"


class Provider:
    def __init__(self):
        self.releases = {}
        self.events = []
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def record(self, kind, **values):
        with self.lock:
            self.events.append(
                {
                    "event": kind,
                    "at_ms": round((time.monotonic() - self.started) * 1000, 1),
                    **values,
                }
            )

    def plan(self, key):
        self.releases[key] = threading.Event()

    def handler(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                payload = json.dumps({"data": [{"id": "continuity-fixture"}]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
                latest = next(
                    (
                        row.get("content", "")
                        for row in reversed(body.get("messages", []))
                        if row.get("role") == "user"
                    ),
                    "",
                )
                key = next(
                    (candidate for candidate in state.releases if candidate in str(latest)), None
                )
                state.record(
                    "provider_request", latest_user=latest, stream=body.get("stream"), key=key
                )
                if not body.get("stream"):
                    payload = json.dumps(
                        {"choices": [{"message": {"role": "assistant", "content": "fixture task"}}]}
                    ).encode()
                    self.send_response(200)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()

                def token(text):
                    payload = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                    self.wfile.flush()

                try:
                    if key and "early-stop" in key:
                        state.releases[key].wait(40)
                    token(f"partial for {key}. ")
                    state.record("partial_sent", key=key)
                    if key:
                        state.releases[key].wait(40)
                    for index in range(6):
                        token(f"continuing {index}. ")
                        time.sleep(0.1)
                    token(f"finished for {key}.")
                    self.wfile.write(
                        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                    )
                    self.wfile.flush()
                    state.record("provider_finished", key=key)
                except (BrokenPipeError, ConnectionResetError):
                    state.record("provider_disconnected", key=key)

        return Handler


def api(method, path, body=None):
    request = Request(
        f"http://127.0.0.1:{os.environ['PORT']}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def missing(path):
    try:
        api("GET", path)
    except HTTPError as exc:
        assert exc.code == 404, exc
        return True
    return False


async def until(check, timeout=10):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition did not settle within {timeout}s; last={last!r}")


async def run_case(browser, state, endpoint, output, profile, case):
    key = f"{profile}-{case}"
    state.plan(key)
    case_dir = output / key
    case_dir.mkdir()
    session_ids = {}
    for label in ("A", "B"):
        session = api(
            "POST",
            "/api/sessions",
            {
                "model": "continuity-fixture",
                "endpoint_id": endpoint,
                "mode": "agent",
                "name": f"{key} {label}",
            },
        )
        api("PATCH", f"/api/sessions/{session['id']}", {"name": f"{key} {label}"})
        session_ids[label] = session["id"]
    context = await browser.new_context(
        viewport={
            "width": 390 if profile == "phone" else 1440,
            "height": 844 if profile == "phone" else 900,
        },
        reduced_motion="reduce",
        service_workers="block",
        locale="en-US",
        timezone_id="UTC",
    )
    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = await context.new_page()
    page.set_default_timeout(15000)
    events = {
        "console": [],
        "page_errors": [],
        "failed_requests": [],
        "http_errors": [],
        "chat_requests": [],
        "stop_requests": [],
    }
    expected_aborts = []
    chat_requests = []
    result = {"case": case, "profile": profile, "simulation": SIMULATION, "sessions": session_ids}

    def request_event(request):
        path = urlsplit(request.url).path
        if path == "/api/chat":
            chat_requests.append(request)
            events["chat_requests"].append(request.post_data_json)
        elif path.startswith("/api/chat/stop/"):
            events["stop_requests"].append(path.rsplit("/", 1)[-1])

    page.on("request", request_event)
    page.on("console", lambda msg: events["console"].append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "requestfailed",
        lambda request: events["failed_requests"].append(
            {
                "url": request.url,
                "error": request.failure,
                "expected": request in expected_aborts and request.failure == "net::ERR_ABORTED",
            }
        ),
    )
    page.on(
        "response",
        lambda response: (
            events["http_errors"].append({"url": response.url, "status": response.status})
            if response.status >= 400
            else None
        ),
    )

    async def guard(route):
        if urlsplit(route.request.url).hostname not in {"127.0.0.1", "localhost", "aide.localhost"}:
            events["http_errors"].append({"unexpected_outbound": route.request.url})
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    await context.route("**/*", guard)

    async def snapshot(label):
        await page.screenshot(path=str(case_dir / f"{label}.png"))

    async def select(label):
        if not await page.locator("#session-search").is_visible():
            await page.locator("#sidebar-toggle-btn").click()
        await page.locator("#session-search").fill(f"{key} {label}")
        await page.locator(f'.session-item[data-id="{session_ids[label]}"] .session-open').click()
        await expect(page.locator("#aide-conversation-name")).to_have_text(f"{key} {label}")
        await page.wait_for_function(
            "id => window._currentSession?.id === id", arg=session_ids[label]
        )
        # The phone history drawer must close before another real control can be reached.
        if profile == "phone" and await page.locator("#session-search").is_visible():
            backdrop = page.locator("#nav-backdrop")
            box = await backdrop.bounding_box()
            assert box
            await backdrop.click(position={"x": box["width"] - 12, "y": box["height"] / 2})
            await expect(page.locator("#session-search")).to_be_hidden()

    try:
        await page.goto(
            f"http://aide.localhost:{os.environ['PORT']}/#{session_ids['A']}",
            wait_until="networkidle",
        )
        if await page.locator("#setup-skip").is_visible():
            await page.locator("#setup-skip").click()
            await expect(page.locator("#setup-wizard")).to_be_hidden()
        await expect(page.locator("#composer-ta")).to_be_visible()
        if case == "incognito-stop":
            await page.locator("#incognito-btn").click()
            await expect(page.locator("#incognito-bar")).to_be_visible()
        prompt = f"Respond with the fixture text for {key}"
        await page.locator("#composer-ta").fill(prompt)
        await page.locator("#composer-ta").press("Enter")
        await until(
            lambda: (
                chat_requests
                and any(
                    e["event"] == "provider_request" and e.get("key") == key for e in state.events
                )
            )
        )
        sid = chat_requests[0].post_data_json["session_id"]
        result["originating_session"] = sid
        await expect(page.locator("#stop-btn")).to_be_visible()
        if case != "early-stop":
            await expect(page.locator("#messages .ai-content").last).to_contain_text(
                f"partial for {key}"
            )
        else:
            assert not any(
                e["event"] == "partial_sent" and e.get("key") == key for e in state.events
            )
        await snapshot("01-before-action")
        active = api("GET", f"/api/agent/runs/active?session_id={sid}")
        result["active_before"] = active
        if case.startswith("switch-"):
            await select("B")
            await snapshot("02-selected-other-session")
            if case == "switch-finish":
                await select("A")
        if case == "switch-finish":
            state.releases[key].set()
            await expect(page.locator("#messages .ai-content").last).to_contain_text(
                f"finished for {key}", timeout=10000
            )
        elif case == "navigate-disconnect":
            expected_aborts.extend(chat_requests)
            await page.locator("#app-drawer-btn").click()
            await page.locator('.app-drawer-item[data-view="today"]').click()
            await expect(page.locator("#today-view")).to_be_visible()
        else:
            expected_aborts.extend(chat_requests)
            await page.locator("#stop-btn").click()
            await expect(page.locator("#send-btn")).to_be_enabled()
            if case != "switch-stop":
                await expect(page.locator(".aide-interruption")).to_have_text(
                    "response interrupted"
                )
            await until(lambda: bool(events["stop_requests"]))
            assert events["stop_requests"] == [sid], events
        # Require server finalization while the provider is still held: no timeout/release rescue.
        await until(lambda: not api("GET", f"/api/agent/runs/active?session_id={sid}"))
        history = await until(lambda: api("GET", f"/api/sessions/{sid}/history")["messages"])
        expected_roles = ["user", "assistant"]
        assert [row["role"] for row in history] == expected_roles, history
        assert history[0]["content"] == prompt
        if case != "early-stop":
            assert f"partial for {key}" in history[1]["content"], history
            assert (f"finished for {key}" in history[1]["content"]) == (case == "switch-finish"), (
                history
            )
        assert bool(history[-1].get("meta", {}).get("interrupted")) == (case != "switch-finish"), (
            history
        )
        result["history"] = history
        assert api("GET", f"/api/sessions/{session_ids['B']}/history")["messages"] == []
        if case != "incognito-stop":
            runs = api("GET", "/api/agent/runs")
            run = next(row for row in runs if row["session_id"] == sid)
            assert run["status"] == ("done" if case == "switch-finish" else "cancelled"), run
            assert run["text"] == (history[1]["content"] if len(history) == 2 else ""), run
            result["terminal_run"] = run
        state.releases[key].set()
        if case == "incognito-stop":
            with sqlite3.connect(
                f"file:{Path(os.environ['ALLES_DATA']) / 'aide.db'}?mode=ro", uri=True
            ) as db:
                assert (
                    db.execute("SELECT count(*) FROM sessions WHERE id=?", (sid,)).fetchone()[0]
                    == 0
                )
                assert (
                    db.execute(
                        "SELECT count(*) FROM messages WHERE session_id=? OR content LIKE ?",
                        (sid, f"%{key}%"),
                    ).fetchone()[0]
                    == 0
                )
            result["sqlite_rows"] = 0
            private_files = []
            for path in (Path(os.environ["ALLES_DATA"]) / "agent_runs").glob("*.json"):
                saved = path.read_text()
                if sid in saved or key in saved:
                    private_files.append(path.name)
            assert not private_files, {"private_agent_run_files": private_files}
            result["private_agent_run_files"] = private_files
            private_run_id = result["active_before"]["id"]
            private_run = api("GET", f"/api/agent/runs/{private_run_id}")
            assert private_run["status"] == "cancelled", private_run
            assert private_run["text"] == history[1]["content"], private_run
            await snapshot("03-private-memory-only")
            await page.locator("#incognito-exit").click()
            await expect(page.locator("#incognito-bar")).to_be_hidden()
            await until(lambda: missing(f"/api/sessions/{sid}/history"))
            await until(lambda: missing(f"/api/agent/runs/{private_run_id}"))
            result["private_state_removed_on_exit"] = True
        else:
            if case == "navigate-disconnect":
                await page.locator("#app-drawer-btn").click()
                await page.locator('.app-drawer-item[data-view="chat"]').click()
                await expect(page.locator("#composer-ta")).to_be_visible()
            if case in {"switch-stop", "navigate-disconnect"}:
                await select("A")
            await page.reload(wait_until="networkidle")
            await expect(page.locator("#messages .user-bubble")).to_have_count(1)
            await expect(page.locator("#messages .user-bubble").last).to_have_text(prompt)
            if case != "early-stop":
                await expect(page.locator("#messages .ai-content")).to_have_count(1)
                await expect(page.locator("#messages .ai-content").last).to_contain_text(
                    f"partial for {key}"
                )
            await expect(page.locator(".bg-reattach-status")).to_have_count(0)
            if case == "switch-finish":
                await expect(page.locator(".aide-interruption")).to_have_count(0)
            else:
                await expect(page.locator(".aide-interruption")).to_have_text(
                    "response interrupted"
                )
            assert api("GET", f"/api/sessions/{sid}/history")["messages"] == history
        await snapshot("03-persisted-result")
        assert len(chat_requests) == 1, events
        assert not events["page_errors"], events
        assert not [row for row in events["console"] if row["type"] == "error"], events
        assert not events["http_errors"], events
        assert not [row for row in events["failed_requests"] if not row["expected"]], events
        result["status"] = "passed"
    except BaseException as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        await snapshot("failure")
        raise
    finally:
        state.releases[key].set()
        (case_dir / "observations.json").write_text(json.dumps(result, indent=2) + "\n")
        (case_dir / "browser-events.json").write_text(json.dumps(events, indent=2) + "\n")
        await context.tracing.stop(path=str(case_dir / "trace.zip"))
        await context.close()
    return result


async def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(f"http://127.0.0.1:{os.environ['PORT']}", run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    state = Provider()
    server = ThreadingHTTPServer(("127.0.0.1", 0), state.handler())
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scenarios = []
    try:
        endpoint = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "isolated continuity fixture",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )
        api("PATCH", f"/api/models/endpoint/{endpoint['id']}", {"models": ["continuity-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": endpoint["id"],
                "default_model": "continuity-fixture",
                "model_roles": {
                    "aide_chat": {"endpoint_id": endpoint["id"], "model": "continuity-fixture"}
                },
                "memory_policy": "off",
                "memory_auto_inject": False,
                "intent_suggestions": False,
                "auto_compact": False,
            },
        )
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            (output / "browser-environment.json").write_text(
                json.dumps(
                    {"browser": "chromium", "version": browser.version, "simulation": SIMULATION},
                    indent=2,
                )
                + "\n"
            )
            try:
                for profile in ("desktop", "phone"):
                    for case in (
                        "stop",
                        "early-stop",
                        "switch-stop",
                        "switch-finish",
                        "navigate-disconnect",
                        "incognito-stop",
                    ):
                        row = {
                            "scenario_id": f"workflow-aide-{case}",
                            "profile": profile,
                            "status": "running",
                            "simulation": SIMULATION,
                            "evidence": [
                                f"{profile}-{case}/trace.zip",
                                f"{profile}-{case}/observations.json",
                            ],
                        }
                        scenarios.append(row)
                        (output / "scenarios.json").write_text(
                            json.dumps(scenarios, indent=2) + "\n"
                        )
                        try:
                            await run_case(browser, state, endpoint["id"], output, profile, case)
                            row["status"] = "passed"
                        except BaseException as exc:
                            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                            raise
                        finally:
                            (output / "scenarios.json").write_text(
                                json.dumps(scenarios, indent=2) + "\n"
                            )
            finally:
                await browser.close()
    finally:
        for release in state.releases.values():
            release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)
        (output / "provider-events.json").write_text(json.dumps(state.events, indent=2) + "\n")
    print(
        "passed: desktop/phone Aide stop, early stop, selection, completion, navigation, incognito SQLite isolation"
    )


if __name__ == "__main__":
    asyncio.run(run())
