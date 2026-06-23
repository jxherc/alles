"""3b - one composed permission gate. layers (first deny wins):
    1. disabled tools (settings / turn-level)
    2. persona policy (blocked scopes or blocked tool names)
    3. decide_permission (mode + user path/tool rules)

scope comes from the 3a capability registry (falls back to TOOL_PERMISSION), so the per-tool scope
finally drives decisions instead of just sitting in a table.
"""


def scope_for(name):
    """the permission scope of a tool, via the capability registry (TOOL_PERMISSION fallback)."""
    from services import capabilities

    cap = capabilities.get(name, "tool")
    if cap and cap.scope:
        return cap.scope
    from services.agent_tools import TOOL_PERMISSION

    return TOOL_PERMISSION.get(name, "")


def _csv(s):
    return {x.strip().lower() for x in (s or "").split(",") if x.strip()}


def persona_blocks(name, persona):
    """does this persona forbid the tool - by its scope or by its exact name?"""
    if not persona:
        return False
    if name in _csv(getattr(persona, "blocked_tools", "")):
        return True
    scope = scope_for(name)
    return bool(scope) and scope in _csv(getattr(persona, "blocked_scopes", ""))


def gate(name, args, *, mode, rules, persona=None, disabled=()):
    """unified allow|ask|deny for one tool call."""
    if name in (disabled or ()):
        return "deny"
    if persona_blocks(name, persona):
        return "deny"
    from services.agent_tools import decide_permission

    return decide_permission(name, args, mode, rules)
