"""
MCP server management — store configs, connect/disconnect, list tools.
Actual MCP protocol calls use the `mcp` package if available.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import McpServer, SessionLocal, get_db

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.mcp")

# in-memory connected sessions
_sessions: dict[str, object] = {}  # server_id -> mcp ClientSession
_tools: dict[str, list] = {}  # server_id -> [{name, description, schema}]
_stacks: dict[str, object] = {}  # server_id -> AsyncExitStack


def _fmt(s: McpServer) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "transport": s.transport,
        "command": s.command,
        "args": s.args_list(),
        "url": s.url,
        "enabled": s.enabled,
        "connected": s.id in _sessions,
        "tools": _tools.get(s.id, []),
        "disabled_tools": s.disabled_tools_list(),
    }


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
        "description": "GitHub repos, issues, PRs — needs GITHUB_TOKEN in the environment.",
    },
    {
        "id": "brave",
        "name": "Brave Search",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "description": "Web search — needs BRAVE_API_KEY.",
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


@router.post("/mcp/presets/{preset_id}")
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
@router.post("/mcp/servers")
async def add_server(body: AddServer, db: DbSession = Depends(get_db)):
    s = McpServer(
        name=body.name,
        transport=body.transport,
        command=body.command,
        args=json.dumps(body.args),
        url=body.url,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    # try to connect immediately
    await _connect(s.id, db)
    return _fmt(s)


# DELETE /api/mcp/servers/{id}
@router.delete("/mcp/servers/{sid}")
async def delete_server(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(McpServer, sid)
    if not s:
        raise HTTPException(404)
    await _disconnect(sid)
    db.delete(s)
    db.commit()
    return {"ok": True}


# POST /api/mcp/servers/{id}/connect
@router.post("/mcp/servers/{sid}/connect")
async def connect_server(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(McpServer, sid)
    if not s:
        raise HTTPException(404)
    ok, err = await _connect(sid, db)
    if not ok:
        raise HTTPException(502, err)
    return _fmt(s)


# POST /api/mcp/servers/{id}/disconnect
@router.post("/mcp/servers/{sid}/disconnect")
async def disconnect_server(sid: str, db: DbSession = Depends(get_db)):
    await _disconnect(sid)
    return {"ok": True}


class ToolCall(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict = {}


# POST /api/mcp/call
@router.post("/mcp/call")
async def call_tool(body: ToolCall):
    session = _sessions.get(body.server_id)
    if not session:
        raise HTTPException(400, "server not connected")
    try:
        result = await session.call_tool(body.tool_name, body.arguments)
        return {"result": str(result)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── internal connect/disconnect ───────────────────────────────────────────────


async def _connect(server_id: str, db) -> tuple[bool, str]:
    s = db.get(McpServer, server_id)
    if not s:
        return False, "not found"
    await _disconnect(server_id)
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if s.transport == "stdio":
            args = s.args_list()
            params = StdioServerParameters(command=s.command, args=args)
            # we store the context manager — connect lazily when tools needed
            # for now just probe by connecting + listing tools
            from contextlib import AsyncExitStack

            stack = AsyncExitStack()
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools_resp = await session.list_tools()
            _sessions[server_id] = session
            _stacks[server_id] = stack
            _tools[server_id] = [
                {"name": t.name, "description": t.description or "", "schema": t.inputSchema}
                for t in tools_resp.tools
            ]
            log.info(f"MCP connected: {s.name} ({len(_tools[server_id])} tools)")
            return True, ""
        else:
            return False, "SSE transport not yet supported"
    except ImportError:
        return False, "mcp package not installed — pip install mcp"
    except Exception as e:
        log.warning(f"MCP connect failed for {s.name}: {e}")
        return False, str(e)


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
