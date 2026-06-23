"""3a - unified capability/action registry: one place that catalogs everything the system can DO
(agent tools, automation actions, later skills) with name + input schema + permission scope + tags.

additive on purpose - bootstrap() POPULATES the registry from the existing agent_tools defs +
TOOL_PERMISSION + automations.ACTIONS without touching execute()/run_automations(). later platform
stages (permission layer, MCP server, API scopes) read from here instead of re-scraping 3 shapes.
"""

from dataclasses import dataclass, field


@dataclass
class Capability:
    name: str
    kind: str  # "tool" | "action" | "skill"
    description: str = ""
    schema: dict = field(default_factory=dict)  # JSON schema of inputs
    scope: str = ""  # permission scope
    tags: tuple = ()
    executor: object = None  # optional callable; tools route through agent_tools.execute


_REGISTRY = {}  # (kind, name) -> Capability


def clear():
    _REGISTRY.clear()


def register(cap: Capability):
    _REGISTRY[(cap.kind, cap.name)] = cap
    return cap


def get(name, kind="tool"):
    return _REGISTRY.get((kind, name))


def all(*, kind=None, scope=None, tag=None):
    out = list(_REGISTRY.values())
    if kind is not None:
        out = [c for c in out if c.kind == kind]
    if scope is not None:
        out = [c for c in out if c.scope == scope]
    if tag is not None:
        out = [c for c in out if tag in c.tags]
    return out


def _tool_defs():
    """every agent tool definition across the separate def lists, as (name, description, schema)."""
    from services import agent_tools

    seen, out = set(), []
    for listname in (
        "TOOL_DEFS",
        "APP_TOOL_DEFS",
        "GITHUB_TOOL_DEFS",
        "COMPUTER_TOOL_DEFS",
        "SUBAGENT_TOOL_DEFS",
    ):
        for d in getattr(agent_tools, listname, []):
            fn = d.get("function", d)
            name = fn.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append((name, fn.get("description", ""), fn.get("parameters", {})))
    return out


def bootstrap():
    """populate (idempotent) from the existing tool defs + permissions + automation actions."""
    from services import agent_tools, automations

    perms = agent_tools.TOOL_PERMISSION
    defs = {name: (desc, schema) for name, desc, schema in _tool_defs()}
    # union of every tool name we know about (defs + permission table)
    for name in set(defs) | set(perms):
        desc, schema = defs.get(name, ("", {}))
        scope = perms.get(name, "")
        register(
            Capability(
                name=name,
                kind="tool",
                description=desc,
                schema=schema,
                scope=scope,
                tags=("tool", scope) if scope else ("tool",),
            )
        )
    for a in automations.ACTIONS:
        register(Capability(name=a, kind="action", scope="state", tags=("action", "state")))
    return len(_REGISTRY)


async def invoke(name, args, kind="tool"):
    """run a capability by name. tools delegate to the existing agent_tools dispatcher."""
    cap = get(name, kind)
    if not cap:
        raise KeyError(f"unknown capability: {kind}:{name}")
    if kind == "tool":
        from services import agent_tools

        return await agent_tools.execute(name, args)
    if cap.executor:
        return cap.executor(args)
    raise NotImplementedError(f"no executor for {kind}:{name}")
