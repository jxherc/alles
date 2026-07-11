"""
MCP server management — store configs, connect/disconnect, list tools.
Actual MCP protocol calls use the `mcp` package if available.
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.auth import require_recent_owner
from core.database import McpServer, SessionLocal, get_db

# the connected-session + tool registry lives in a leaf module so services/agent_tools.py can
# read it without importing routes.mcp (which would close a routes->services->routes cycle)
from services.mcp_registry import sessions as _sessions  # server_id -> mcp ClientSession
from services.mcp_registry import tools as _tools  # server_id -> [{name, description, schema}]
from services.redaction import redact_args, redact_url

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.mcp")

# in-memory connected sessions
_stacks: dict[str, object] = {}  # server_id -> AsyncExitStack (only used here)


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
    transport: str = "stdio"  # stdio | sse
    command: str = ""
    args: list[str] = []
    url: str = ""
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


_CONFIG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")


def _validated_config(body: AddServer) -> tuple[list[str], dict[str, str], dict[str, str]]:
    if body.transport not in {"stdio", "sse"}:
        raise HTTPException(400, "transport must be stdio or sse")
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
    if not ok:
        raise HTTPException(502, err)
    return _fmt(s)


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
    try:
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        try:
            if s.transport == "stdio":
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                args = s.args_list()
                params = StdioServerParameters(
                    command=s.command, args=args, env=_stdio_env(s.env_dict())
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif s.transport == "sse":
                from mcp.client.sse import sse_client

                if not (s.url or "").strip():
                    return False, "url required for sse transport"
                read, write = await stack.enter_async_context(
                    sse_client(s.url, headers=s.headers_dict())
                )
            else:
                return False, "transport must be stdio or sse"

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
            log.info(f"MCP connected: {s.name} ({len(_tools[server_id])} tools)")
            return True, ""
        except Exception:
            await stack.aclose()
            raise
    except ImportError:
        return False, "mcp package not installed — pip install mcp"
    except Exception as exc:
        log.warning("MCP connect failed for %s: %s", s.name, type(exc).__name__)
        return False, "MCP connection failed; check the server configuration and logs"


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
