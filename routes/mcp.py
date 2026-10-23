"""
MCP server management — store configs, connect/disconnect, list tools.
Actual MCP protocol calls use the `mcp` package if available.
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.auth import require_recent_owner
from core.database import McpServer, SessionLocal, get_db
from services import mcp_oauth
from services.mcp_client import AuthNeeded, HttpClient, McpError, StdioClient

# the connected-session + tool registry lives in a leaf module so services/agent_tools.py can
# read it without importing routes.mcp (which would close a routes->services->routes cycle)
from services.mcp_registry import sessions as _sessions  # server_id -> mcp ClientSession
from services.mcp_registry import tools as _tools  # server_id -> [{name, description, schema}]
from services.redaction import redact_args, redact_url

router = APIRouter(prefix="/api")
# outside /api: an auth server fetches this without a sign-in
public = APIRouter()
log = logging.getLogger("aide.mcp")

# in-memory connected sessions
_stacks: dict[str, object] = {}  # server_id -> AsyncExitStack, or the built-in client
# server_id -> {"state": connected|needs_sign_in|error, "error", "challenge", "era", "version"}
_status: dict[str, dict] = {}
TRANSPORTS = {"stdio", "http", "sse"}


def _fmt(s: McpServer) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "transport": s.transport,
        "command": s.command,
        "args": redact_args(s.args_list()),
        "url": redact_url(s.url),
        "env": {key: "***" for key in s.env_dict()},
        "headers": {key: "***" for key in s.headers_dict()},
        "enabled": s.enabled,
        "connected": s.id in _sessions,
        "state": _status.get(s.id, {}).get("state", "connected" if s.id in _sessions else "off"),
        "error": _status.get(s.id, {}).get("error", ""),
        "era": _status.get(s.id, {}).get("era", ""),
        "signed_in": s.transport == "http" and mcp_oauth.signed_in(s.id),
        "tools": _enabled_tools(s),
        "disabled_tools": s.disabled_tools_list(),
    }


def _disabled_set(s: McpServer) -> set[str]:
    return {str(x) for x in s.disabled_tools_list()}


def _enabled_tools(s: McpServer) -> list[dict]:
    disabled = _disabled_set(s)
    return [t for t in _tools.get(s.id, []) if t.get("name") not in disabled]


# GET /api/mcp/servers
@router.get("/mcp/servers")
def list_servers(db: DbSession = Depends(get_db)):
    return [_fmt(s) for s in db.query(McpServer).all()]


# 3d - alles AS an MCP server: JSON-RPC channel exposing our own capability registry
@router.post("/mcp/rpc")
async def mcp_rpc(req: dict):
    from services import mcp_server

    resp = await mcp_server.handle(req)
    if resp is None:  # notification - no response body
        return Response(status_code=204)
    return JSONResponse(resp)


class AddServer(BaseModel):
    name: str
    transport: str = "stdio"  # stdio | http (streamable) | sse (old, needs the mcp package)
    command: str = ""
    args: list[str] = []
    url: str = ""
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


_CONFIG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")


def _validated_config(body: AddServer) -> tuple[list[str], dict[str, str], dict[str, str]]:
    if body.transport not in TRANSPORTS:
        raise HTTPException(400, "transport must be stdio, http or sse")
    if body.transport in ("http", "sse") and not re.match(r"^https?://", body.url.strip(), re.I):
        raise HTTPException(400, "a remote server needs an http(s) url")
    if body.transport == "stdio" and not body.command.strip():
        raise HTTPException(400, "a local server needs a command")
    if not body.name.strip() or len(body.name) > 120:
        raise HTTPException(400, "name is required and must be at most 120 characters")
    if len(body.command) > 1024 or len(body.url) > 8192 or len(body.args) > 64:
        raise HTTPException(400, "MCP configuration is too large")
    args = [str(value) for value in body.args]
    if any(len(value) > 4096 for value in args):
        raise HTTPException(400, "MCP argument is too large")

    def mapping(values: dict[str, str], label: str) -> dict[str, str]:
        if len(values) > 64:
            raise HTTPException(400, f"too many MCP {label} values")
        result = {}
        for raw_key, raw_value in values.items():
            key, value = str(raw_key), str(raw_value)
            if not _CONFIG_NAME.fullmatch(key) or len(value) > 16384:
                raise HTTPException(400, f"invalid MCP {label} value")
            result[key] = value
        return result

    return args, mapping(body.env, "environment"), mapping(body.headers, "header")


def _stdio_env(configured: dict[str, str]) -> dict[str, str]:
    allowed = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result.update(configured)
    return result


# 10d — one-click connector presets (curated; args interpolate {placeholders} from params)
MCP_PRESETS = [
    {
        "id": "filesystem",
        "name": "Filesystem",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{root}"],
        "description": "Read/write files under a folder (set {root}).",
    },
    {
        "id": "github",
        "name": "GitHub",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "description": "GitHub repos, issues, PRs — add GITHUB_TOKEN to this server's MCP environment.",
    },
    {
        "id": "brave",
        "name": "Brave Search",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "description": "Web search — add BRAVE_API_KEY to this server's MCP environment.",
    },
    {
        "id": "sqlite",
        "name": "SQLite",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "{db_path}"],
        "description": "Query a local SQLite database (set {db_path}).",
    },
    {
        "id": "fetch",
        "name": "Fetch",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
        "description": "Fetch and read web pages as markdown.",
    },
]


@router.get("/mcp/presets")
def list_presets():
    return MCP_PRESETS


class PresetParams(BaseModel):
    params: dict = {}


@router.post("/mcp/presets/{preset_id}", dependencies=[Depends(require_recent_owner)])
async def add_preset(preset_id: str, body: PresetParams = None, db: DbSession = Depends(get_db)):
    p = next((x for x in MCP_PRESETS if x["id"] == preset_id), None)
    if not p:
        raise HTTPException(404, "unknown preset")
    params = (body.params if body else {}) or {}

    def _fill(a):
        try:
            return a.format(**params)
        except (KeyError, IndexError):
            return a  # leave unknown placeholders for the user to edit

    args = [_fill(a) for a in p["args"]]
    return await add_server(
        AddServer(name=p["name"], transport=p["transport"], command=p["command"], args=args), db
    )


# POST /api/mcp/servers
@router.post("/mcp/servers", dependencies=[Depends(require_recent_owner)])
async def add_server(body: AddServer, db: DbSession = Depends(get_db)):
    args, env, headers = _validated_config(body)
    s = McpServer(
        name=body.name.strip(),
        transport=body.transport,
        command=body.command,
        args=json.dumps(args),
        url=body.url,
        env=json.dumps(env),
        headers=json.dumps(headers),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    # try to connect immediately
    await _connect(s.id, db)
    return _fmt(s)


# DELETE /api/mcp/servers/{id}
@router.delete("/mcp/servers/{sid}", dependencies=[Depends(require_recent_owner)])
async def delete_server(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(McpServer, sid)
    if not s:
        raise HTTPException(404)
    await _disconnect(sid)
    mcp_oauth.forget(sid)
    _status.pop(sid, None)
    db.delete(s)
    db.commit()
    return {"ok": True}


# POST /api/mcp/servers/{id}/connect
@router.post("/mcp/servers/{sid}/connect", dependencies=[Depends(require_recent_owner)])
async def connect_server(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(McpServer, sid)
    if not s:
        raise HTTPException(404)
    ok, err = await _connect(sid, db)
    if not ok and _status.get(sid, {}).get("state") != "needs_sign_in":
        raise HTTPException(502, err)
    return _fmt(s)


class SignIn(BaseModel):
    client_id: str = ""
    client_secret: str = ""


# POST /api/mcp/servers/{id}/sign-in -> {"url"} to open in the browser
@router.post("/mcp/servers/{sid}/sign-in", dependencies=[Depends(require_recent_owner)])
async def sign_in(sid: str, request: Request, body: SignIn = None, db: DbSession = Depends(get_db)):
    s = db.get(McpServer, sid)
    if not s or s.transport != "http":
        raise HTTPException(404, "no remote server here")
    header = _status.get(sid, {}).get("challenge", "")
    if not header:
        # ask the server what it wants; a 401 carries the hints
        client = HttpClient(s.url, headers=s.headers_dict())
        try:
            await client.open()
            return {"url": "", "detail": "this server doesn't need a sign-in"}
        except AuthNeeded as need:
            header = need.challenge
        except Exception:
            header = ""
        finally:
            await client.aclose()
    redirect = _callback_url(request)
    given = {
        "client_id": (body.client_id if body else "").strip(),
        "client_secret": (body.client_secret if body else "").strip(),
    }
    try:
        url = await mcp_oauth.begin(sid, s.url, header, redirect, given)
    except mcp_oauth.OAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.warning("MCP sign-in start failed: %s", type(exc).__name__)
        raise HTTPException(502, "couldn't reach the sign-in server") from exc
    return {"url": url}


def _callback_url(request: Request) -> str:
    origin = mcp_oauth._public_origin()
    if origin:
        return f"{origin}/api/mcp/oauth/callback"
    return str(request.url_for("mcp_oauth_callback"))


@router.post("/mcp/servers/{sid}/sign-out", dependencies=[Depends(require_recent_owner)])
async def sign_out(sid: str):
    await _disconnect(sid)
    mcp_oauth.forget(sid)
    _status[sid] = {"state": "needs_sign_in", "error": ""}
    return {"ok": True}


def _sign_in_page(ok: bool, detail: str) -> HTMLResponse:
    from html import escape

    title = "connected" if ok else "sign-in didn't finish"
    message = (
        "the server is connected. you can close this tab and go back to alles."
        if ok
        else f"{escape(detail)}. go back to alles settings and try again."
    )
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><body style='background:#0b0b0b;color:#ededed;"
        "font:16px system-ui;padding:48px 20px;max-width:42rem;margin:auto'>"
        f"<h1 style='font-size:22px;font-weight:600'>{title}</h1><p>{message}</p></body></html>",
        status_code=200 if ok else 400,
    )


@router.get("/mcp/oauth/callback", name="mcp_oauth_callback")
async def oauth_callback(code: str = "", state: str = "", iss: str = "", error: str = ""):
    try:
        sid = await mcp_oauth.finish(state, code, iss, error)
    except mcp_oauth.OAuthError as exc:
        return _sign_in_page(False, str(exc))
    except Exception as exc:
        log.warning("MCP sign-in finish failed: %s", type(exc).__name__)
        return _sign_in_page(False, "couldn't reach the sign-in server")
    db = SessionLocal()
    try:
        ok, err = await _connect(sid, db)
    finally:
        db.close()
    return _sign_in_page(ok, err or "signed in, but the server still refused")


@public.get("/oauth/mcp-client.json")
def client_metadata():
    """alles's OAuth client id document; only exists when alles has a public https address."""
    origin = mcp_oauth._public_origin()
    if not origin:
        raise HTTPException(404)
    return mcp_oauth.public_client(origin)


REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"


def _short_name(full: str) -> str:
    """io.github.someone/notes -> notes; com.notion/mcp -> notion (a bare "mcp" says nothing)."""
    space, _, last = full.rpartition("/")
    if last.lower() in {"mcp", "server", "mcp-server"} and space:
        return space.split(".")[-1]
    return last or full


def _registry_item(entry: dict) -> dict | None:
    server = entry.get("server") or {}
    remotes = [
        {
            "url": r.get("url", ""),
            "headers": [h.get("name", "") for h in r.get("headers") or [] if h.get("isRequired")],
        }
        for r in server.get("remotes") or []
        if r.get("type") == "streamable-http"
        and str(r.get("url", "")).startswith("https://")
        and "{" not in r.get("url", "")
    ]
    packages = []
    for pkg in server.get("packages") or []:
        kind, name, version = (
            pkg.get("registryType"),
            pkg.get("identifier", ""),
            pkg.get("version", ""),
        )
        if (pkg.get("transport") or {}).get("type", "stdio") != "stdio" or not name:
            continue
        if kind == "npm":
            command, args = "npx", ["-y", f"{name}@{version}" if version else name]
        elif kind == "pypi":
            command, args = "uvx", [f"{name}=={version}" if version else name]
        else:
            continue
        env = [
            e.get("name", "") for e in pkg.get("environmentVariables") or [] if e.get("isRequired")
        ]
        packages.append({"command": command, "args": args, "env": env})
    if not remotes and not packages:
        return None
    return {
        "name": server.get("title") or _short_name(server.get("name", "")),
        "id": server.get("name", ""),
        "description": (server.get("description") or "")[:240],
        "version": server.get("version", ""),
        "repository": (server.get("repository") or {}).get("url", ""),
        "remotes": remotes[:2],
        "packages": packages[:2],
    }


# GET /api/mcp/registry?q= -> servers from the official MCP registry
@router.get("/mcp/registry")
async def search_registry(q: str = "", cursor: str = ""):
    import httpx

    params = {"limit": 30, "version": "latest"}
    if q.strip():
        params["search"] = q.strip()[:80]
    if cursor:
        params["cursor"] = cursor[:200]
    try:
        # the registry is slow (often 15s+), so give it room
        async with httpx.AsyncClient(timeout=35) as http:
            response = await http.get(REGISTRY, params=params)
        data = response.json() if response.status_code == 200 else {}
    except Exception as exc:
        log.warning("MCP registry search failed: %s", type(exc).__name__)
        raise HTTPException(502, "couldn't reach the MCP registry") from exc
    items = [i for i in (_registry_item(e) for e in data.get("servers") or []) if i]
    return {"items": items, "next": (data.get("metadata") or {}).get("nextCursor", "")}


# POST /api/mcp/servers/{id}/disconnect
@router.post("/mcp/servers/{sid}/disconnect", dependencies=[Depends(require_recent_owner)])
async def disconnect_server(sid: str, db: DbSession = Depends(get_db)):
    await _disconnect(sid)
    return {"ok": True}


class ToolCall(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict = {}


# POST /api/mcp/call
@router.post("/mcp/call")
async def call_tool(body: ToolCall, db: DbSession = Depends(get_db)):
    session = _sessions.get(body.server_id)
    if not session:
        raise HTTPException(400, "server not connected")
    s = db.get(McpServer, body.server_id)
    if s and body.tool_name in _disabled_set(s):
        raise HTTPException(403, "tool disabled")
    try:
        result = await session.call_tool(body.tool_name, body.arguments)
        return {"result": str(result)}
    except Exception as exc:
        log.warning("MCP tool call failed: %s", type(exc).__name__)
        raise HTTPException(500, "MCP tool call failed") from exc


# ── internal connect/disconnect ───────────────────────────────────────────────


async def _connect(server_id: str, db) -> tuple[bool, str]:
    s = db.get(McpServer, server_id)
    if not s:
        return False, "not found"
    await _disconnect(server_id)
    if s.transport in ("stdio", "http"):
        return await _connect_builtin(s)
    if s.transport != "sse":
        return False, "transport must be stdio, http or sse"
    # the old http+sse transport (deprecated by the spec) still uses the optional mcp package
    try:
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.sse import sse_client

        stack = AsyncExitStack()
        try:
            if not (s.url or "").strip():
                return False, "url required for sse transport"
            read, write = await stack.enter_async_context(
                sse_client(s.url, headers=s.headers_dict())
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools_resp = await session.list_tools()
            _sessions[server_id] = session
            _stacks[server_id] = stack
            disabled = _disabled_set(s)
            _tools[server_id] = [
                {"name": t.name, "description": t.description or "", "schema": t.inputSchema}
                for t in tools_resp.tools
                if t.name not in disabled
            ]
            _status[server_id] = {"state": "connected", "error": "", "era": "legacy"}
            log.info(f"MCP connected: {s.name} ({len(_tools[server_id])} tools)")
            return True, ""
        except Exception:
            await stack.aclose()
            raise
    except ImportError:
        return _failed(
            server_id,
            "the old sse transport needs the mcp package; use http if the server supports it",
        )
    except Exception as exc:
        log.warning("MCP connect failed for %s: %s", s.name, type(exc).__name__)
        return _failed(server_id, "MCP connection failed; check the server configuration and logs")


def _failed(server_id: str, error: str) -> tuple[bool, str]:
    _status[server_id] = {"state": "error", "error": error}
    return False, error


async def _connect_builtin(s: McpServer) -> tuple[bool, str]:
    sid = s.id
    if s.transport == "stdio":
        client = StdioClient(s.command, s.args_list(), _stdio_env(s.env_dict()))
    else:
        client = HttpClient(s.url, headers=s.headers_dict(), token=lambda: mcp_oauth.token_for(sid))
    try:
        await client.open()
        tools = await client.list_tools()
    except AuthNeeded as need:
        await client.aclose()
        _status[sid] = {"state": "needs_sign_in", "error": "", "challenge": need.challenge}
        return False, "this server needs you to sign in"
    except FileNotFoundError:
        await client.aclose()
        return _failed(sid, f"couldn't find the command {s.command!r} on this machine")
    except (McpError, TimeoutError, ConnectionError) as exc:
        await client.aclose()
        tail = getattr(client, "stderr_tail", [])[-1:]
        detail = str(exc) or type(exc).__name__
        return _failed(
            sid, f"the MCP server didn't start: {detail}" + (f" ({tail[0][:160]})" if tail else "")
        )
    except Exception as exc:
        await client.aclose()
        log.warning("MCP connect failed for %s: %s", s.name, type(exc).__name__)
        return _failed(sid, "MCP connection failed; check the server configuration and logs")
    disabled = _disabled_set(s)
    _sessions[sid] = client
    _stacks[sid] = client
    _tools[sid] = [
        {
            "name": t.get("name", ""),
            "description": t.get("description") or "",
            "schema": t.get("inputSchema") or {},
        }
        for t in tools
        if t.get("name") not in disabled
    ]
    _status[sid] = {"state": "connected", "error": "", "era": client.era, "version": client.version}
    log.info(
        "MCP connected: %s (%s tools, %s %s)", s.name, len(_tools[sid]), client.era, client.version
    )
    return True, ""


async def _disconnect(server_id: str):
    session = _sessions.pop(server_id, None)
    stack = _stacks.pop(server_id, None)
    _tools.pop(server_id, None)
    if stack:
        try:
            await stack.aclose()
            return
        except Exception:
            pass
    if session:
        try:
            await session.aclose()
        except Exception:
            pass


async def connect_all():
    """called on startup — reconnect all enabled servers"""
    db = SessionLocal()
    try:
        servers = db.query(McpServer).filter(McpServer.enabled == True).all()
        for s in servers:
            await _connect(s.id, db)
    finally:
        db.close()
