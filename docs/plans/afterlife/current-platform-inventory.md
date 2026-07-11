# Current Aide platform inventory

Recorded on 2026-07-11 for the Afterlife Phase 0 baseline.

This is a code-only inventory. It did not open `.env`, `data/`, `settings.json`, a database, a vault,
MCP arguments, prompts, memories, or any other private content. Counts come from the model, route,
registry, and test definitions named below.

## Snapshot

| Area | Current code surface |
|---|---|
| MCP | 1 saved-server model, 2 transports, 5 presets, and 9 API routes |
| Memory | 1 durable memory model and 10 API routes, plus a separate personal-recall index |
| Personas | 1 persona model, 1 linked-document model, 5 starters, and 10 API routes |
| Aide tools | 81 declared tool definitions; 82 registry tools after the `bash` alias is added |
| Automation actions | 6 names in the shared registry |

## MCP

### What is saved

`McpServer` stores `id`, `name`, `transport`, `command`, JSON `args`, `url`, `enabled`, JSON
`disabled_tools`, and `created_at`. This inventory records only the field names, not any saved values.

- Supported client transports: `stdio` and `sse`.
- The 5 presets are `filesystem`, `github`, `brave`, `sqlite`, and `fetch`.
- Enabled servers reconnect on startup.
- Live client sessions and discovered tool schemas exist only in process memory.
- A saved `disabled_tools` list hides and blocks exact tool names for that server.
- Aide reaches peers through `mcp_list_tools` and `mcp_call_tool`.
- Alles also acts as an MCP server through JSON-RPC at `/api/mcp/rpc`.

The 9 routes cover list, add, delete, connect, disconnect, direct call, presets, and inbound JSON-RPC.
The current Settings UI exposes list, add, preset, status, and remove.

### Current gaps

- Newly discovered peer tools are usable unless already named in `disabled_tools`; there is no
  General-Aide, Project, or Workflow grant model.
- `enabled` and `disabled_tools` are saved, but there is no API/UI editor for them. There is also no
  edit, refresh, or explicit test control in Settings.
- Command, arguments, and URL are stored as normal database text. There is no shared encrypted MCP
  credential record yet.
- Inbound `/api/mcp/rpc` lists all 82 registry tools and calls `capabilities.invoke()` directly. It
  does not use the chat agent's feature filtering, persona policy, mode, per-tool rules, or approval
  wait. Normal HTTP authentication still applies when auth is enabled, but that is not a tool grant.
- MCP schemas and results are wrapped as untrusted content when Aide calls them. The direct inbound
  MCP path does not add the chat approval boundary before executing a tool.

Sources: `core/database.py`, `routes/mcp.py`, `services/mcp_registry.py`, `services/mcp_server.py`,
`services/agent_tools.py`, `static/js/settings.js`, `tests/test_api_mcp.py`, and
`tests/test_mcp_server.py`.

## Memory and personal recall

### Durable memory

`Memory` stores `id`, `text`, `category`, `source`, `session_id`, `pinned`, `timestamp`, `confidence`,
`vetoed`, and `provenance`. Known writers currently use these sources:

- `manual` for the memory API;
- `agent` for Aide's `memory_add` tool;
- `extracted` for model-assisted chat extraction;
- `distilled` for the learned user model.

The source and category columns accept free text, so those values are conventions rather than a strict
schema. Search uses local `fastembed` vectors when available and Jaccard keyword matching otherwise.
Pinned memories are injected first. Vetoed memories are hidden from normal search, and distilled facts
also have confidence decay and a veto control.

The 10 routes cover list, add, edit, delete, search, search debugging, extraction, distilled-list,
manual distillation, and veto. The main prompt-related setting keys are:

- `memory_auto_inject` — normal long-term-memory retrieval; default on;
- `user_model_distill` — automatic user-model learning; default off;
- `distilled_auto_inject` — inject accepted distilled facts; default on;
- `insights_auto_inject` and `session_context_inject` — append other learned/session context; default on.

### Separate indexes

- Personal recall is not the `memories` table. It indexes allowed Docs, notes, journal, mail, contacts,
  read-later items, and books in `IndexChunk` records. Aide reads it through `recall`.
- Persona knowledge text is stored in the same text index under `persona:<id>`. `PersonaDoc` keeps only
  its `id`, `persona_id`, title, and creation time.

### Current gaps

- The current policy is not the planned Off/Ask/Auto model. `memory_auto_inject` defaults on, and
  `memory_add` can save directly.
- Incognito skips chat-message persistence, but prompt building still reads memory and an agent run can
  still call `memory_add`. Incognito is therefore not yet a true no-read/no-write memory mode.
- Memory records have no global-vs-Project scope, updated time, trusted-review state, or list of runs
  that used them.
- Model extraction and distillation can create records without the planned owner review queue.
- There is no single export, pause, or clear-all control with provenance reporting yet.

Sources: `core/database.py`, `routes/memory.py`, `routes/chat.py`, `services/memory_store.py`,
`services/user_model.py`, `services/personal_index.py`, `services/persona_docs.py`, and their matching
tests.

## Personas and owner instructions

### Personas

`Persona` stores `id`, `name`, `emoji`, `system_prompt`, pinned `model`, optional `temperature`,
`default_mode`, `blocked_scopes`, `blocked_tools`, `accent`, `initial_message`, `is_default`, and
`created_at`. Personas can be created, edited, duplicated, deleted, shared, and linked to indexed
knowledge documents.

First boot seeds 5 personas once: `aide` (the default), `coder`, `brainstorm`, `editor`, and `tutor`.
The sentinel means deleting them is respected instead of reseeding them on every boot.

Current **None** behavior is not the Afterlife behavior yet. The picker writes a null `persona_id`, but
`_resolve_persona()` then falls back to the row marked `is_default`. With the normal seed, **None still
uses the `aide` persona prompt**. If there is no default row, null really means no persona. Phase 4 must
remove this ambiguity while preserving custom persona data.

### Instruction sources and order

There is no separate `owner_instructions` record today. These are the current instruction sources:

1. Settings key `system_prompt` supplies the editable global prompt.
2. `Project.system_prompt`, when present, is prepended to the global prompt.
3. A non-empty `Persona.system_prompt` replaces both the Project and global prompt.
4. Persona knowledge, memory, insights, distilled facts, session context, and artifact instructions may
   then be appended according to their settings.
5. In agent mode, code-owned agent rules are appended. If `agent_context_files` is on, Alles also reads
   `AGENTS.md`, `AGENT.md`, `aide.md`, and `.aide/instructions.md` from the selected folder and up to 5
   parent levels.

Permission checks are enforced in code, not only by prompt text. However, prompt provenance is not
shown to the owner, a persona can replace the editable global/Project instructions, and there is not yet
a clean stored split between editable owner instructions and immutable safety rules.

Sources: `core/settings.py`, `core/database.py`, `routes/chat.py`, `routes/personas.py`,
`services/agent_runtime.py`, `services/persona_docs.py`, `static/js/app.js`, and persona tests.

## Aide capability coverage

### Declared surfaces

- 27 base tools: files, shell, Git, web, memory, skills, MCP, code inspection, and OpenCode.
- 36 app/browser tools, listed below.
- 2 sub-agent tools, on by default.
- 6 computer-use tools, shown only when enabled.
- 10 GitHub tools, shown only when a GitHub connection exists.

That is 81 unique declared definitions. The registry has 82 tools because it also registers `bash` as
a permissioned alias for `shell`. With default feature settings and no GitHub connection, Aide is offered
65 definitions: 27 base + 36 app + 2 sub-agent.

The 36 current app/browser tools are:

| Area | Exact tool names |
|---|---|
| Calendar | `calendar_list`, `calendar_create`, `calendar_delete` |
| Tasks | `task_list`, `task_add`, `task_done` |
| Docs | `note_list`, `note_read`, `note_write`, `note_append`, `note_search`, `note_backlinks` |
| Contacts | `contact_list`, `contact_add` |
| Mail | `mail_list`, `mail_read`, `mail_send` |
| Books | `book_add`, `books_list` |
| Health | `health_log`, `health_summary` |
| Habits | `habit_add`, `habit_log`, `habits_list` |
| Read later | `read_save`, `read_list` |
| Watch | `watch_add`, `watch_status` |
| Finance | `money_query` |
| Personal recall | `recall` |
| Code recall | `search_code` |
| Browser | `browse_open`, `browse_read`, `browse_click`, `browse_type`, `browse_screenshot` |

The explicit mutation set contains 17 of those 36 app/browser tools: Calendar create/delete; browser
open/click/type; task add/done; note write/append; contact add; mail send; book add; health log; habit
add/log; read save; and watch add. The other 19 are treated as read-only or non-mutating.

The shared registry also catalogs 6 automation action names: `create_task`, `push`, `create_note`,
`push_digest`, `notify`, and `notify_digest`. They have `state` scope, but the registry has no action
executor; the automation service runs them through its own path.

### Approval boundary

For normal interactive agent calls, the order is:

1. deny a turn-disabled tool;
2. deny a persona-blocked exact tool or typed scope;
3. apply the mode and the last matching `permission_rules` entry;
4. wait for an owner decision when the result is `ask`;
5. execute only after the gate allows it.

`plan` hides and denies names in `MUTATING_TOOLS`. `approve` asks for those names. `full_auto` allows
them unless a rule or persona blocks them. A normal chat that is automatically promoted to agent mode
uses `approve`, but the saved default is currently `full_auto`, and detached background runs force
`full_auto` because nobody is present to answer an approval request.

### Current gaps

- 34 of the 36 app/browser tools have no typed scope. Only `recall` and `money_query` have `read`.
  Exact mutation names still receive mode approval, but persona scope blocks cannot cover the unscoped
  tools as a group.
- `memory_add`, `todo_update`, and `revert_file` have write/state scopes but are absent from
  `MUTATING_TOOLS`. Plan/approve mode therefore does not automatically deny/ask for them.
- The registry is a catalog, not a complete service boundary. Direct APIs and inbound MCP do not all
  pass through the interactive Aide approval flow.
- Current actions are uneven: for example, Finance is read-only, Contacts has add but no edit/delete,
  and several apps have no Aide tool yet.
- `agent_allowed_roots` is saved, but the general capability gate does not enforce it as a complete
  Project boundary. File tools use separate secret-path/workspace guards instead.

Sources: `services/agent_tools.py`, `services/capabilities.py`, `services/policy.py`,
`services/agent_runtime.py`, `services/automations.py`, `routes/agent.py`, `tests/test_agent_tools.py`,
`tests/test_capabilities.py`, and `tests/test_policy.py`. See also
[the current trust map](current-trust-map.md).
