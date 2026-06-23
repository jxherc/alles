# stage 3c - composable tool chains / macros - audit findings (2026-06-23)

## current state
- capabilities can be invoked one at a time (3a `capabilities.invoke`), but there is NO way to define a
  reusable SEQUENCE - a macro that runs several capabilities in order, optionally feeding one step's
  output into the next, saved + replayable atomically. grep confirms no ToolChain/Macro anywhere.
- so a repeated multi-tool workflow (e.g. "grep for X, then read the top hit") has to be re-driven by
  the model every time instead of being a one-call saved chain.

## the gap
- a `ToolChain` (name + ordered steps) the user can save.
- a runner that executes the steps through the 3a invoke path, with simple `{{N.field}}` templating so
  a later step can reference an earlier step's result, stopping on the first error.

## fix
- `ToolChain` model (new table -> create_all, no migration): name + steps_json.
- `services/chains.py`: `run_chain(steps, *, invoke, ctx)` -> renders `{{N}}` / `{{N.key}}` refs from
  prior results, invokes each step, returns {results, ok}; stops at the first failing step.
- routes/chains.py: list/create/delete + POST /chains/{id}/run (uses capabilities.invoke by default).

tested with a stub invoke: ordered run, templating from a prior step, whole-result `{{N}}`, error stops
the chain, empty chain, kind passthrough, missing-ref graceful, non-string args untouched, CRUD + run.
