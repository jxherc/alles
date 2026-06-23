# stage 3a - unified capability/action registry - audit findings (2026-06-23)

## current state - capabilities are scattered across 3 unrelated shapes
- **agent tools**: `agent_tools.TOOL_DEFS` (27) + `APP_TOOL_DEFS` (34) + `GITHUB_TOOL_DEFS` (10) +
  COMPUTER/SUBAGENT defs, each an OpenAI-style `{"type":"function","function":{name,description,
  parameters}}`. permission scope lives SEPARATELY in `TOOL_PERMISSION` (47 entries: name -> scope).
  dispatch is one big `async execute(name, args)` if/elif (line 1088).
- **automation actions**: `automations.ACTIONS` - a bare tuple of 6 names ("create_task", "push",
  "create_note", "push_digest", "notify", "notify_digest"), no schema, fired by `_fire`.
- **skills**: `skills_store.match_skills` - markdown skills, separate again.

there is NO single place that answers "what can this system DO?" with name + input schema + permission
scope + tags. every future platform feature (3b permission layer, 3d MCP server, 3h API scopes) needs
that catalog and today would have to re-scrape three different shapes.

## the gap
- one `Capability {name, kind, description, schema, scope, tags, executor}` record + a registry keyed by
  (kind, name).
- a `bootstrap()` that POPULATES it from the existing tool defs + TOOL_PERMISSION + ACTIONS WITHOUT
  touching execute()/run_automations() (reuse-over-rebuild: additive index first, dedupe later).
- a single `invoke(name, args)` entry point for tools (delegates to agent_tools.execute) + an
  observability endpoint.

## fix - new `services/capabilities.py`
- `Capability` dataclass + `register/get/all(kind=,scope=,tag=)/clear`.
- `bootstrap()` (idempotent): merge every `*_TOOL_DEFS` list -> tool capabilities (schema from the def,
  scope from TOOL_PERMISSION), + ACTIONS -> action capabilities. tags = (kind, scope).
- `invoke(name, args)` -> await agent_tools.execute for tools.
- route GET /api/capabilities (list + filter by kind/scope/tag) for observability.
- app startup calls bootstrap().

tested: register/get/all/filtering, duplicate overwrite, bootstrap coverage (every TOOL_PERMISSION tool
+ every ACTION registered, idempotent), schema carried, scope carried, invoke delegates to execute.
