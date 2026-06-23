# stage 3b - permission/policy layer - audit findings (2026-06-23)

## current state
- permission decisions are spread across pieces with no shared gate:
  - `decide_permission(name, args, mode, rules)` (agent_tools:2741) -> allow|ask|deny from the agent
    mode + user path/tool rules. the only thing agent_runtime calls (line 450).
  - `_guard_path` / `_is_secret_path` (agent_tools:140/173) -> filesystem sandbox, called INSIDE
    individual tool implementations, not at the gate.
  - `TOOL_PERMISSION` (now also the 3a registry) -> per-tool scope, but the SCOPE is never used to make
    a decision; decide_permission only keys off MUTATING_TOOLS + name globs.
- personas exist (`Persona` model) with prompt/model/mode/accent but NO policy: a persona cannot
  restrict what tools/scopes it may use. so a "code reviewer" persona can still run `shell` or
  `write_file`. exercised: no field on Persona governs tool access.

## the gap
- a persona-scoped policy: a persona declares blocked scopes (e.g. "shell,write") and/or blocked tool
  names; those are denied regardless of mode.
- one composed gate that layers: disabled-tools -> persona policy (scope/name) -> decide_permission, so
  agent_runtime calls a single function and the scope from 3a actually drives decisions.

## fix
- migration m0006: `Persona.blocked_scopes` + `blocked_tools` (csv TEXT).
- new `services/policy.py`: `scope_for(name)` (reads the 3a registry, falls back to TOOL_PERMISSION),
  `persona_blocks(name, persona)` (scope in blocked_scopes OR name in blocked_tools), `gate(name, args,
  *, mode, rules, persona=None, disabled=())` -> deny if disabled/persona-blocked else decide_permission.
- agent_runtime: load the session's persona + call `policy.gate(...)` instead of decide_permission.
- personas route + model + _fmt: expose blocked_scopes / blocked_tools.

tested: scope_for, persona_blocks by scope + by name + None-persona, gate disabled-deny, gate
persona-deny, gate defers to decide_permission, code-reviewer scenario (blocks shell+write, allows read).
