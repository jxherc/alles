"""Aide makes a project folder from a General chat, in the real page, in WebKit.

A loopback model calls project_create on a new folder, then write_file into it. The gate checks
the folder and the file exist, the chat moved into the project, and the header shows the project
right after the turn without a reload. The server must run with a throwaway HOME: the tool only
makes folders inside the home folder or on a drive.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import _require_throwaway_data_root, api

sys.path.insert(0, str(Path.cwd()))
from services.appearance import from_legacy  # noqa: E402

PORT = os.environ.get("PORT", "8992")
URL = f"http://aide.localhost:{PORT}/"
SIZES = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
    "phone": {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True},
}
GREETING = "made by aide in a project folder\n"


def throwaway_home() -> Path:
    home = Path.home().resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if temp not in home.parents:
        raise RuntimeError("run this gate with HOME set to a throwaway folder")
    return home


class ProjectModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    folders = {}  # the user's message names the folder: "make <path>"

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        messages = request.get("messages") or []
        if not request.get("stream"):
            payload = json.dumps({"choices": [{"message": {"content": "project check"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        ask = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        folder = str(ask).split("make ", 1)[-1].strip()
        results = sum(1 for m in messages if m.get("role") == "tool")
        if results == 0:
            call = ("project_create", {"path": folder})
        elif results == 1:
            call = ("write_file", {"path": f"{folder}/hello.txt", "content": GREETING})
        else:
            call = None
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        if call:
            tool = {
                "index": 0,
                "id": f"call_{results}",
                "type": "function",
                "function": {"name": call[0], "arguments": json.dumps(call[1])},
            }
            chunks = [
                {"choices": [{"delta": {"tool_calls": [tool]}}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"content": "done: the project is ready."}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        try:
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def run():
    _require_throwaway_data_root()
    home = throwaway_home()
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS") or tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProjectModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = api(
        "POST",
        "/api/models/endpoint",
        {
            "name": "project fixture",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "provider_adapter": "manual",
        },
    )["id"]
    api("PATCH", f"/api/models/endpoint/{endpoint}", {"models": ["maker"]})
    api("POST", "/api/setup/dismiss", {})
    api(
        "PATCH",
        "/api/settings",
        {
            "default_endpoint_id": endpoint,
            "default_model": "maker",
            "model_roles": {},
            "memory_policy": "off",
            "memory_auto_inject": False,
            "intent_suggestions": False,
            "auto_compact": False,
            "agent_permission_mode": "full_auto",
        },
    )
    rows = []
    try:
        with sync_playwright() as pw:
            browser = pw.webkit.launch()
            for size, options in SIZES.items():
                for theme in ("dark", "light"):
                    profile = f"webkit-{size}-{theme}"
                    record = {"profile": profile, "status": "failed"}
                    rows.append(record)
                    api("PUT", "/api/appearance", from_legacy(theme, None))
                    context = browser.new_context(service_workers="block", **options)
                    errors = []
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "console",
                        lambda m: errors.append(m.text) if m.type == "error" else None,
                    )
                    try:
                        folder = home / "Work" / f"test-{size}-{theme}"
                        assert not folder.exists(), folder
                        sid = api(
                            "POST",
                            "/api/sessions",
                            {
                                "name": profile,
                                "model": "maker",
                                "endpoint_id": endpoint,
                                "mode": "jarvis",
                            },
                        )["id"]
                        page.goto("about:blank")
                        page.goto(f"{URL}#{sid}", wait_until="networkidle")
                        shown = page.evaluate("document.documentElement.dataset.theme || 'dark'")
                        assert shown == theme, (shown, theme)
                        label = page.locator("#aide-project-context-label")
                        expect(page.locator("#composer-ta")).to_be_visible()
                        before = (label.text_content() or "").strip()
                        assert before != folder.name, before
                        background = page.evaluate(
                            "getComputedStyle(document.body).backgroundColor"
                        )
                        record["background"] = background
                        page.locator("#composer-ta").fill(f"make {folder}")
                        page.keyboard.press("Enter")
                        expect(page.locator("#messages .ai-content").last).to_contain_text(
                            "the project is ready", timeout=30000
                        )
                        expect(label).to_have_text(folder.name, timeout=10000)
                        # the owner opens the conversation settings to see where this chat works
                        page.locator("#aide-more-btn").click()
                        page.locator('[data-aide-central-action="options"]').click()
                        expect(label).to_be_visible()
                        if not (folder / "hello.txt").exists():
                            steps = [
                                m["meta"].get("tool_steps")
                                for m in api("GET", f"/api/sessions/{sid}/history")["messages"]
                            ]
                            raise AssertionError(f"no file; steps: {steps}")
                        assert (folder / "hello.txt").read_text() == GREETING
                        history = api("GET", f"/api/sessions/{sid}/history")["session"]
                        assert history["project_id"], history
                        projects = [p for p in api("GET", "/api/projects") if p["working_dir"]]
                        assert any(p["working_dir"] == str(folder) for p in projects), projects
                        box = label.bounding_box()
                        width = options["viewport"]["width"]
                        assert 0 <= box["x"] and box["x"] + box["width"] <= width, box
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        page.screenshot(path=str(out / f"{profile}.png"))
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
        shutil.rmtree(home / "Work", ignore_errors=True)
    backgrounds = {r["profile"].rsplit("-", 1)[1]: r.get("background") for r in rows}
    print(json.dumps(rows, indent=1))
    if len(
        {r.get("background") for r in rows if "dark" in r["profile"]}
        & {r.get("background") for r in rows if "light" in r["profile"]}
    ):
        raise SystemExit(f"themes did not switch: {backgrounds}")
    if any(r["status"] != "passed" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
