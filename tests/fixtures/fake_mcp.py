"""a pretend MCP server for tests.

stdio: `python fake_mcp.py modern|legacy`. http: `Handler` with `Handler.era` and `Handler.auth`.
it has one tool, `echo`, plus `region_echo` whose region is mirrored into a header.
"""

import base64
import hashlib
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

MODERN = "2026-07-28"
TOOLS = [
    {
        "name": "echo",
        "description": "say it back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {
        "name": "region_echo",
        "description": "say the region back",
        "inputSchema": {
            "type": "object",
            "properties": {"region": {"type": "string", "x-mcp-header": "Region"}},
        },
    },
    {
        "name": "broken",
        "description": "bad header annotation",
        "inputSchema": {
            "type": "object",
            "properties": {"n": {"type": "number", "x-mcp-header": "N"}},
        },
    },
]


def answer(era: str, message: dict, state: dict, headers: dict | None = None):
    """(result, error) for one request, or None for a notification."""
    method, params = message.get("method"), message.get("params") or {}
    if "id" not in message:
        if method == "notifications/initialized":
            state["ready"] = True
        return None
    meta = params.get("_meta") or {}
    if era == "modern":
        if method == "initialize":
            return None, {"code": -32601, "message": "use server/discover; I speak 2026-07-28"}
        if meta.get("io.modelcontextprotocol/protocolVersion") != MODERN:
            return None, {"code": -32022, "message": "unsupported", "data": {"supported": [MODERN]}}
        if method == "server/discover":
            return {
                "resultType": "complete",
                "supportedVersions": [MODERN],
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "fake", "version": "1"}},
            }, None
    else:
        if method == "initialize":
            state["ready"] = False
            return {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-old"},
            }, None
        if not state.get("ready"):
            return None, {"code": -32002, "message": "not initialized"}
    if method == "tools/list":
        return {"tools": TOOLS, "resultType": "complete", "ttlMs": 0, "cacheScope": "private"}, None
    if method == "tools/call":
        args = params.get("arguments") or {}
        if params.get("name") == "region_echo":
            got = (headers or {}).get("mcp-param-region", "(none)")
            return {
                "content": [{"type": "text", "text": f"region {args.get('region')} header {got}"}]
            }, None
        return {
            "content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}],
            "resultType": "complete",
        }, None
    return None, {"code": -32601, "message": "method not found"}


def stdio(era: str):
    state = {}
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if era == "silent-legacy" and message.get("method") == "server/discover":
            continue  # some old servers never answer unknown methods
        out = answer("legacy" if era == "silent-legacy" else era, message, state)
        if out is None:
            continue
        result, error = out
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        reply.update({"error": error} if error else {"result": result})
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


class Handler(BaseHTTPRequestHandler):
    era = "modern"
    auth = False  # when True, every MCP request needs "Bearer good-token"
    sse = False  # answer requests as an event stream
    sessions: dict = {}
    seen: list = []
    codes: dict = {}  # code -> challenge

    def _send(self, status, body=None, headers=None, kind="application/json"):
        raw = (
            b""
            if body is None
            else (body if isinstance(body, bytes) else json.dumps(body).encode())
        )
        self.send_response(status)
        if raw:
            self.send_header("content-type", kind)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path == "/.well-known/oauth-protected-resource/mcp":
            return self._send(
                200,
                {
                    "resource": f"{self.base}/mcp",
                    "authorization_servers": [self.base],
                    "scopes_supported": ["tools"],
                },
            )
        if path.path == "/.well-known/oauth-authorization-server":
            return self._send(
                200,
                {
                    "issuer": self.base,
                    "authorization_endpoint": f"{self.base}/authorize",
                    "token_endpoint": f"{self.base}/token",
                    "registration_endpoint": f"{self.base}/register",
                    "code_challenge_methods_supported": ["S256"],
                    "authorization_response_iss_parameter_supported": True,
                },
            )
        if path.path == "/authorize":
            q = dict(urllib.parse.parse_qsl(path.query))
            Handler.seen.append(("authorize", q))
            code = "code-" + q["state"][:6]
            Handler.codes[code] = (q["code_challenge"], q.get("resource"))
            target = (
                q["redirect_uri"]
                + "?"
                + urllib.parse.urlencode({"code": code, "state": q["state"], "iss": self.base})
            )
            return self._send(302, None, {"location": target})
        self._send(405)

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        path = urllib.parse.urlsplit(self.path).path
        if path == "/register":
            Handler.seen.append(("register", json.loads(raw)))
            return self._send(201, {"client_id": "client-1"})
        if path == "/token":
            form = dict(urllib.parse.parse_qsl(raw.decode()))
            Handler.seen.append(("token", form))
            challenge, resource = Handler.codes.pop(form.get("code"), (None, None))
            digest = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if challenge != digest or form.get("resource") != resource:
                return self._send(400, {"error": "invalid_grant"})
            return self._send(
                200, {"access_token": "good-token", "expires_in": 3600, "refresh_token": "r1"}
            )
        if path != "/mcp":
            return self._send(404)
        if self.auth and self.headers.get("authorization") != "Bearer good-token":
            challenge = f'Bearer resource_metadata="{self.base}/.well-known/oauth-protected-resource/mcp", scope="tools"'
            return self._send(401, {"error": "unauthorized"}, {"WWW-Authenticate": challenge})
        message = json.loads(raw)
        headers = {k.lower(): v for k, v in self.headers.items()}
        Handler.seen.append(("mcp", message.get("method"), headers))
        if self.era == "modern" and message.get("method") != "initialize":
            if headers.get("mcp-method") != message.get("method"):
                return self._send(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32020, "message": "header mismatch"},
                    },
                )
        extra = {}
        if self.era == "legacy":
            sid = headers.get("mcp-session-id", "")
            if message.get("method") == "initialize":
                sid = f"s{len(Handler.sessions) + 1}"
                Handler.sessions[sid] = {}
                extra["Mcp-Session-Id"] = sid
            elif sid not in Handler.sessions:
                return self._send(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32000,
                            "message": "Bad Request: No valid session ID provided",
                        },
                    },
                )
            state = Handler.sessions[sid]
        else:
            state = {}
        out = answer(self.era, message, state, headers)
        if out is None:
            return self._send(202)
        result, error = out
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        reply.update({"error": error} if error else {"result": result})
        if self.sse:
            body = f": hello\n\nevent: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {}})}\n\ndata: {json.dumps(reply)}\n\n"
            return self._send(200, body.encode(), extra, kind="text/event-stream")
        status = (
            404
            if error and error["code"] == -32601 and self.era == "modern"
            else (400 if error else 200)
        )
        self._send(status, reply, extra)

    def do_DELETE(self):
        Handler.sessions.pop(self.headers.get("mcp-session-id", ""), None)
        self._send(200)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    stdio(sys.argv[1] if len(sys.argv) > 1 else "modern")
