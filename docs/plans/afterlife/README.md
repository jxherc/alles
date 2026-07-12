# Stage 6 — Afterlife

- **Status:** current; Phase 4 delivered, Phase 5 next
- **Started:** July 11, 2026
- **Meaning:** preserve what works, repair what is unsafe, and give Alles one coherent new life

Alles reached a first life with many partially usable features. Purgatory left those features spread
across overlapping plans, branches, and product ideas. Afterlife is the deliberate rebuild after that
point.

Afterlife is not a rewrite from scratch. It keeps real user data, proven capabilities, compatible links,
and the current FastAPI/SQLite/vanilla-JavaScript stack.

## Current product shape

- **Today** — the daily home.
- **Aide** — one AI home containing Chat and Jarvis task modes.
- **Andromeda** — fast search with normal results and a grounded AI Overview.
- **Projects** — a selected folder that becomes Aide and Jarvis's prioritized working environment.
- **Specialist sections** — Plan, Docs, Files, Finance, Inbox, Library, Health, Passwords, and Server.

Jarvis lives inside Aide. It remains the name of the durable background runtime and Discord bot.

## Start here

- [Full product and architecture design](design.md)
- [Implementation phases](phases/README.md)
- [All project stages](../README.md)
- [Current shipped specifications](../../../specifications.md)

## Current state

Phases 0–4 are delivered with fresh recovery, migration, compatibility, browser, and full-suite
evidence. The Afterlife branch now ships one Aide Chat/Jarvis home, conclusion-first tool work, visible
memory controls, and links-first Andromeda search with an optional grounded AI Overview. The candidate
SearXNG definition is pinned and loopback-only, but installation stays disabled because no supported
container runtime was available for the live spike; external HTTPS SearXNG and other providers remain
usable. Phase 5 — Jarvis inside Aide and channels — is next. The broader product design remains open to
changes as later gates are implemented.

## Stage rules

- New future plans live in this folder.
- Use `decision-<topic>.md` for a product or architecture decision.
- Use `phases/phase-XX-<topic>.md` for an implementation plan.
- Every plan states **draft**, **ready**, **in progress**, **blocked**, **delivered**, or **replaced**.
- A plan becomes **delivered** only after fresh tests and evidence.
- Update `specifications.md` only after behavior ships.
- Never delete legacy data in the same release that first introduces its replacement.
