# Afterlife Phase 4 — Aide and Andromeda

- **Status:** delivered, including the live-verified optional managed SearXNG lifecycle
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** Phase 3 delivered
- **Verification:** [`../evidence/phase-04-verification.md`](../evidence/phase-04-verification.md)
- **Product correction:** [`../decision-aide-one-mode.md`](../decision-aide-one-mode.md)
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

> This file records the Phase 4 build that was actually delivered. Its Chat/Jarvis selector and Answer
> only behavior are superseded product decisions, not the target for new work. Phase 5 removes those
> controls and presents one automatic, tool-capable Aide. Jarvis remains only as the Discord bot name.

## Goal

Make Aide one understandable place to talk or hand off longer work, then make Andromeda a fast search
engine that keeps normal links useful even when its model or search companion fails.

At the end of this phase:

- Aide has one automatic, tool-capable experience with no Chat, Agent, Jarvis, Docs, or Research mode;
- simple questions stay simple, useful tools route automatically, and mutations still follow the
  selected permission profile;
- thinking and tool steps appear before the answer and remain inspectable;
- memory use is visible, scoped, reviewable, and absent from incognito;
- Andromeda shows normal results immediately with an optional cited AI Overview above them;
- `!ai` skips only that search's overview;
- a small local model can produce the normal overview from a bounded evidence bundle;
- weak, stale, conflicting, or missing evidence produces an honest recovery state instead of a guess;
- the managed SearXNG definition is pinned, loopback-only, resource-limited, and live-verified on a
  supported Docker/Compose runtime; external HTTPS SearXNG and other providers remain supported when
  that runtime is unavailable.

## Design direction

The visual idea is **evidence first**.

- **Feel:** calm, precise, compact.
- **Palette:** keep Alles's existing near-black surfaces, off-white text, restrained purple accent, and
  existing success/warning/error colors.
- **Type:** keep the current local/system typography and use weight, spacing, and alignment for
  hierarchy. No new font or remote asset is added.
- **Composition:** Aide keeps one conversation column. Andromeda places a reserved overview region
  above a stable result list so the links never move or wait on model work.
- **Signature:** a quiet evidence rail connects overview citations to numbered source cards. It exists
  to make support easy to inspect, not as decoration.
- **Motion:** only short state transitions, all removed under reduced motion.
- **Density:** medium on desktop and touch-safe on mobile.

The rest stays visually quiet: no gradients, decorative dashboards, fake activity, generated images,
new icon packs, frontend framework, or animation library.

## Starting implementation facts

Phase 4 extended working code instead of replacing it:

- model roles for Aide, Andromeda, and Jarvis already resolve independently;
- Project selection and folder safety already exist in Aide;
- Automatic tools and Answer only already have backend settings and routing tests;
- memory already has Off/Ask/Auto, global/Project scope, review state, provenance, and usage fields;
- incognito sessions are RAM-only and normal prompt injection already skips memory;
- tool steps are persisted with assistant messages and can be rendered after reload;
- provider search, SearXNG JSON search, safe page fetching, and deep research already exist;
- the owned-service manager already supports typed Compose lifecycle controls.

The named gaps were the old Agent/Chat switch, separate Docs/Research toggles, persona None falling back
to a default row, force-scrolling paths, open-by-default live steps, incomplete memory actions and
provenance, no Andromeda result surface, no bounded overview evidence/verification path, and no managed
SearXNG installation or health contract.

## 4A — Aide

The checklist below records the originally delivered Phase 4 implementation. The accepted one-mode
decision and delivered Phase 5 correction supersede its Chat/Jarvis and Answer-only controls. New work
must follow the current bullets above and [`../decision-aide-one-mode.md`](../decision-aide-one-mode.md).

### 4A.1 — one conversation behavior

- [x] Replace the Agent/Chat control with a clear **Chat / Jarvis** selector inside Aide.
- [x] Keep one normal Chat conversation and route approved reads, searches, and tools internally.
- [x] Remove the separate Ask Docs and Research toggles without removing their underlying abilities.
- [x] Make **Automatic tools** the default and add a small per-conversation **Answer only** override.
- [x] Keep ask-before-change as the default mutation boundary after automatic routing.
- [x] Make **None** mean no persona prompt, remove implicit fallback to a default persona, revise only
  the built-in starter defaults, and preserve every custom persona.
- [x] Preserve exact Project, thread, attachments, model, and draft state when switching Chat/Jarvis.
- [x] Show the effective model and provider before private Project, memory, file, or owner context is
  sent outside Alles.
- [x] Make Compare an action rather than a persistent Aide destination.

### 4A.2 — Jarvis handoff inside Aide

- [x] Offer **Keep here** and **Run with Jarvis** when work should continue in the background.
- [x] Create the Jarvis task with the same request, Project, approved folder environment, attachments,
  and explicit model override.
- [x] Open the created task inside Aide and keep its durable progress visible in the existing sidebar.
- [x] Keep failure, cancellation, restart, retry, and resume behavior recoverable without creating a
  standalone Jarvis app or global destination.

### 4A.3 — conclusion, steps, and scroll ownership

- [x] Render a successful conclusion before the tool history.
- [x] Collapse successful tool work under one accessible **Show steps / Hide steps** control during
  streaming and after reload.
- [x] Keep failures, questions, pending choices, and approvals visible while successful steps are
  collapsed.
- [x] Preserve sources, diffs, revert controls, and exact tool-step history after reload.
- [x] Stop force-scrolling when the owner moves away from the bottom or is selecting/typing.
- [x] Add a keyboard-accessible **Jump to latest** control and resume following only after it is used or
  the owner returns to the bottom.
- [x] Fix original desktop/mobile incognito states without inventing a replacement token glyph.

### 4A.4 — memory and capability coverage

- [x] Add **Remember this** with visible scope, confirmation, and Undo.
- [x] Add **Forget this** for memories used by a response without deleting unrelated memories.
- [x] Show memory suggestions for Ask, restricted low-risk owner statements for Auto, and review/accept
  controls for derived suggestions.
- [x] Show which owner instructions and memory IDs/scopes were used by each response.
- [x] Prove Off and incognito perform no memory reads or writes, including agent tools, extraction,
  distillation, personal insights, and background handoff.
- [x] Keep review, search, edit, delete, export, pause, and clear controls in Settings.
- [x] Complete typed capability rows and approval tests for Home, Aide, Plan, Docs, and Andromeda;
  record explicit exclusions rather than silently claiming later specialist coverage.

### 4A gate

Automatic tools, Answer only, persona None, custom personas, Chat/Jarvis switching, Project context,
handoff, conclusion-first steps, reload, scroll ownership, memory actions/provenance, and incognito all
pass focused backend and JavaScript tests. Isolated desktop and mobile runs cover keyboard and screen
reader labels, reduced motion, empty/loading/error/cancel/restart states, no horizontal overflow, and no
unexpected console, page, or server errors.

## 4B — Andromeda

### 4B.1 — managed SearXNG spike

- [x] Pin the reviewed SearXNG image by immutable digest and record its upstream version and license.
- [x] Generate an Alles-owned Compose definition under `ALLES_DATA`, bind only to loopback, use a
  private settings/secret file, drop unnecessary privileges, and set explicit CPU/memory/process limits.
- [x] Register the exact definition with the owned-service manager so tampering revokes control.
- [x] Add typed install, start, stop, restart, health, and safe-update/rollback behavior guarded by
  recent-owner confirmation.
- [x] Prove low-resource startup, JSON search, health, supervised restart, server restart, failed pull,
  failed health, rollback, and uninstall-keep-data behavior on supported Docker.
- [x] Keep an external HTTPS SearXNG URL and other existing providers usable when Docker or managed
  SearXNG is unavailable. Never claim managed support when the runtime spike cannot pass.
- [x] Show the optional managed SearXNG state and safe recovery actions in Server.

The supported-Docker item passed live on 2026-07-17 with Docker 29.5.2, Compose, and Colima on macOS.
The isolated run proved loopback-only JSON search, the 512 MiB / 1 CPU / 128 PID limits, read-only
root filesystem, supervised and server restart recovery, a failed digest pull without downtime,
failed-health rollback, successful update and explicit rollback, and uninstall while retaining the
private config and secret. The service container and throwaway data were removed after verification.

### 4B.2 — immediate normal results

- [x] Add a dedicated Andromeda route and result page behind `afterlife_andromeda`.
- [x] Parse standalone `!ai` anywhere, remove only that token, preserve SearXNG bangs, and leave saved
  settings unchanged.
- [x] Keep AI Overview and normal-result settings independent and default both on.
- [x] Return ranked normal results with provider, elapsed time, title, URL, snippet, and safe source
  metadata without waiting for overview work.
- [x] Keep result order and content stable when `!ai` changes only the overview.
- [x] Show clear setup, loading, empty, partial, timeout, offline, disabled-results, disabled-overview,
  both-disabled, no-provider, and retry states.
- [x] Meet or visibly revise the deterministic links-ready budget of 1.5 seconds p95; record live
  network timing separately from fixture timing.

### 4B.3 — bounded grounded overview

- [x] Fetch real pages through the existing SSRF-safe path and build a size-bounded evidence bundle
  containing source ID, title, URL, publisher, date, version, quality, and relevant passages.
- [x] Prefer current primary sources and apply the locked software-source order: official docs, release
  notes, source repository/tag, package registry, then clearly labelled community material.
- [x] Extract and compare dates and versions; add **Checked on** when freshness matters.
- [x] Add Light, Standard, Strong, and Auto bands with owner-selected exact models and a per-search
  override. Auto may choose only a configured local model that passed the quality fixture.
- [x] Stream claim-level citations into the reserved overview area while normal links remain usable.
- [x] Verify every factual claim against its cited passage before marking it supported.
- [x] Remove, soften, or label unsupported, stale, weak, or conflicting claims and provide a clear
  insufficient-evidence result when needed.
- [x] Keep normal results usable on no-model, local-model failure, timeout, cancellation, or bad model
  output. Never silently send the query or evidence to a remote model.
- [x] Meet or visibly revise the deterministic Standard-local first-text budget of 5 seconds p95.

### 4B.4 — source actions, saving, and deep research

- [x] Let the owner inspect source quality and the exact evidence behind each citation.
- [x] Add **Explain selected links in Aide** without injecting unrelated private context into search.
- [x] Save and reopen normal searches with their query, settings snapshot, result metadata, overview,
  citation evidence, model/provider provenance, and checked time.
- [x] Add **Run deep research with Jarvis** while preserving the query and selected Project.
- [x] Replace the named no-information dead end with failure type, safe attempted sources, retained
  links, and **Retry / Broaden search / Edit query / Return to normal results** actions.
- [x] Re-run encrypted backup/restore and migration checks for saved-search data.

### 4B gate

Normal overview-plus-results, `!ai`, globally disabled overview, disabled normal results, both disabled,
no model, no SearXNG, provider timeout, partial source, conflicting evidence, unsafe URL, bad extraction,
offline, cancellation, and local-model failure all produce useful results or clear recovery. Software
fixtures prove stale versions are never presented as current and every claim marked supported has an
exact cited passage. The SearXNG definition is called managed only after its live runtime spike passes.
This build passed that spike on a supported Docker/Compose runtime while keeping external/provider
fallbacks available.

## Phase 4 exit gate

Phase 4 is delivered only when all of these are true:

1. Aide has one Chat/Jarvis home and no separate Agent, Ask Docs, or Research mode.
2. Automatic tools is the default, Answer only is available, and mutations still require approval.
3. Persona None adds no prompt and custom persona data is unchanged.
4. Chat/Jarvis switching and background handoff preserve the active Project and request.
5. Successful work leads with its conclusion; steps remain accessible; scroll ownership stays with the
   owner.
6. Memory scope, provenance, Remember/Forget, review, Off, and incognito behavior are proven.
7. Home, Aide, Plan, Docs, and Andromeda capability rows have working tests or explicit exclusions.
8. Andromeda displays usable normal links independently from its cited overview.
9. `!ai` changes only one request and does not become a competing search mode.
10. Freshness, version, source-quality, and claim-to-citation checks fail closed.
11. Local overview failure keeps links and never causes an unapproved remote request.
12. The managed SearXNG definition is loopback-only, ownership-checked, pinned, resource-limited,
    recoverable in simulated and supported-runtime lifecycle tests, and honestly unavailable when its
    live runtime requirements are missing.
13. Desktop, mobile, keyboard, screen-reader labels, reduced motion, offline, partial, empty, failure,
    restart, recovery, full Python, full JavaScript, browser, changed-file Ruff, and backup/restore
    gates pass with throwaway data and no new console or server errors; the repository-wide Ruff
    baseline is recorded honestly.

## Verification record required before delivery

- exact focused Python and JavaScript test names/counts;
- full Python and JavaScript counts with throwaway `ALLES_DATA`;
- deterministic search and local-overview latency distribution and reference hardware;
- separate live-network observations without a false guarantee;
- managed SearXNG version, digest, bind address, simulated lifecycle coverage, Docker-unavailable
  behavior, and live health/resource/restart/update/rollback evidence on a supported runtime;
- authenticated and auth-disabled browser passes at representative desktop/mobile widths;
- keyboard, focus return, screen-reader labels, reduced motion, overflow, console, page-error, and
  server-error evidence;
- memory no-read/no-write and untrusted-source tests;
- encrypted backup/export/restore evidence for every new durable shape;
- changed-file Ruff checks plus an honest repository-wide baseline;
- dependency/license/notice changes, or an explicit record that none were added.

## Not part of Phase 4

- Jarvis Workflows, Runs, Schedule, Connections, cron, heartbeat, and webhooks beyond the handoff needed
  to prove the Aide mode;
- Discord pairing and News collection;
- the full Docs/Obsidian editor migration;
- Files storage locations and offline cache;
- specialist-app consolidation or Finance migration;
- installer distribution, Passwords extension work, localization, or final release hardening.
