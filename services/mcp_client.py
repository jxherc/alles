"""a small MCP client that speaks both eras of the protocol, with no extra packages.

modern servers (2026-07-28) are stateless: every request carries its version and client info
in `_meta`, and `server/discover` says what the server supports. legacy servers (2025-11-25
and older) want an `initialize` handshake first and, over http, an Mcp-Session-Id header.
we try modern first and fall back the way the spec describes, then remember the answer for
the life of the connection.

transports: stdio (a local command) and streamable http (a url). the old http+sse transport
is deprecated and still goes through the optional `mcp` package in routes/mcp.py.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
import logging
import re

log = logging.getLogger("aide.mcp")

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
CLIENT = {"name": "alles", "version": "1.0"}
# errors only a modern server sends; anything else from a probe means "legacy"
MODERN_ERRORS = {-32020, -32021, -32022}
UNSUPPORTED_VERSION = -32022
TIMEOUT = 60
DISCOVER_TIMEOUT = 8  # stdio probe; a legacy server may just stay quiet


class McpError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.data = code, data


class AuthNeeded(Exception):
    """the server answered 401 (or 403 insufficient_scope); `challenge` is its WWW-Authenticate."""

    def __init__(self, status: int, challenge: str):
        super().__init__("this server needs you to sign in")
        self.status, self.challenge = status, challenge


def _meta(version: str) -> dict:
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientInfo": CLIENT,
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _header_value(value) -> str:
    """header-safe text; anything else goes as =?base64?…?= (spec: value encoding)."""
    text = ("true" if value else "false") if isinstance(value, bool) else str(value)
    plain = all(0x20 <= ord(c) <= 0x7E or c == "\t" for c in text)
    sentinel = text.startswith("=?base64?") and text.endswith("?=")
    if plain and text == text.strip() and not sentinel:
        return text
    return "=?base64?" + base64.b64encode(text.encode()).decode() + "?="


_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def header_params(schema: dict) -> dict[str, tuple[str, ...]] | None:
    """x-mcp-header annotations -> {header name: property path}; None when the tool is invalid."""
    found: dict[str, tuple[str, ...]] = {}

    def walk(node, path):
        for key, child in (node.get("properties") or {}).items():
            if not isinstance(child, dict):
                continue
            here = path + (key,)
            name = child.get("x-mcp-header")
            if name is not None:
                kind = child.get("type")
                if (
                    not isinstance(name, str)
                    or not _TOKEN.match(name)
                    or kind not in ("string", "integer", "boolean")
                    or name.lower() in {n.lower() for n in found}
                ):
                    raise ValueError(f"bad x-mcp-header {name!r}")
                found[name] = here
            walk(child, here)

    def stray(node, reachable):
        # an annotation anywhere but a plain properties chain makes the tool invalid
        if isinstance(node, dict):
            if "x-mcp-header" in node and not reachable:
                raise ValueError("x-mcp-header outside a properties chain")
            for key, child in node.items():
                if key == "properties" and isinstance(child, dict):
                    for prop in child.values():
                        stray(prop, reachable)
                else:
                    stray(child, False)
        elif isinstance(node, list):
            for child in node:
                stray(child, False)

    try:
        stray({"properties": (schema or {}).get("properties") or {}}, True)
        for key, child in (schema or {}).items():
            if key != "properties":
                stray(child, False)
        walk(schema or {}, ())
    except ValueError as exc:
        log.warning("MCP tool rejected: %s", exc)
        return None
    return found


def result_text(result: dict) -> str:
    """a tools/call result as plain text for the agent."""
    if result.get("resultType") == "input_required":
        asks = [r.get("method", "input") for r in (result.get("inputRequests") or {}).values()]
        return (
            "the MCP server asked for more input ("
            + ", ".join(asks)
            + "), which alles can't give it yet"
        )
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(res.get("text") or f"[resource {res.get('uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[link {item.get('name', '')}: {item.get('uri', '')}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} {item.get('mimeType', '')}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(p for p in parts if p) or "(no output)"
    return ("tool error: " + text) if result.get("isError") else text


class _Client:
    """the protocol on top of a transport's `_request` and `_notify`."""

    def __init__(self):
        self.era = ""
        self.version = MODERN
        self.server_info: dict = {}
        self.instructions = ""
        self._ids = itertools.count(1)
        self._headers: dict[str, dict] = {}  # tool name -> {header: path}

    async def _request(self, method: str, params: dict, extra: dict | None = None) -> dict:
        raise NotImplementedError

    async def _notify(self, method: str, params: dict) -> None:
        raise NotImplementedError

    def _params(self, params: dict) -> dict:
        if self.era == "legacy":
            return params
        return {**params, "_meta": {**(params.get("_meta") or {}), **_meta(self.version)}}

    async def call(self, method: str, params: dict | None = None, extra: dict | None = None):
        params = params or {}
        try:
            return await self._request(method, self._params(params), extra)
        except McpError as exc:
            supported = (exc.data or {}).get("supported") if isinstance(exc.data, dict) else None
            if (
                exc.code == UNSUPPORTED_VERSION
                and self.era == "modern"
                and MODERN not in (supported or [MODERN])
            ):
                raise McpError(
                    exc.code, f"the server speaks {', '.join(supported or [])}, not {MODERN}"
                ) from exc
            raise

    async def open(self) -> None:
        """find out which era the server speaks and get ready to use it."""
        self.era, self.version = "modern", MODERN
        try:
            found = await self._request("server/discover", self._params({}))
            if MODERN in (found.get("supportedVersions") or [MODERN]):
                self.server_info = (found.get("_meta") or {}).get(
                    "io.modelcontextprotocol/serverInfo"
                ) or {}
                self.instructions = found.get("instructions") or ""
                return
            supported = found.get("supportedVersions") or []
        except AuthNeeded:
            raise
        except McpError as exc:
            if exc.code == UNSUPPORTED_VERSION:
                supported = (exc.data or {}).get("supported") if isinstance(exc.data, dict) else []
                if MODERN in (supported or []):
                    raise
            elif exc.code in MODERN_ERRORS:
                raise  # a modern server that didn't like the request; falling back won't help
            else:
                supported = None  # not a modern answer: a legacy server
        except (asyncio.TimeoutError, _Legacy):
            supported = None
        legacy = [v for v in LEGACY if supported is None or v in supported]
        if not legacy:
            raise McpError(UNSUPPORTED_VERSION, f"no shared protocol version (server: {supported})")
        await self._initialize(legacy[0])

    async def _initialize(self, version: str) -> None:
        self.era, self.version = "legacy", version
        self._session_reset()
        result = await self._request(
            "initialize",
            {"protocolVersion": version, "capabilities": {}, "clientInfo": CLIENT},
        )
        self.version = result.get("protocolVersion") or version
        if self.version not in LEGACY:
            raise McpError(
                UNSUPPORTED_VERSION, f"the server picked {self.version}, which alles doesn't speak"
            )
        self.server_info = result.get("serverInfo") or {}
        self.instructions = result.get("instructions") or ""
        await self._notify("notifications/initialized", {})

    def _session_reset(self) -> None:
        pass

    async def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(50):
            page = await self.call("tools/list", {"cursor": cursor} if cursor else {})
            tools += page.get("tools") or []
            cursor = page.get("nextCursor")
            if not cursor:
                break
        kept = []
        for tool in tools:
            schema = tool.get("inputSchema") or {}
            mirrored = header_params(schema) if self.mirrors_headers else {}
            if mirrored is None:
                continue  # spec: drop tools with bad x-mcp-header annotations
            self._headers[tool.get("name", "")] = mirrored
            kept.append(tool)
        return kept

    mirrors_headers = False

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        arguments = arguments or {}
        extra = {}
        for header, path in self._headers.get(name, {}).items():
            value = arguments
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None:
                extra[f"Mcp-Param-{header}"] = _header_value(value)
        result = await self.call("tools/call", {"name": name, "arguments": arguments}, extra)
        return result_text(result)

    async def aclose(self) -> None:
        pass


class _Legacy(Exception):
    """a probe got an answer only a legacy server gives (no json-rpc error at all)."""


# ── stdio ──


class StdioClient(_Client):
    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        super().__init__()
        self.command, self.args, self.env = command, args, env
        self._proc = None
        self._waiting: dict[int, asyncio.Future] = {}
        self._reader = None
        self.stderr_tail: list[str] = []

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read())
        self._errors = asyncio.create_task(self._read_stderr())

    async def open(self) -> None:
        await self.start()
        await super().open()

    async def _read_stderr(self):
        while line := await self._proc.stderr.readline():
            self.stderr_tail = (self.stderr_tail + [line.decode(errors="replace").rstrip()])[-20:]

    async def _read(self):
        try:
            while line := await self._proc.stdout.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "method" in message and "id" in message:
                    # a legacy server asking us something (roots, sampling, ping…)
                    reply = {"jsonrpc": "2.0", "id": message["id"]}
                    if message["method"] == "ping":
                        reply["result"] = {}
                    else:
                        reply["error"] = {"code": -32601, "message": "alles doesn't support that"}
                    await self._write(reply)
                    continue
                future = self._waiting.pop(message.get("id"), None)
                if future and not future.done():
                    future.set_result(message)
        finally:
            for future in self._waiting.values():
                if not future.done():
                    future.set_exception(ConnectionError("the MCP server stopped"))
            self._waiting.clear()

    async def _write(self, message: dict) -> None:
        if self._proc is None or self._proc.returncode is not None:
            raise ConnectionError("the MCP server is not running")
        self._proc.stdin.write((json.dumps(message) + "\n").encode())
        await self._proc.stdin.drain()

    async def _request(self, method: str, params: dict, extra: dict | None = None) -> dict:
        request_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        # the discover probe gets a short wait: a legacy server may just stay quiet
        timeout = DISCOVER_TIMEOUT if method == "server/discover" else TIMEOUT
        try:
            message = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._waiting.pop(request_id, None)
            if method != "server/discover":
                with contextlib.suppress(Exception):
                    await self._notify("notifications/cancelled", {"requestId": request_id})
            raise
        if "error" in message:
            error = message["error"] or {}
            raise McpError(
                int(error.get("code") or 0), str(error.get("message") or "error"), error.get("data")
            )
        return message.get("result") or {}

    async def _notify(self, method: str, params: dict) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def aclose(self) -> None:
        if self._proc and self._proc.returncode is None:
            with contextlib.suppress(Exception):
                self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), 3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
        for task in (self._reader, getattr(self, "_errors", None)):
            if task:
                task.cancel()


# ── streamable http ──


class HttpClient(_Client):
    mirrors_headers = True

    def __init__(self, url: str, headers: dict[str, str] | None = None, token=None):
        """`token` is an async callable that returns a bearer token (or "") for each request."""
        import httpx

        super().__init__()
        self.url = url
        self.headers = dict(headers or {})
        self.token = token
        self.session_id = ""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT, connect=15), follow_redirects=False
        )

    def _session_reset(self) -> None:
        self.session_id = ""

    async def _post(self, body: dict, extra: dict | None = None):
        headers = {
            **self.headers,
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        if self.era == "modern":
            headers["MCP-Protocol-Version"] = self.version
            headers["Mcp-Method"] = body.get("method", "")
            name = (body.get("params") or {}).get("name") or (body.get("params") or {}).get("uri")
            if name and body.get("method") in ("tools/call", "resources/read", "prompts/get"):
                headers["Mcp-Name"] = _header_value(name)
            headers.update(extra or {})
        elif body.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = self.version
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
        if self.token:
            token = await self.token()
            if token:
                headers["authorization"] = f"Bearer {token}"
        request = self._http.build_request("POST", self.url, headers=headers, json=body)
        return await self._http.send(request, stream=True)

    async def _request(self, method: str, params: dict, extra: dict | None = None) -> dict:
        request_id = next(self._ids)
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        response = await self._post(body, extra)
        try:
            if response.status_code in (401, 403) and (
                response.status_code == 401
                or "insufficient_scope" in response.headers.get("www-authenticate", "")
            ):
                raise AuthNeeded(response.status_code, response.headers.get("www-authenticate", ""))
            if (
                response.status_code == 404
                and self.era == "legacy"
                and self.session_id
                and method != "initialize"
            ):
                # the server forgot our session: start a new one and try once more
                await response.aclose()
                await self._initialize(self.version)
                return await self._request(method, params, extra)
            if method == "initialize":
                self.session_id = response.headers.get("mcp-session-id", "")
            kind = response.headers.get("content-type", "")
            if response.status_code >= 400 and "json" not in kind:
                await response.aread()
                if method == "server/discover":
                    raise _Legacy()
                raise McpError(-32000, f"the MCP server answered {response.status_code}")
            if "text/event-stream" in kind:
                message = await self._from_stream(response, request_id)
            else:
                raw = await response.aread()
                try:
                    message = json.loads(raw or b"{}")
                except ValueError:
                    if method == "server/discover":
                        raise _Legacy() from None
                    raise McpError(
                        -32000, "the MCP server sent something that isn't json"
                    ) from None
        finally:
            await response.aclose()
        if not isinstance(message, dict):
            raise McpError(-32000, "unexpected answer from the MCP server")
        if "error" in message:
            error = message["error"] or {}
            raise McpError(
                int(error.get("code") or 0), str(error.get("message") or "error"), error.get("data")
            )
        if method == "server/discover" and "result" not in message:
            raise _Legacy()
        return message.get("result") or {}

    async def _from_stream(self, response, request_id) -> dict:
        data: list[str] = []
        async for line in response.aiter_lines():
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
                continue
            if line.strip() or not data:
                continue
            try:
                message = json.loads("\n".join(data))
            except ValueError:
                message = None
            data = []
            if not isinstance(message, dict):
                continue
            if message.get("id") == request_id and ("result" in message or "error" in message):
                return message
            if "method" in message and "id" in message and self.era == "legacy":
                # legacy servers may ask things mid-stream; say no so they don't hang
                reply = {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": "not supported"},
                }
                with contextlib.suppress(Exception):
                    await (await self._post(reply)).aclose()
        raise ConnectionError("the MCP server closed the stream before answering")

    async def _notify(self, method: str, params: dict) -> None:
        response = await self._post({"jsonrpc": "2.0", "method": method, "params": params})
        await response.aclose()

    async def aclose(self) -> None:
        if self.era == "legacy" and self.session_id:
            with contextlib.suppress(Exception):
                headers = {
                    **self.headers,
                    "Mcp-Session-Id": self.session_id,
                    "MCP-Protocol-Version": self.version,
                }
                await self._http.delete(self.url, headers=headers, timeout=5)
        await self._http.aclose()
