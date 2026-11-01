"""`alles ask` and `alles chat`: talk to aide from the terminal through the running server.

Like hermes's `hermes chat -q` and its plain chat loop (hermes-agent 0.22.2+1885.g20acba0,
hermes_cli/_parser.py --query and hermes_cli/cli_single_query.py), but aide answers here, so
the conversation lands in aide's history like any other. Standard library only.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


class ChatError(RuntimeError):
    pass


class Client:
    """JSON over http to the local server, holding the session cookie a password login gives."""

    def __init__(self, base_url: str, ask_password=None):
        self.base = base_url.rstrip("/")
        self.cookie = ""
        self.ask_password = ask_password

    def _request(self, method: str, path: str, body=None, *, stream=False):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "text/event-stream" if stream else "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = f"aide_session={self.cookie}"
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        return urllib.request.urlopen(request, timeout=None if stream else 30)

    def call(self, method: str, path: str, body=None, *, stream=False):
        """One request; a password prompt and one retry when the server asks for the owner."""
        for attempt in range(2):
            try:
                return self._request(method, path, body, stream=stream)
            except urllib.error.HTTPError as exc:
                code, detail = _error(exc)
                if attempt == 0 and code in ("not_authenticated", "recent_auth_required"):
                    self._sign_in(reauth=code == "recent_auth_required")
                    continue
                raise ChatError(detail) from exc
            except urllib.error.URLError as exc:
                raise ChatError("alles isn't answering: alles status") from exc
        raise ChatError("the server keeps asking for the password")

    def _sign_in(self, *, reauth: bool) -> None:
        password = self.ask_password() if self.ask_password is not None else None
        if password is None:  # no keyboard to type it on
            raise ChatError("alles has a password: run this in a terminal to type it")
        if not password:
            raise ChatError("no password, nothing sent")
        path = "/api/auth/reauth" if reauth and self.cookie else "/api/auth/login"
        try:
            with self._request("POST", path, {"password": password}) as response:
                for header in response.headers.get_all("Set-Cookie") or []:
                    name, _, rest = header.partition("=")
                    if name.strip() == "aide_session":
                        self.cookie = rest.split(";", 1)[0]
        except urllib.error.HTTPError as exc:
            raise ChatError(_error(exc)[1]) from exc
        if not self.cookie:
            raise ChatError("the server didn't open a session")

    def json(self, method: str, path: str, body=None) -> dict:
        with self.call(method, path, body) as response:
            return json.loads(response.read() or b"{}")

    def new_session(self, name: str) -> str:
        return str(self.json("POST", "/api/sessions", {"name": name, "mode": "chat"})["id"])

    def drop(self, session_id: str) -> None:
        """Remove a conversation whose first question never got an answer."""
        try:
            self.call("DELETE", f"/api/sessions/{session_id}").close()
        except ChatError:
            pass

    def turn(self, session_id: str, message: str, out) -> str:
        """Send one message and write aide's reply to `out` as it streams; returns the reply."""
        body = {"session_id": session_id, "message": message, "mode": "chat"}
        reply: list[str] = []
        with self.call("POST", "/api/chat", body, stream=True) as response:
            for chunk in events(response):
                if chunk.get("error"):
                    raise ChatError(str(chunk["error"]))
                text = chunk.get("delta")
                if isinstance(text, str) and text:
                    reply.append(text)
                    out.text(text)
                elif isinstance(chunk.get("tool_start"), dict):
                    out.tool(str(chunk["tool_start"].get("name") or "a tool"))
        out.end()
        return "".join(reply)


def events(response):
    """The json objects of a server sent event stream, until [DONE]."""
    for raw in response:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            return
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue
        if isinstance(chunk, dict):
            yield chunk


def _error(exc: urllib.error.HTTPError) -> tuple[str, str]:
    try:
        body = json.loads(exc.read() or b"{}")
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        code, message = detail.get("code", ""), detail.get("message") or detail.get("detail")
    else:
        code, message = (body.get("code", "") if isinstance(body, dict) else ""), detail
    return str(code or ""), str(message or f"the server answered {exc.code}")


class Printer:
    """Writes a streaming reply: text as it comes, tools as one quiet line each."""

    def __init__(self, ui, stream=None):
        self.ui = ui
        self.stream = stream or sys.stdout
        self.at_line_start = True
        self.wrote = False

    def text(self, text: str) -> None:
        self.wrote = True
        self.stream.write(text)
        self.stream.flush()
        self.at_line_start = text.endswith("\n")

    def tool(self, name: str) -> None:
        if not self.at_line_start:
            self.stream.write("\n")
        self.stream.write(self.ui.dim(f"  · {name}") + "\n")
        self.stream.flush()
        self.at_line_start = True

    def end(self) -> None:
        if not self.at_line_start:
            self.stream.write("\n")
            self.stream.flush()
        self.at_line_start = True
