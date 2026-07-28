# Stage 6 — Afterlife

- **Status:** Phases 0 through 11 delivered; Phase 12 product/interface correction is in progress
- **Started:** July 11, 2026
- **Meaning:** preserve what works, repair what is unsafe, and give Alles one coherent new life

Alles reached a first life with many partially usable features. Purgatory left those features spread
across overlapping plans, branches, and product ideas. Afterlife is the deliberate rebuild after that
point.

Afterlife is not a rewrite from scratch. It keeps real user data, proven capabilities, compatible links,
and the current FastAPI/SQLite/vanilla-JavaScript stack.

## Current product shape

- **Home** — the daily dashboard.
- **Aide** — one assistant that can chat, use tools, and keep work running in the background.
- **Andromeda** — fast search with normal results and a grounded AI Overview.
- **Projects** — a selected folder that becomes Aide's prioritized working environment.
- **Specialist sections** — Plan, Docs, Files, Finance, Inbox, Library, Health, Passwords, and Server.

Jarvis is only the Discord bot's name. Background work remains Aide.

## Start here

- [Full product and architecture design](design.md)
- [Accepted decision: Aide has one mode](decision-aide-one-mode.md)
- [Accepted decision: approve interface starters before implementation](decision-html-first-ui.md)
- [Accepted decision: one quality system for every Andromeda search](decision-andromeda-result-quality.md)
- [Implementation phases](phases/README.md)
- [All project stages](../README.md)
- [Current shipped specifications](../../../specifications.md)

## Current state

Phase 12 is now in progress. The owner approved exactly eight visible specialist workbenches, a
compact cited Andromeda answer followed by independent background verification, and an owned-only
Server default with a fail-closed file-backed allowlist for any extended host management. The exact
standalone KOKUEN starters are not yet approved, so no real Phase 12 interface is described as shipped.
The decision-complete sequence and gates are in
[`phases/phase-12-product-consolidation-ui-rebuild.md`](phases/phase-12-product-consolidation-ui-rebuild.md).

Phases 0 through 11 are delivered. Phase 11 reconciled all 41 original brainstorm requests against
the current implementation: 40 are satisfied, only the token-glyph visual approval remains honestly
open, and all 27 final-acceptance rows pass. A current implementation recheck closed every Phase 0-5 checklist
row on July 18, including the approved Settings-based Home customization flow and corrected shipped
behavior documentation. The reopened Phase 6 gate passed on July 16 with fresh recovery,
JavaScript, formatting, browser, live SearXNG, and visible UI proof. Phase 5 replaced the old
Chat/Jarvis split with one automatic Aide,
finished scheduled work, and added the owner-scoped Jarvis Discord connection. The branch also ships
visible memory controls and links-first Andromeda search with an optional grounded AI Overview. The candidate
SearXNG definition is pinned and loopback-only. Its managed lifecycle passed live on supported Docker,
reports unsupported Docker or data-root boundaries honestly, and keeps external HTTPS SearXNG and
other providers usable. Phase 6
keeps its isolated Markdown-preservation and recovery foundation, including
restart-safe vault moves and encrypted recovery for configured external vaults. Its approved Docs
interface remains an Obsidian-first Markdown viewer with an on-demand CodeMirror editor, exact
source preservation, safe drafts and conflicts, unified Notes/Journal navigation, reversible Journal
migration controls, retained Journal tools, and visible Aide note scope. The Phase 6 correction gate
passed across the four Aide permissions, real terminal and speech flows, live managed and external
SearXNG, automatic AI Overview, and all 19 real specialist apps. The tested build remains in the
`dev-afterlife` worktree; the owner's normal `notes-vault` checkout was not changed. Phase 7 adds
stable local, WebDAV, and S3-compatible storage locations, location-aware metadata, safe durable
transfers, explicit offline copies, a verified Files-to-Photos handoff, background indexing, and the
approved KOKUEN Files workbench. Its full Python, JavaScript, Ruff, and real browser gates passed on
throwaway data. The owner approved Phase 8's five fake-data KOKUEN starters, and the real Plan, Inbox,
Library, Health, and Finance workbenches are implemented with compatibility routing. The additive
currency/import foundation and managed Actual canonical-ledger boundary are also delivered. The final
full regression, upgraded-ledger live gate, real desktop/mobile browser gates, warning scan, Ruff, and
diff/index checks pass. The owner removed autoreview from this delivery scope, so no clean-autoreview
claim is made.

Phase 10 is delivered with all 44 checklist rows backed by current-worktree evidence. Eight internally
reviewed local catalogs cover the named core flows, shared locale formatting and deterministic
Task/Calendar input work in every language, translated READMEs record their canonical revision, and
the cold-offline desktop/phone RTL/CJK gate passes. The complete 432-entry credits manifest generates
the exact 465-file release notice set and matches native/container artifacts. Compatibility,
performance, security/privacy, recovery, Aide capability, architecture, full regression, Ruff, diff,
and empty-index gates pass with their physical-Linux, live-owner-remote, external-native-review, and
translation-scope limits stated in the Phase 10 evidence. No autoreview, commit, or push was performed.

Phase 11 fixed the final confirmed privacy, security-communication, password-policy, packaging, and
test-infrastructure blockers. It then passed the real macOS and Linux-container lifecycle paths, the
pinned Actual runtime lifecycle, current browser capstones, 5,025 Python tests, 434 JavaScript tests,
dependency/security checks, Ruff, generated notices, diff, and empty-index checks. The detailed
finding dispositions and limits are in [`final-review.md`](final-review.md). No autoreview, mockup,
commit, or push was performed.

## Stage rules

- New future plans live in this folder.
- For remaining visual work, make and approve a standalone KOKUEN HTML starter before changing the
  real interface.
- Use `decision-<topic>.md` for a product or architecture decision.
- Use `phases/phase-XX-<topic>.md` for an implementation plan.
- Every plan states **draft**, **ready**, **in progress**, **blocked**, **delivered**, or **replaced**.
- A plan becomes **delivered** only after fresh tests and evidence.
- Update `specifications.md` only after behavior ships.
- Never delete legacy data in the same release that first introduces its replacement.
