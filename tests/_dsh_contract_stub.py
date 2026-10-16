"""Contract-faithful local DSH mobile bridge stub for browser verification."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DshContractStub:
    def __init__(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def json(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if self.path == "/mobile/api/pair/payload":
                    self.json(200, {"v": 2, "h": [stub.base_url], "sid": "browser-pair"})
                else:
                    self.json(404, {"error": "not-found"})

            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                request = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/mobile/api/pair/claim":
                    if request == {"sid": "browser-pair", "code": "12345678"}:
                        self.json(200, {"ok": True, "token": stub.token})
                    else:
                        self.json(403, {"error": "wrong code"})
                    return
                prefix = "/mobile/api/proxy/"
                if not self.path.startswith(prefix):
                    self.json(404, {"error": "not-found"})
                    return
                if self.headers.get("authorization") != f"Bearer {stub.token}":
                    self.json(401, {"error": "unauthorized"})
                    return
                method = self.path.removeprefix(prefix)
                payload = request.get("payload") or {}
                stub.paths.append(self.path)
                value = stub.call(method, payload)
                self.json(
                    200,
                    {
                        "type": "server-response",
                        "rpcId": request.get("rpcId"),
                        "result": {"ok": True, "value": value},
                    },
                )

        self.token = "synthetic-browser-token"
        self.paths = []
        self.sessions = {}
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", int(os.environ.get("ALLES_DSH_STUB_PORT", "0"))), Handler
        )
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, payload):
        if method == "host.describe":
            return {
                "version": "stub-0.2.0",
                "cwd": "/tmp/stub",
                "attachedSessions": sum(
                    1 for session in self.sessions.values() if session["running"]
                ),
                "home": "/tmp",
                "canOpenPath": False,
            }
        if method == "workspace.list":
            return {
                "items": [
                    {
                        "workspaceId": "workspace-1",
                        "path": "/tmp/alles-stub",
                        "title": "Alles · local stub",
                        "sessionIds": list(self.sessions),
                    }
                ],
                "archivedSessionIds": [],
            }
        if method == "session.create":
            session_id = payload["sessionId"]
            self.sessions.setdefault(session_id, {"running": False, "blank": True, "events": []})
            return {"sessionId": session_id, "agentPreset": "default"}
        if method == "session.prompt":
            session = self.sessions[payload["sessionId"]]
            session.update(running=True, blank=False)
            sequence = len(session["events"])
            session["events"].extend(
                [
                    {"event": {"type": "user/message", "seq": sequence, "time": 1, "data": {}}},
                    {"event": {"type": "turn/start", "seq": sequence + 1, "time": 2, "data": {}}},
                ]
            )
            return {"accepted": True}
        if method == "session.list":
            return {
                "items": [
                    {
                        "sessionId": session_id,
                        "updatedAt": 1,
                        "running": session["running"],
                        "blank": session["blank"],
                        "cwd": "/tmp/alles-stub",
                    }
                    for session_id, session in self.sessions.items()
                ]
            }
        if method == "session.history":
            return {"events": list(self.sessions[payload["sessionId"]]["events"]), "hasMore": False}
        if method == "session.cancel":
            session = self.sessions[payload["sessionId"]]
            session["running"] = False
            session["events"].append(
                {
                    "event": {
                        "type": "turn/end",
                        "seq": len(session["events"]),
                        "time": 3,
                        "data": {
                            "turn": 1,
                            "reason": {"kind": "aborted", "reason": {"kind": "user"}},
                        },
                    }
                }
            )
            return {"accepted": True}
        raise AssertionError(f"unexpected DSH method {method}")

    def complete(self, session_id):
        session = self.sessions[session_id]
        session["running"] = False
        session["events"].extend(
            [
                {
                    "event": {
                        "type": "assistant/message",
                        "seq": len(session["events"]),
                        "time": 3,
                        "data": {
                            "message": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "fixed the synthetic lifecycle test; focused checks passed.",
                                    }
                                ]
                            }
                        },
                    }
                },
                {
                    "event": {
                        "type": "tool/result",
                        "seq": len(session["events"]) + 1,
                        "time": 3,
                        "data": {},
                    },
                    "view": {
                        "for": "result",
                        "view": {
                            "card": "diff",
                            "title": "updated lifecycle test",
                            "diffs": [
                                {
                                    "path": "tests/lifecycle.py",
                                    "oldText": "assert pending",
                                    "newText": "assert completed",
                                }
                            ],
                        },
                    },
                },
            ]
        )
        session["events"].append(
            {
                "event": {
                    "type": "turn/end",
                    "seq": len(session["events"]),
                    "time": 4,
                    "data": {"turn": 1, "reason": {"kind": "completed"}},
                }
            }
        )
