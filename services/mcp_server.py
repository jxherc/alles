"""3d - alles AS an MCP server: a JSON-RPC 2.0 handler that exposes the 3a capability registry as
MCP tools, so an external agent (Claude Desktop, another alles) can drive this instance.

transport-agnostic: `handle(req)` takes one decoded JSON-RPC message and returns the response dict
(or None for notifications). the HTTP route feeds it; a stdio launcher could reuse it verbatim.
"""

import json

from core.database import DelegatedAction, SessionLocal
from services.agent_tools import MUTATING_TOOLS
from services.delegated_actions import (
    ActionRequest,
    begin_action,
    finish_action,
    hash_arguments,
    matching_grant,
    request_action,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "alles", "version": "1.0.0"}
_BOOTSTRAPPED = False


def _capabilities():
    from services import capabilities

    global _BOOTSTRAPPED
    if not _BOOTSTRAPPED or not capabilities.all():
        capabilities.bootstrap()
        _BOOTSTRAPPED = True
    return capabilities


def _scope(params: dict) -> tuple[str, str]:
    value = params.get("scope") if isinstance(params.get("scope"), dict) else {}
    kind, scope_id = str(value.get("kind") or "general"), str(value.get("id") or "")
    if kind != "general" or scope_id:
        raise ValueError("mcp_scope_not_bound")
    return kind, scope_id


def _request(name: str, arguments: dict, params: dict) -> ActionRequest:
    scope_kind, scope_id = _scope(params)
    return ActionRequest(
        origin="tool",
        scope_kind=scope_kind,
        scope_id=scope_id,
        capability=f"tool:{name}",
        action="mcp.call",
        target=name,
        data_summary=", ".join(sorted(str(key)[:64] for key in arguments))[:2000],
        privacy_effect="tool input and output are untrusted external data",
        cost="unknown",
        arguments_hash=hash_arguments(arguments),
        mutating=name in MUTATING_TOOLS,
    )


def _tool_list(params: dict):
    capabilities = _capabilities()
    db = SessionLocal()
    out = []
    try:
        for c in capabilities.all(kind="tool"):
            try:
                request = _request(c.name, {}, params)
            except ValueError:
                break
            if not matching_grant(db, request):
                continue
            out.append(
                {
                    "name": c.name,
                    "description": c.description or "",
                    "inputSchema": c.schema or {"type": "object", "properties": {}},
                }
            )
        db.commit()
    finally:
        db.close()
    out.sort(key=lambda t: t["name"])
    return out


async def _call(name, arguments, params):
    capabilities = _capabilities()
    if not capabilities.get(name, "tool"):
        return {
            "content": [{"type": "text", "text": f"unknown capability: tool:{name}"}],
            "isError": True,
        }
    try:
        request = _request(name, arguments or {}, params)
    except ValueError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    db = SessionLocal()
    try:
        action, allowed = request_action(db, request)
        db.commit()
        db.refresh(action)
        if not allowed:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"approval required in Alles (action {action.id})",
                    }
                ],
                "isError": True,
                "approval": {"action_id": action.id, "exact_hash": action.exact_hash},
            }
        begin_action(db, action, request)
        db.commit()
        res = await capabilities.invoke(name, arguments or {})
        action = db.get(DelegatedAction, action.id)
        is_err = isinstance(res, dict) and bool(res.get("error"))
        finish_action(db, action, success=not is_err, outcome_known=True)
        db.commit()
    except Exception as e:
        db.rollback()
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    finally:
        db.close()
    text = res if isinstance(res, str) else json.dumps(res)
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
        result = {"tools": _tool_list(params)}
    elif method == "tools/call":
        result = await _call(params.get("name", ""), params.get("arguments") or {}, params)
    elif method == "ping":
        result = {}
    elif is_notification:
        return None  # any other notification: accept silently
    else:
        return _err(rid, -32601, f"method not found: {method}")

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}
