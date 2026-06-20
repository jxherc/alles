# 10d — custom assistants: audit

## Persona (core/database.py:312)
Columns: id, name, emoji, system_prompt, model, temperature, default_mode, accent, initial_message,
is_default. `Session.persona_id` FK. Applied in `routes/chat.py` (`_resolve_persona` 52, model 59,
temperature 372/452, **system_prompt full-replace 135**, mode 73). `agent_runtime` has no persona refs.
**No knowledge-files concept exists.**

## 1a share (services/share.py)
`mint(db,kind,ref,level="view")` (idempotent), `lookup`, `token_for`, `revoke`, `revoke_ref`,
`md_to_html`. `Share(token,kind,ref,level)`. `VALID_KINDS = {doc,file,folder,photo,album,contact,event,
session}` (share.py:14). `/s/{token}` (routes/shared.py:97) dispatches on kind → add a `"persona"` branch.

## MCP (routes/mcp.py + McpServer core/database.py:148)
`McpServer(name,transport,command,args,url,enabled,disabled_tools)`. Endpoints: GET/POST
`/api/mcp/servers`, DELETE `/{sid}`, connect/disconnect, `/api/mcp/call`. Connection state in-memory.
**No presets** → add `MCP_PRESETS` + `GET /api/mcp/presets` + `POST /api/mcp/presets/{id}`.

## 1c index (services/textindex.py) — reuse with kind=`persona:<id>`
`index(db,kind,ref,text)`, `search(db,query,kind,k)`, `remove(db,kind,ref)`, `reindex_kind`, `stats`.

## Tests
`test_api_personas.py` (ApiTest), `test_api_mcp.py` (mocks `routes.mcp._connect` async stub),
`test_share.py` (service + ApiTest). New models auto-created by `create_all`.

## 10d plan
- **10d-1** persona knowledge files: `PersonaDoc` + `services/persona_docs.py` (attach/list/detach/purge/
  knowledge_block over `persona:<id>` index) + endpoints + chat.py injects the knowledge block + cascade
  on persona delete.
- **10d-2** persona share (1a "persona" kind + `/s/{token}` bundle page) + MCP one-click presets.
- **10d-3** frontend: persona editor knowledge-files + share; MCP presets one-click in connections UI.

---

## 10d implementation + regression (resumed run)

Strict TDD, ruff + node-check clean (no new lint errors in touched files).

- **10d-1 persona knowledge files** — `PersonaDoc` + `services/persona_docs.py` (attach/list/detach/
  purge/knowledge_block over the 1c `persona:<id>` index) + `/api/personas/{pid}/docs` CRUD; chat.py
  injects the relevant knowledge chunks into a persona's system prompt; deleting a persona purges its
  docs + chunks. 10 unit tests.
- **10d-2 persona share + MCP presets** — `persona` added to 1a `VALID_KINDS`; `/s/{token}` renders a
  read-only assistant bundle; `POST/DELETE /api/personas/{pid}/share`. `MCP_PRESETS` (filesystem/github/
  brave/sqlite/fetch) + `GET /api/mcp/presets` + `POST /api/mcp/presets/{id}` (param interpolation). 10 tests.
- **10d-3 frontend** — persona editor knowledge-files section (add/list/remove) + share action; MCP
  one-click presets row in the tools pane. 9 Playwright assertions, 0 console errors. Stamps v74 / SW v48.

## Regression
16 subdomains 0 console errors (`docs/evidence/10d/regression/`). Full suite: 1653 tests OK.
