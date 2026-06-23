"""3d - alles AS an MCP server: a JSON-RPC 2.0 handler that exposes the 3a capability registry as
MCP tools, so an external agent (Claude Desktop, another alles) can drive this instance.

transport-agnostic: `handle(req)` takes one decoded JSON-RPC message and returns the response dict
(or None for notifications). the HTTP route feeds it; a stdio launcher could reuse it verbatim.
"""

import json

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "alles", "version": "1.0.0"}


def _tool_list():
    from services import capabilities

    capabilities.bootstrap()
    out = []
    for c in capabilities.all(kind="tool"):
        out.append(
            {
                "name": c.name,
                "description": c.description or "",
                "inputSchema": c.schema or {"type": "object", "properties": {}},
            }
        )
    out.sort(key=lambda t: t["name"])
    return out


async def _call(name, arguments):
    from services import capabilities

    capabilities.bootstrap()
    try:
        res = await capabilities.invoke(name, arguments or {})
    except Exception as e:
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    text = res if isinstance(res, str) else json.dumps(res)
    is_err = isinstance(res, dict) and bool(res.get("error"))
    return {"content": [{"type": "text", "text": text}], "isError": is_err}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def handle(req):
    """one JSON-RPC message -> response dict, or None for a notification (no id)."""
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        result = {"tools": _tool_list()}
    elif method == "tools/call":
        result = await _call(params.get("name", ""), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    elif is_notification:
        return None  # any other notification: accept silently
    else:
        return _err(rid, -32601, f"method not found: {method}")

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}
