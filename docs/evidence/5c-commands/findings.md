# stage 5c - declarative command/hotkey registry - audit findings (2026-06-23)

## current state
- `static/js/palette.js` exists (a command palette) but commands, hotkeys, and context-menu actions are
  declared in separate ad-hoc places. there is NO single command registry that all three surfaces read
  from, and no shared hotkey-combo parser/matcher.

## scope (testable core)
one declarative command registry: register {id, title, keywords, hotkey, group, run}; search/rank;
parse + match a hotkey combo against a keyboard event; run by id. DEFERRED: wiring palette.js / a global
keydown listener / context menus to it (DOM glue, done when the views adopt it).

## fix - new `static/js/commands.js` (vanilla ESM, no DOM deps -> node-testable)
- `createRegistry()` -> { register, all, search, run, matchHotkey, byGroup }.
- `register(cmd)` keyed by id (re-register overwrites).
- `search(q)` ranks by title prefix > title substring > keyword match.
- `parseHotkey('mod+k')` -> normalized combo; `matchHotkey(event)` -> the command whose hotkey matches
  (mod = ctrl OR meta, so it's cross-platform).
- `run(id, ctx)` invokes the command's run().

tested: register/all, search title + keyword + ranking, overwrite by id, hotkey parse + match (mod=ctrl/
meta), shift/alt combos, no-match, run invokes, run unknown returns false, byGroup filter.
