# AGENTS.md - alles project context

Auto-loaded into agent mode (the cross-tool standard, like CLAUDE.md for Claude Code). Keep it short.

## what this is
Self-hosted personal workspace. Alles is the ecosystem; Aide is the AI app inside it.
Python 3.11 + FastAPI + SQLite + vanilla JS ES modules, no build step.
Run: `python app.py` or `alles start` -> http://localhost:8000

## layout
- `app.py` — FastAPI entry, routers, lifespan
- `routes/` — one APIRouter per file, prefix `/api`
- `services/` — llm.py (streaming), agent_runtime.py + agent_tools.py (agent mode), crypto, memory, research
- `core/` — database.py (all models + migrations), settings.py, auth.py
- `static/` — index.html SPA, style.css, js/ (one ES module per feature)

## conventions
- new DB table: add model to `core/database.py`, `create_all()` handles it
- new column on existing table: use `_add_col()` in `init_db()`
- frontend: ES module per feature, imported via app.js; state in module-level `_vars`
- after mutations reload the full list, no optimistic UI
- SSE streaming: `data: {json}\n\n`, `[DONE]` sentinel
- keep comments minimal and informal, don't over-engineer

## design tokens (don't break these)
bg #0a0a0a, text #e8e6e3, muted #6e6e6e, accent #818cf8, error #f87171, green #4ade80
border-radius 2-3px max, no shadows/gradients, transitions only on color/border/background

## alles = ecosystem of per-app sites (subdomains)
One server, subdomain-aware single SPA. `static/js/subdomain.js` holds the
`SUBDOMAIN_VIEWS` map: apex = the hub; `aide` = the AI (chat/agent/memory/compare/
brain/models/reminders/AI gallery); each other app on its own subdomain (mail, docs,
calendar, tasks, files, contacts, secrets, gallery). `notes` and `photos` remain
compatibility aliases for `docs` and `gallery`. `app.js`
`applySubdomainScope()` scopes the sidebar; `navigateTo` cross-jumps between
subdomains. Works today on `aide.localhost:8000` etc. (no DNS).
- auth across subdomains: `Domain=localhost` cookies aren't sent to `*.localhost`,
  so login is host-only per subdomain + a one-time `/api/auth/handoff` code relays
  the session on cross-nav (log in once). `base_domain` setting (env `BASE_DOMAIN`).
- real domain: set `BASE_DOMAIN=dom` (cookie gets `Domain=dom; Secure`) + a Caddy
  wildcard: `*.dom, dom { reverse_proxy 127.0.0.1:8000 }` (needs DNS-challenge cert).

## checks
- python: `python -c "import ast; ast.parse(open('FILE').read())"` for a quick syntax check
- js: `node --check static/js/FILE.js`
- tests: `python -m unittest discover -s tests` (56 tests)
