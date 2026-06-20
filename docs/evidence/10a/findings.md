# 10a — aide code intelligence: audit (code-level, no server boot needed)

## 1c text index (`services/textindex.py`, 92 lines) — reuse target
`index(db, kind, ref, text) -> int` · `remove(db, kind, ref) -> int` ·
`search(db, query, kind=None, k=5) -> [{kind,ref,chunk,score}]` ·
`reindex_kind(db, kind, items: iterable[(ref,text)]) -> int` · `stats(db) -> {kind: count}`.
`IndexChunk` model (core/database.py) auto-created by `create_all`. Embeds via
`memory_store._embed` (fastembed BAAI/bge-small), falls back to Jaccard keyword scoring when
fastembed is absent. `kind` is free-form; docs use `"doc"`, 10a adds `"code"`; `ref` = repo-relative path.

## Agent tools (`services/agent_tools.py`, 2472 lines)
- Tools are dicts via `_tool()`; assembled by `build_tool_defs(settings)`. Dispatch through
  `execute(name, args)` (big if/elif) and `stream_execute(name, args)`.
- File-mutation handlers: `_write_file` (291), `_edit_file` (304), `_apply_patch_text` (338), all
  behind `_guard_path(p, write=True)`. `MUTATING_TOOLS` set (2170).
- Secret-path confinement (`_is_secret_path`/`_guard_path`) + prompt-injection guard
  (`guard_untrusted`, `UNTRUSTED_TOOLS`). `capture_checkpoint`/`revert_run` for one-click revert.

## Agent runtime (`services/agent_runtime.py` 603 ln, `agent_state.py` 192 ln)
- `run_agent(messages, ep, model, stop_event, settings, accumulated, thinking_acc, tool_steps,
  session_id="")` async-gen. `start_run(session_id, model, max_turns, cwd=...)` at ~295; turn loop
  323–598; per-tool `record_event(run_id,"tool_result",step)` ~553 = the **single tool-event choke
  point** (name/args/result/run_id all in scope). Worktree insertion = right after `start_run`,
  before the loop; `finally` teardown.
- `_resolve(path)` and `_stream_shell` both honour `settings["agent_cwd"]` via a contextvar, so
  pointing `agent_cwd` at a worktree redirects every file/shell op with no per-tool changes.
- `Session.working_dir` / `Project.working_dir` columns already exist.

## Automations (`services/automations.py`) — hook target
Rule triggers today: `daily_at`, `sub_renewing`, `day_event_near`, `mail_from`, `doc_tag`.
`on_doc_saved(path, content)` (256) is the event-fire pattern. **No agent-tool trigger yet** → 10a
adds a `"agent_tool"` trigger fired from the run_agent choke point.

## Git worktree — none yet
No `git worktree` usage anywhere. `apply_patch` already assumes a git repo (`(workdir/'.git').exists()`).
Git tools run via shell. 10a adds `_setup_worktree`/`_teardown_worktree` (subprocess `git worktree add/remove`).

## Test conventions
unittest only. Agent-tool tests: `import services.agent_tools as at`, `asyncio.run(at._fn(...))`,
`mock.patch.object(at,"_settings",...)`, tempdirs. Runtime tests script `stream_chat` as a fake async
gen. Textindex tests need an in-memory SQLAlchemy session (StaticPool, like `tests/_client.py`). No server.

## 10a plan
- **10a-1** semantic codebase index: `services/codeindex.py` (walk + index kind="code" + search) +
  `/api/code/reindex` `/api/code/search` + a `search_code` agent tool.
- **10a-2** tool-event hooks: `AutomationRule` `agent_tool` trigger + `fire_tool_hooks()` at the choke point.
- **10a-3** git worktree isolation: `_setup_worktree`/`_teardown_worktree`, gated by `agent_worktree` setting.

---

## 10a implementation + regression (resumed run)

Built depth-first, strict TDD, ruff + node-check clean (no new lint errors in touched files).

- **10a-1 semantic codebase index** — `services/codeindex.py` walks a repo (ext allow-list, skips
  vcs/deps/large), indexes as 1c `kind="code"`, `search()` wraps `textindex.search`. `GET /api/code/search`,
  `POST /api/code/reindex`, and a `search_code` agent tool. Verified live: reindex of the real repo →
  6874 chunks; search returns ranked hits (Jaccard fallback w/o fastembed). 11 tests.
- **10a-2 tool-event hooks** — `AutomationRule` `agent_tool` trigger (fnmatch glob on tool name) +
  `automations.on_agent_tool()` fired from the run_agent per-tool choke point. 10 tests incl. a
  runtime-driven integration test.
- **10a-3 git worktree isolation** — `services/worktrees.py` (is_git_repo / setup / teardown) +
  run_agent repoints `agent_cwd` to a detached worktree when `agent_worktree` is set, tears it down in
  `finally`. 11 tests (tests cap git search with GIT_CEILING_DIRECTORIES since this box keeps %TEMP%
  under a parent repo). 

**Regression:** 16 subdomains 0 console errors (`docs/evidence/10a/regression/`). Full suite: 1611 tests OK.

Note: semantic ranking is keyword-Jaccard until `fastembed` is installed (by design — reuses the 1c
index's fallback). With fastembed present the same code path uses cosine over embeddings.
