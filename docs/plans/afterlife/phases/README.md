# Afterlife implementation phases

- **Stage:** Afterlife
- **Current focus:** Phase 3
- **Implementation status:** Phases 0–2 delivered; Phase 3 in progress

These are dependency gates, not release dates. Each phase must be split into small, testable plans before
implementation.

| Phase | Name | Status | Main result |
|---|---|---|---|
| 0 | Recovery gate and baseline | **Delivered** | Encrypted backup/restore, safe defaults, upgrade fixtures, and compatibility baselines |
| 1 | Platform and security foundation | **Delivered** | Access profiles, secrets, service ownership, Server foundation, safe Docs/Files primitives, and backup targets |
| 2 | [Folder Projects and durable Jarvis core](phase-02-projects-jarvis-core.md) | **Delivered** | Working folders, General, task stages, durable runs, scheduler, permissions, and delivery outbox |
| 3 | [Product shell, Today, Aide Projects, and Settings](phase-03-product-shell-today-settings.md) | **In progress** | The three-space shell, useful Today, folder Projects in Aide, settings, and legacy redirects |
| 4 | Aide and Andromeda | Planned | Aide Chat/Jarvis shell plus fast, grounded, local-capable AI search |
| 5 | Jarvis inside Aide and channels | Planned | Workflows, runs, schedules, Discord, News, and Today delivery |
| 6 | Docs and knowledge migration | Planned | Safe Visual/Source Markdown editing with Obsidian-compatible conflicts and privacy |
| 7 | Files and storage locations | Planned | Stable local/online file identity, general WebDAV/S3 Files browsing, offline cache, and Photos; the separate backup-only WebDAV target ships in Phase 1C |
| 8 | Specialist app consolidation | Planned | Plan, Inbox, Library, Health, Finance, imports, and optional Actual interoperability |
| 9 | Distribution and browser access | Planned | Native installer, safe updates, uninstall, and the Passwords browser extension |
| 10 | Localization and release hardening | Planned | Eight languages, credits/licenses, accessibility, performance, security, and final recovery proof |

## Gate rule

Do not begin a later data migration just because its UI is attractive. The earlier recovery, security,
identity, and parity gates must pass first.

The complete requirements and gates currently live in the [Afterlife design](../design.md). As work
starts, each row above gets its own small phase file in this folder.
