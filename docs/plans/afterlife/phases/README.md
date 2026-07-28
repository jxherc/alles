# Afterlife implementation phases

- **Stage:** Afterlife
- **Current focus:** Phase 12 product consolidation, search verification, and Server redesign
- **Implementation status:** Phases 0 through 11 are delivered; Phase 12 direction is approved and its
  exact HTML starters remain before real-interface work

These are dependency gates, not release dates. Each phase must be split into small, testable plans before
implementation.

| Phase | Name | Status | Main result |
|---|---|---|---|
| 0 | Recovery gate and baseline | **Delivered** | Encrypted backup/restore, safe defaults, upgrade fixtures, and compatibility baselines |
| 1 | Platform and security foundation | **Delivered** | Access profiles, secrets, service ownership, Server foundation, safe Docs/Files primitives, and backup targets |
| 2 | [Folder Projects and durable background core](phase-02-projects-jarvis-core.md) | **Delivered** | Working folders, General, task stages, durable runs, scheduler, permissions, and delivery outbox; old internal names remain for compatibility |
| 3 | [Product shell, Home, Aide Projects, and Settings](phase-03-product-shell-today-settings.md) | **Delivered; reverified 2026-07-18** | The three-space shell, useful customizable Home, folder Projects in Aide, settings, and legacy redirects |
| 4 | [Aide and Andromeda](phase-04-aide-andromeda.md) | **Delivered; interaction revised** | One-mode Aide, grounded search, and a live-verified optional managed SearXNG lifecycle |
| 5 | [Background Aide and channels](phase-05-background-aide-channels.md) | **Delivered** | Finished scheduled/background Aide and added the owner-scoped Jarvis Discord connection |
| 6 | [Docs and knowledge migration](phase-06-docs-knowledge.md) | **Delivered** | Safe Docs migration, unified Notes/Journal, corrected Aide and Andromeda, and fresh full-suite, live-provider, and real-app proof |
| 7 | [Files and storage locations](phase-07-files-storage.md) | **Delivered; reverified 2026-07-17** | Safe local and online locations, durable transfers, offline copies, Photos handoff, and the real KOKUEN Files workbench |
| 8 | [Specialist app consolidation](phase-08-specialist-app-consolidation.md) | **Delivered; verified 2026-07-20** | Plan, Inbox, Library, Health, Finance, safe imports, and Actual as the gated canonical ledger |
| 9 | [Distribution and browser access](phase-09-distribution-browser-access.md) | **Delivered; verified 2026-07-20** | Native installer, safe updates, uninstall, and paired exact-site Passwords browser access |
| 10 | [Localization and release hardening](phase-10-localization-release-hardening.md) | **Delivered; verified 2026-07-21** | Eight reviewed core-flow languages, locale input/formatting, complete credits/licenses, and separated release-hardening proof |
| 11 | [Post-development review and handoff](phase-11-post-development-review-handoff.md) | **Delivered; verified 2026-07-21** | 41-row reconciliation, detailed review, lifecycle/browser proof, and honest final handoff |
| 12 | [Product consolidation and interface rebuild](phase-12-product-consolidation-ui-rebuild.md) | **In progress; starter gate open** | Eight workbenches, universal shell/focus, fast plus verified Andromeda, and secure Server management |

## Gate rule

Do not begin a later data migration just because its UI is attractive. The earlier recovery, security,
identity, and parity gates must pass first.

The complete requirements and gates currently live in the [Afterlife design](../design.md). As work
starts, each row above gets its own small phase file in this folder.
