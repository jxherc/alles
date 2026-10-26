"""A shutdown ends every open turn at once: the reply is kept as interrupted, held writes land."""

import asyncio
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from core.database import AideCall, Message, ModelEndpoint
from routes import chat
from services import agent_tools, aide_calls
from tests._client import ApiTest

ROOT = Path(__file__).resolve().parent.parent


def _reset_exit_state():
    chat._exiting = False
    chat._streams.clear()
    chat._after_turn.clear()


class ShutdownTurnTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.addCleanup(_reset_exit_state)
        self.settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
            "agent_permission_mode": "approve",
        }
        patch = mock.patch.object(chat, "load_settings", lambda: dict(self.settings))
        patch.start()
        self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(name="held", base_url="http://127.0.0.1:1", cached_models='["held"]')
            db.add(ep)
            db.commit()
            endpoint = ep.id
        folder = tempfile.TemporaryDirectory(prefix="alles-shutdown-task-")
        self.addCleanup(folder.cleanup)
        made = self.client.post(
            "/api/sessions",
            json={
                "name": "held reply",
                "model": "held",
                "endpoint_id": endpoint,
                "working_dir": folder.name,
            },
        )
        self.assertEqual(made.status_code, 200, made.text)
        self.sid = made.json()["id"]

    def history(self):
        return self.client.get(f"/api/sessions/{self.sid}/history").json()["messages"]

    def test_a_held_reply_ends_at_once_kept_as_interrupted_and_held_writes_land(self):
        with self.db() as db:
            call = AideCall(session_id=self.sid, state="connected", connected_at=datetime.now(UTC))
            db.add(call)
            db.commit()
            call_id = call.id

        async def held(messages, *args, **kwargs):
            yield {"delta": "half an answer"}
            # a live call line comes in while the reply runs: it's held for the turn's end
            with self.db() as db:
                aide_calls.append_final_transcript(
                    db,
                    db.get(AideCall, call_id),
                    role="user",
                    text="said during the reply",
                    provider_event_id="e1",
                )
                db.commit()
            asyncio.get_running_loop().call_later(0.1, chat.stop_open_turns)
            await asyncio.sleep(30)  # the model stalls
            yield {"delta": " never sent"}

        started = time.monotonic()
        with mock.patch("services.chat_turn.stream_chat", held):
            response = self.client.post(
                "/api/chat", json={"session_id": self.sid, "message": "hello", "simple": True}
            )
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(response.status_code, 200, response.text)
        rows = self.history()
        self.assertEqual(
            [(m["role"], m["content"]) for m in rows],
            [
                ("user", "hello"),
                ("assistant", "half an answer"),
                ("user", "said during the reply"),
            ],
        )
        self.assertTrue(rows[1]["meta"].get("interrupted"))
        self.assertNotIn(self.sid, chat._streams)

    def test_a_wait_on_the_owner_ends_unanswered(self):
        question = {
            "name": "ask_user",
            "args": {
                "questions": [
                    {
                        "id": "pick",
                        "prompt": "Which one?",
                        "choices": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    }
                ]
            },
        }
        approval = {"name": "shell", "args": {"command": "echo never"}}
        for call in (question, approval):
            with self.subTest(tool=call["name"]):
                chat._exiting = False

                async def waits(messages, *args, call=call, **kwargs):
                    asyncio.get_running_loop().call_later(0.2, chat.stop_open_turns)
                    yield {"tool_call": {"call_id": "c1", **call}}
                    yield {"done": True, "usage": {}}

                started = time.monotonic()
                with mock.patch("services.agent_runtime.stream_chat", waits):
                    response = self.client.post(
                        "/api/chat",
                        json={"session_id": self.sid, "message": "go", "mode": "agent"},
                    )
                self.assertLess(time.monotonic() - started, 5)
                events = [
                    json.loads(line[6:])
                    for line in response.text.splitlines()
                    if line.startswith("data: {")
                ]
                waited = "user_question" if call is question else "tool_permission"
                self.assertTrue(any(waited in e for e in events), events)
                self.assertTrue(any("saved_message" in e for e in events), events)
                self.assertNotIn(self.sid, chat._streams)
        with self.db() as db:
            replies = db.query(Message).filter_by(session_id=self.sid, role="assistant").all()
            self.assertEqual(len(replies), 2)
            self.assertTrue(all("Agent stopped." in m.content for m in replies))

    def test_a_turn_claimed_while_going_down_stops_before_it_starts(self):
        chat.stop_open_turns()
        response = self.client.post(
            "/api/chat", json={"session_id": self.sid, "message": "late", "simple": True}
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "turn_stopped")
        self.assertNotIn(self.sid, chat._streams)


class ShutdownHooksTests(unittest.TestCase):
    def tearDown(self):
        _reset_exit_state()

    def test_a_running_command_is_ended(self):
        async def go():
            with tempfile.TemporaryDirectory() as folder:
                agent_tools.set_agent_ctx(settings={"agent_cwd": folder})
                run = asyncio.create_task(agent_tools._run_shell("sleep 30", folder, "try"))
                for _ in range(200):
                    if agent_tools._running:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(chat.stop_open_turns(), 0)
                return await asyncio.wait_for(run, 5)

        started = time.monotonic()
        result = asyncio.run(go())
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(result["error"])
        self.assertEqual(agent_tools._running, set())

    def test_the_signal_chain_stops_open_turns_then_hands_over(self):
        handed = []
        original = signal.getsignal(signal.SIGTERM)

        async def go():
            signal.signal(signal.SIGTERM, lambda signum, frame: handed.append(signum))
            chat._watching_exit = False
            chat.stop_turns_on_exit()
            chat.stop_turns_on_exit()  # once is enough: no double chain
            running = asyncio.Event()
            self.assertTrue(chat.claim_turn("task-a", running))
            signal.raise_signal(signal.SIGTERM)
            for _ in range(100):
                if running.is_set():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(running.is_set())
            self.assertEqual(handed, [signal.SIGTERM])
            late = asyncio.Event()
            self.assertTrue(chat.claim_turn("task-b", late))
            self.assertTrue(late.is_set())

        try:
            asyncio.run(go())
        finally:
            signal.signal(signal.SIGTERM, original)
            chat._watching_exit = False


class _HeldModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "held"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"held words"}}]}\n\n')
        self.wfile.flush()
        self.server.release.wait(30)  # the model stalls until the test ends


# until app.py's startup calls chat.stop_turns_on_exit() itself, start the real app with it added
_WIRED_START = """
import contextlib, os, uvicorn, app
from routes import chat
inner = app.app.router.lifespan_context
@contextlib.asynccontextmanager
async def lifespan(a):
    async with inner(a):
        chat.stop_turns_on_exit()
        yield
app.app.router.lifespan_context = lifespan
uvicorn.run(app.app, host="127.0.0.1", port=int(os.environ["PORT"]))
"""


@unittest.skipIf(os.name == "nt", "posix signals")
class ShutdownProcessTests(unittest.TestCase):
    def test_sigterm_with_a_held_reply_exits_quickly_and_keeps_the_reply(self):
        model = ThreadingHTTPServer(("127.0.0.1", 0), _HeldModel)
        model.release = threading.Event()
        threading.Thread(target=model.serve_forever, daemon=True).start()
        self.addCleanup(model.server_close)
        self.addCleanup(model.shutdown)
        self.addCleanup(model.release.set)
        data = Path(tempfile.mkdtemp(prefix="alles-shutdown-")).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(data, ignore_errors=True))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        keep = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "SYSTEMROOT")
        env = {k: v for k, v in os.environ.items() if k in keep}
        env.update(
            ALLES_DATA=str(data),
            ALLES_DB=str(data / "aide.db"),
            ALLES_TEST_DATA="1",
            AUTH_ENABLED="false",
            ALLES_HOST="127.0.0.1",
            ALLES_ACCESS_PROFILE="device",
            PORT=str(port),
            PYTHON_DOTENV_DISABLED="1",
            HF_HUB_OFFLINE="1",
        )
        wired = "stop_turns_on_exit()" in (ROOT / "app.py").read_text(encoding="utf-8")
        start = ["app.py"] if wired else ["-c", _WIRED_START]
        with (data / "server.log").open("w") as log:
            server = subprocess.Popen(
                [sys.executable, *start], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        self.addCleanup(lambda: server.poll() is None and server.kill())
        base = f"http://127.0.0.1:{port}"

        def call(method, path, body=None):
            request = urllib.request.Request(
                base + path,
                method=method,
                data=None if body is None else json.dumps(body).encode(),
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read() or b"null")

        deadline = time.monotonic() + 60
        while True:
            try:
                call("GET", "/api/sessions")
                break
            except OSError:
                self.assertIsNone(server.poll(), (data / "server.log").read_text())
                self.assertLess(time.monotonic(), deadline, "the server never came up")
                time.sleep(0.2)
        endpoint = call(
            "POST",
            "/api/models/endpoint",
            {
                "name": "held",
                "base_url": f"http://127.0.0.1:{model.server_address[1]}/v1",
                "auth_type": "none",
            },
        )
        call("PATCH", f"/api/models/endpoint/{endpoint['id']}", {"models": ["held"]})
        task = call(
            "POST",
            "/api/sessions",
            {"name": "held", "model": "held", "endpoint_id": endpoint["id"]},
        )
        seen = []

        def read_reply():
            request = urllib.request.Request(
                base + "/api/chat",
                method="POST",
                headers={"content-type": "application/json"},
                data=json.dumps(
                    {"session_id": task["id"], "message": "hello", "simple": True}
                ).encode(),
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    seen.extend(line.decode().strip() for line in response)
            except OSError as exc:
                seen.append(f"broken: {exc}")
            seen.append("closed")

        reader = threading.Thread(target=read_reply, daemon=True)
        reader.start()
        deadline = time.monotonic() + 20
        while not any("held words" in line for line in seen):
            self.assertLess(time.monotonic(), deadline, seen)
            time.sleep(0.05)

        stopped_at = time.monotonic()
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.fail("the server was still up 15s after SIGTERM")
        self.assertLess(time.monotonic() - stopped_at, 5)
        reader.join(5)
        self.assertIn("closed", seen)
        self.assertTrue(any("saved_message" in line for line in seen), seen)
        with sqlite3.connect(data / "aide.db") as db:
            rows = db.execute(
                "SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY rowid",
                (task["id"],),
            ).fetchall()
        self.assertEqual(
            [(r[0], r[1]) for r in rows], [("user", "hello"), ("assistant", "held words")]
        )
        self.assertTrue(json.loads(rows[1][2]).get("interrupted"))


if __name__ == "__main__":
    unittest.main()
