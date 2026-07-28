# Afterlife — product and architecture design review

- **Stage:** 6 — Afterlife
- **Status:** Phases 0 through 11 delivered; final handoff records 1 original-request gap
- **Last updated:** 2026-07-21
- **Scope:** the Afterlife rebuild

> This document describes planned behavior, not the current application.
> `specifications.md` remains the reference for behavior that is already shipped.
>
> **Accepted correction:** [`decision-aide-one-mode.md`](decision-aide-one-mode.md) overrides every
> older mention of Chat/Agent modes, Chat/Jarvis modes, Answer only, or Jarvis as an in-app/background
> runtime. Jarvis now means only the Discord bot.

## Purpose

This plan turns the product brainstorm into one buildable direction.

It is the source for:

- product names and boundaries;
- navigation and information architecture;
- shared data and runtime foundations;
- safety and migration rules;
- implementation order;
- acceptance checks.

Technical choices marked **spike first** still need a small proof before they become dependencies.

## Short version

- **Home** is the default dashboard.
- **Aide** is one assistant. It chats, uses tools when useful, and keeps durable, scheduled, or
  background work in the same conversation.
- **Andromeda** is AI search, with SearXNG as its normal Web results tool.
- **Jarvis** is only the Discord bot's name. It connects Discord messages to Aide.
- A Project is one selected folder that becomes Aide's prioritized working environment.
- Specialist apps are grouped into Plan, Docs, Files, Finance, Inbox, Library, Health, Passwords, and
  Server.
- Files supports approved local and online locations. Sync, offline copies, and backup stay separate.
- Actual Budget is the intended Finance ledger/budgeting core after its migration gate; Alles remains
  the UI and keeps only Alles-specific sidecar records.
- Aide and Andromeda each have a default model, with per-feature and per-run overrides. Background Aide
  uses the same Aide choice unless the owner explicitly overrides that run.
- Model lists refresh from each endpoint instead of relying on a shipped memorized catalog.
- Andromeda's normal AI Overview is designed to run with a small local model; stronger models remain
  optional for difficult searches.
- Alles keeps its current FastAPI, SQLite, vanilla JavaScript, and CSS stack.
- The build starts with safe encrypted backup, restore, network defaults, and migration tests—not the
  visual redesign.

## Product principles

1. **AI-first, not AI-required.** Core daily tools keep working without a model.
2. **Reduce doors, not features.** Merge navigation before deleting data or backend routes.
3. **Local-first and resilient.** Plain files where appropriate, SQLite for structured state, and verified backups.
4. **One owner.** Alles remains deliberately single-user.
5. **Ask before meaningful changes.** Reads can be easy; sends, deletes, edits, purchases, and system changes need clear authority.
6. **No silent data loss.** Conflicts, unsupported Markdown, failed syncs, and migrations preserve both sides.
7. **Simple on the surface.** Advanced controls stay available without crowding daily use.
8. **Keep the current stack.** FastAPI, SQLite/SQLAlchemy, vanilla JavaScript, and plain CSS stay.
9. **macOS and Linux first.** Windows remains best-effort until the main experience is stable.
10. **Private by default.** No telemetry, public services, remote fonts, or cloud dependency should be required.

## The three main product spaces

| Name | Job | Normal use |
|---|---|---|
| **Home** | Coordinate the day | See what matters, approve work, open pinned apps |
| **Aide** | Conversation, tools, and background work | Ask once; Aide decides whether the request needs text, tools, or durable background work |
| **Andromeda** | AI-first search | Get a cited answer, then browse normal web results |

**There is no second Aide mode.** Chat, tool use, longer work, schedules, heartbeats, news, and delivery
all use Aide. **Jarvis** names only the optional Discord bot.

**Cowork is retired as a product name.** Its useful background-work ideas become normal Aide behavior.

## Navigation

### Always visible

- Home
- Aide
- Andromeda

There is no mode selector. Active Aide runs, approvals, and finished briefs also surface in Home.
Jarvis appears only inside Discord connection settings.

### Available from pinned apps, search, or the app drawer

- Plan
- Docs
- Files
- Finance
- Inbox
- Library
- Health
- Passwords
- Server

Settings lives in the Alles/profile menu and opens with `Cmd/Ctrl + ,`.
Global search opens with `Cmd/Ctrl + K`.

Calendar, Tasks, Docs, Files, Mail, and Finance can be selected as pinned apps on Home.
They do not need equal top-level weight.

### App consolidation

| New destination or section | Existing features it contains |
|---|---|
| **Home** | The legacy launcher, Activity, proactive items, reminders, and important dates |
| **Aide** | Chat, tools, skills, automations, schedules, background runs, deliveries |
| **Plan** | Calendar, Tasks, Reminders |
| **Docs** | Docs, Notes, Journal views over the Markdown vault |
| **Files** | Managed files, approved local locations, online locations, Photos/Gallery |
| **Finance** | Money and Subscriptions |
| **Inbox** | Mail and Contacts |
| **Library** | Books, Watchlist/Read, saved News |
| **Health** | Health tracking and Habits |
| **Server** | System monitor, Watch, Alles services, backups, logs, maintenance |

Passwords remains a separate secure surface.
Projects live in the Aide sidebar rather than becoming another app or data silo.

The first consolidation release changes navigation only. Existing tables, URLs, and APIs stay behind
compatibility aliases until their replacements are proven.

The existing Apps directory remains the approved baseline. A later consistency pass should be small:
align spacing, type, and shared navigation with the finished Home, Aide, and Andromeda shell without
removing information or rebuilding the specialist apps. It requires a fresh standalone HTML starter
and explicit owner approval before the real interface changes.

## Shared interaction rules

- Use plain language and short labels.
- Show a compact model chip only where a model matters.
- Keep keyboard access and visible focus states.
- Never expose browser-default selects, checkboxes, or radios. Use accessible KOKUEN controls instead.
- Before a new app interface or material app rework, make a standalone KOKUEN HTML starter with fake
  data and minor local-only interactions, then wait for explicit owner approval before changing the
  real app.
- Targeted fixes that preserve an already approved direction do not need another starter, but they do
  need focused regression coverage and rendered browser verification. Do not turn a bug fix into an
  unapproved redesign.
- Keep normal interface text and controls at least 14 pixels, conversation text at least 16 pixels, and
  helper text at least 12 pixels.
- Respect reduced motion.
- Design desktop and mobile together.
- Show loading, empty, offline, partial, error, disabled, and conflict states.
- Use inline status such as **Saving**, **Saved**, **Waiting**, **Offline**, or **Needs approval**.
- Do not use endless feeds.
- Do not move important work into temporary toasts only.
- A background task must remain visible after the page closes.
- Preserve information, but use spacing, type, and surface tone before adding borders. Separators mark
  real structural boundaries only. Avoid nested boxes, card-everything layouts, duplicated controls,
  decorative rules, and secondary controls that remain visible when they are not relevant.

## Visual direction

The interface remains a quiet, precise daily tool:

- near-black and off-black surfaces;
- the existing restrained purple accent;
- sharp, small radii;
- medium information density;
- limited, purposeful motion;
- current typography until local/system font coverage is reviewed.

No framework migration, remote image set, icon pack, animation library, or new font is part of this
redesign by default.

The three icon screenshots attached to the original brainstorm are acceptance references, not assets to
copy into the repository. The normal and enabled incognito states use the same incognito glyph; color,
label, or surrounding state communicates whether it is enabled. The current mismatched smile/starburst
states are removed. The token-count icon is tracked as a separate visual fix and receives owner approval
before a replacement glyph is chosen.

## Primary experiences

### Home

Home replaces the launcher as the default page.

Its order is:

1. **Needs you** — approvals, choices, conflicts, and failed work.
2. **Schedule** — events, due tasks, reminders, habits, renewals, and important dates.
3. **In progress** — active and background Aide work.
4. **Briefs** — finished news, research, and scheduled reports.
5. **Pinned apps** — the app destinations selected in Settings → Home.

Core cards are deterministic and work without AI. AI can summarize or prioritize them when requested.
Activity becomes a History view instead of a separate app.

Home's greeting, heading, and summary are dynamic from the current time and live Alles data; they are
not hardcoded demo copy. The five information groups may share one continuous layout with whitespace
and type hierarchy instead of becoming five boxed dashboards. Home remains useful when no model is
configured.

The KOKUEN starter takes the continuous-layout option: a roomy greeting, unboxed schedule rows, plain
Focus and Needs you lists, one inline Aide brief, an underlined capture row, and compact Aide/Andromeda/
Apps links. It avoids event cards, briefing cards, full-width destination grids, and a boxed Quick
capture control. Greeting tracking remains loose enough that **good afternoon, jxh** never looks crushed.

Home has no Settings control. Saved Home preferences remain compatible, but any visible customization
belongs in the main Settings surface. The inline Aide brief is plain text, short enough to scan in two
lines, and never dumps raw Markdown or a full conversation response into Home.

### Aide

Aide is one assistant with no visible or default mode selector. Every conversation can answer directly,
reason, read approved user data, search through Andromeda, use tools, or keep working in the background.
Simple questions stay simple; tasks use approved tools automatically when useful.

The old Agent/Chat switch, temporary Chat/Jarvis switch, Answer only control, Ask Docs mode, Research
toggle, and Compare action are removed. Research is contextual: when Aide detects that deeper research
would help, it asks the owner and continues inside the same task after approval. Settings controls
permissions, allowed tools, folders, models, memory, effort, and background limits. Cookbook moves to
**Settings → AI and models**. Aide never asks the owner to choose Chat versus Agent.

Personas remain an optional advanced feature. **None** is the default and means the normal base assistant
with no extra persona prompt. Phase 4 fixes None selection, revises the built-in persona defaults, and
preserves custom personas.

Default mutation behavior is **ask before changes**. Aide may read allowed context freely, but sending,
deleting, editing outside the current draft, purchasing, or changing the system requires approval.

When work will take a while, Aide can keep running in the background with the same Project, request,
attachments, model context, and conversation.

Aide keeps the compact KOKUEN conversation canvas. Codex is a task-organization and control-placement
reference only. The sidebar is open by default on desktop and collapses through a split-sidebar icon;
on mobile it is a closed-by-default overlay. **Tasks** lists loose conversations directly, while
**Projects** lists folder-backed Projects and their tasks. General is not shown as a category, label, or
Project. **New task**, **scheduled**, **Brain**, **Skills**, and **Reminders** share one compact primary
navigation group. The capability rows use one restrained, matching icon each but do
not sit under a separate Tools heading. Models and Cookbook remain in Settings. Tasks and Projects use stronger headings, smaller conversation rows, and
real group spacing instead of separator lines. Search and Settings remain easy to reach, and Connections
stay in the composer's `+` menu. The top bar's primary label is the conversation name. Project
conversations also show a folder icon and muted Project name; loose tasks show neither. Project folder
glyphs change between closed and open with their expanded state. Aide uses normal 1-pixel borders and
tight 3–5-pixel corner radii. Desktop top-bar icon controls use compact 32-pixel boxes while mobile keeps
44-pixel touch targets. Search also keeps a 44-pixel hit area. Activating it grows a transform-only field
leftward across the Aide wordmark; Escape restores the normal heading without a layout repaint. The
sidebar footer keeps text-only **Settings** at the left and a quiet **Home** control at the right. The composer has one 1-pixel outer border; textarea focus never draws a
second inset outline. Structural panel toggles stay visually neutral in both open and closed states
because the panel itself already shows the state.

The composer has no suggested prompts. Its permission button is text-only, has no icon, and offers
exactly **auto mode** (full permission), **ask for approval** (the default), and **plan** (read and plan
without making changes). Only Auto mode is purple; the other permission states remain neutral. A compact
control selects the current task's model and effort; full catalogs and defaults stay in Settings. The
`+` button is a custom menu for files, photos, apps, and connections, and speech is directly reachable.
On desktop the microphone and send controls share the same 36-pixel square and 18-pixel glyph size; on
mobile they share the same 44-pixel touch target. Hover never moves the send control out of alignment. A
hidden-by-default right task-tools sidebar is attached to the viewport edge and gives Review, Terminal,
Browser, Files, and Side task one compact launcher. It is a real layout column on desktop, not a floating
window. There is no automatic pinned summary. Opening Terminal replaces the panel body with only the
terminal surface; no environment summary, description, review rows, or app links remain visible.

The real browser terminal should start with a pinned, self-hosted [xterm.js](https://xtermjs.org/) build
and a Project-scoped PTY over an authenticated, origin-checked WebSocket. xterm.js is specifically a web
terminal frontend and documents the PTY bridge. [Ghostty](https://github.com/ghostty-org/ghostty) remains
worth re-evaluating later because `libghostty-vt` supports WebAssembly, but its API is still unversioned
and in flux. Terminal output is untrusted, the terminal page loads no runtime CDN code, and the shell
never runs as root. Follow the [xterm.js security guide](https://xtermjs.org/docs/guides/security/) for
transport, origin, DOM, and privilege boundaries.

Messages rely on layout instead of **you** or **Aide** author labels. The top bar owns the conversation
title and Project context, so the message stream never repeats them as a thread heading. Thinking,
progress, failures,
questions, approvals, and tool steps appear in order before the answer. Completed details may collapse
behind one keyboard-accessible toggle, but that disclosure remains before the answer and survives
reload. The message rail stays absent below three user messages. At three or more, it appears vertically
centered with one keyboard-accessible tick per user message. Its one bright tick follows the user message
closest to the reading position while scrolling; the top and bottom positions map exactly to the first and
last messages. Pointer proximity controls each tick independently: the nearest grows most, nearby ticks
grow less, and distant ticks stay short. Transform-only scaling keeps the hit area stable and avoids
page repaint bugs. A keyboard-focused tick gets full reach, and selecting one jumps to that message.
Streaming must not force-scroll while the user is reading or typing. A visible jump-to-latest control
replaces automatic scroll capture.

#### Memory and owner instructions

Memory is controlled learning, not silent profiling.

- **Off** never reads or writes long-term memory.
- **Ask** is the default. Aide can suggest a low-risk preference, but the owner confirms it.
- Optional **Auto** may save only low-risk preferences stated directly by the owner.
- **Remember this** saves an explicit owner request with visible confirmation and Undo.
- **Forget this** removes the memory from active use and its indexes.

Memories carry a source, global or Project scope, created/updated times, and the runs that used them.
Settings can search, review, edit, delete, export, pause, or clear memories. Incognito conversations read
and write no memory. Mail, web pages, feeds, Discord, files, MCP output, and other untrusted content can
never create memory or alter owner instructions.

The editable owner system prompt is separate from the immutable safety and permission rules. Alles shows
which owner instructions and memories were used for a response.

#### Aide capability coverage

Aide uses the same service layer as the normal UI. It never controls an app by silently editing the DOM
or bypassing the database and permission layer. Every product phase maintains a capability row with:
readable context, safe actions, approval-required actions, background Aide support, exclusions, and tests.

| Product area | Minimum Aide coverage | Hard boundary |
|---|---|---|
| Home | Read cards and propose layout/shortcut changes | Customization changes need approval |
| Plan | Read, create, update, move, and complete items | Deletes and external calendar effects need approval |
| Docs | Search, read, create, edit, link, and summarize Markdown | Protected/private content needs an explicit grant |
| Files and Photos | Browse, search, preview, copy, move, upload, and import | Destructive or outside-root work needs approval |
| Finance | Read summaries; draft categories, imports, and budgets | No bank-password access or purchases |
| Inbox | Read/search allowed accounts; draft mail and contact changes | Send, delete, and external changes need approval |
| Library | Search, save, tag, and organize items | Saving/removing content is visible and reversible |
| Health | Read or add entries only after an explicit sensitive-data grant | Never enters Project context automatically |
| Passwords | Find a requested entry and start a narrow fill/reveal flow | Never bulk-inject or reveal secrets to a model |
| Server | Read health and operate identified Alles-owned services | No arbitrary host administration or shell bypass |
| Andromeda | Search, explain results, save, and hand off research | Normal search does not receive unrelated private context |

An area is not Afterlife-complete until its capability row is implemented or its exclusion is recorded
with a reason.

### Andromeda

Andromeda is an AI-first search engine, not a second chat page.

The result page is one Google-style page:

1. a cited **AI Overview** at the top;
2. normal ranked web results directly underneath it.

The regular results do not wait for the AI Overview. When AI is enabled, its reserved area can stream
while the links are already usable. If the overview fails, the normal results remain unchanged.

The AI Overview and normal web results are enabled by default. The user can disable either one globally.
If both are disabled, Andromeda shows a setup message instead of an empty or broken search page.

Query behavior:

- a standalone `!ai` may appear before or after the search text;
- Alles removes that token before searching and skips only the AI Overview for that request;
- `!ai` does not change the search provider, ranking, layout, or saved settings;
- normal SearXNG bangs still work;
- a result action can ask Aide to explain selected links;
- when a long investigation would benefit from deeper research, Aide asks first and then continues it as
  a background run in the same task.

The AI Overview reads a small number of strong results and answers with citations.
Deep research remains a separate background path with visible progress and a durable result.

#### Speed budget

On supported baseline hardware with deterministic local fixtures:

- normal links become usable within 1.5 seconds at p95;
- AI work never delays those links;
- a Standard local model starts cited overview text within 5 seconds at p95;
- typing, scrolling, opening a result, and using `!ai` remain responsive while the overview runs.

Live-network timing is measured separately because remote websites cannot be given a fake guarantee.
Phase 0 records the reference hardware and current baseline; Phase 4 locks or adjusts the numbers with a
visible reason before they become release gates.

#### Answer quality and freshness

The AI Overview does not merely summarize search snippets or every result. It selects the strongest
sources, fetches their real content, and grounds the answer in evidence.

The fast path:

1. Search the configured provider.
2. Prefer current primary sources.
3. Fetch the relevant pages instead of trusting snippets alone.
4. Extract dates, versions, and the exact evidence needed.
5. Cross-check important claims when another strong source is available.
6. Draft the answer with claim-level citations.
7. Remove or clearly label any statement that the cited sources do not support.

For software questions, source priority is:

1. official documentation;
2. official release notes or changelog;
3. the official source repository and tagged release;
4. the package registry;
5. community posts and issue discussions, clearly labelled as such.

Software answers show the relevant version and a **Checked on** time when freshness matters. Cached
results use short topic-aware lifetimes and are revalidated for version-sensitive queries.

No model can promise zero hallucinations. Alles reduces them with retrieval, source rules, and a final
claim-to-evidence check. If the available evidence is weak, stale, or conflicting, the overview says so
or declines to answer instead of inventing certainty. The normal search results still remain available.

Deep research must never finish with only **No information could be gathered for this question**. When
usable evidence cannot be gathered, it keeps any normal links, says whether search, fetch, or extraction
failed, lists the attempted sources when safe, and offers **Retry**, **Broaden search**, **Edit query**,
or **Return to normal results**. The old failure text is a named regression fixture.

Freshness comes from the fetched evidence, not the model's training memory. This lets the normal overview
use a small local model as long as it passes the grounding and citation tests below.

SearXNG is an Alles-managed companion service when installed by Alles. It binds to loopback and is not
published directly. Andromeda still supports a user-managed SearXNG URL.

### Background Aide

Aide owns durable work that should continue without an open page. Background is a run state, not a
second assistant or mode.

Its views inside Aide are:

- Workflows
- Runs
- Schedule
- Connections

Each workflow stores:

- name and purpose;
- optional Project folder;
- prompt or deterministic action;
- model override;
- allowed capabilities;
- concurrency rule;
- trigger;
- delivery policy.

Supported triggers:

- manual;
- one-time schedule;
- exact repeating schedule;
- interval;
- heartbeat;
- application event;
- webhook;
- inbound Discord message.

An exact schedule is for work that must happen at a known time. A heartbeat periodically checks signals
and only creates work when something changed. Cheap local checks happen before any model call.

Heartbeat controls include quiet hours, cost limits, change fingerprints, skip-when-busy, and
only-notify-when-useful behavior.

Run context can be:

- **Fresh** — clean context for every run;
- **Continue workflow** — persistent workflow history;
- **Project environment** — the selected folder, its instructions, and a fresh run.

Background work never writes untrusted mail, web, Discord, or feed content into the normal Aide
conversation or long-term memory automatically.

Run states are:

- queued;
- running;
- waiting for input;
- waiting for approval;
- paused;
- succeeded;
- failed;
- cancelled;
- interrupted.

A workflow may receive a narrow capability grant once. Anything outside that grant pauses.
Questions and approvals survive restarts.

For a missed recurring schedule, background Aide coalesces missed occurrences into one current run.
A one-time reminder runs once within its grace window.

#### Jarvis on Discord

The Discord bot is named **Jarvis**.

Version one supports:

- one paired owner Discord account;
- owner direct messages;
- individually allowed private channels;
- optional channel-to-approved-Project mapping;
- starting allowed workflows;
- reading run status;
- answering non-mutating choices;
- Discord typing followed by one answer message that updates while Aide writes;
- one persistent Aide conversation per paired DM or approved channel;
- completion, failure, and input-needed delivery.

Discord-origin work starts read-only. Any mutation opens an approval inside Alles.
External notifications contain title and status only by default; full private summaries are opt-in.

OpenClaw is inspiration for cron, heartbeat, persistent session, and chat-delivery ideas only.
Alles does not depend on or connect to OpenClaw.

#### News

News is a background Aide workflow plus a Home Brief.

The deterministic pipeline:

1. Poll RSS/Atom with conditional requests and backoff.
2. Store stable feed entries with GUID, canonical URL, time, source, and content hash.
3. Remove exact duplicates and cluster similar coverage.
4. Rank by recency, interests, and source diversity.
5. Summarize selected clusters with citations.
6. Publish to Home and optional Discord/push delivery.

If extraction or the model fails, Aide still produces a normal link digest. The AI summary can arrive
later. Feed entries do not automatically become Library items; saving is explicit.

News ships with a small reviewed starter-source catalog grouped by topic and language, but it fetches
nothing until News is enabled. The owner can add, test, edit, disable, and delete RSS/Atom sources and
set each source's name, category, language, priority, and schedule. A preview appears before saving.
Source health shows the last success, last safe error, and next retry. One broken source never blocks the
rest of a digest. OPML import/export is useful but optional for the first release.

## Projects and core workspaces

### Projects

A Project is a selected folder plus the Aide conversations and background runs that work from it.
It is a prioritized environment, not a database of linked Alles records and not a hard prison.

When a Project is active:

- commands start in its folder;
- relative paths resolve inside it;
- file search and retrieval look there first;
- new files and generated outputs default there;
- Project instructions apply;
- Aide conversations and background runs remain grouped under it.

Creating a Project means choosing one folder. Its name defaults to the folder name and remains editable.
The folder may be empty; Alles can use it as the place for new output.

The folder is the default, not the only place Alles can work. Aide may read or act outside it
when the owner explicitly selects another path, invokes an allowed connector, or approves the broader
action. The UI clearly shows when work leaves the Project folder.

Alles does not copy the folder, upload every file, or send the whole folder to a model. It selects only
the files needed for the current request.

A Project stores only small environment metadata:

- name and folder path;
- optional instructions and scratchpad text;
- display color;
- associated Aide conversation and background-run IDs;
- last-opened state.

Tasks, notes, files, saved searches, and other app records stay in their own apps. They can be opened or
attached explicitly; they do not become Project members.

Loose conversations use an unscoped, no-folder context. The Aide interface never labels that context
**General** or presents it as a Project. If a Project folder moves or is missing, Alles keeps its threads
and settings, marks the folder missing, and asks the owner to relink it.

On a self-hosted server, the Project folder exists on the server or an approved mount. A browser cannot
pretend that a folder on the client device is a server folder; client-local access needs an approved
desktop bridge or mount.

### Plan

Plan combines Calendar, Tasks, and Reminders without merging their underlying data blindly.

Task List and Board are two views of the same tasks.
Default board columns are:

- Backlog
- Next
- Doing
- Waiting
- Done

Starting a task with background Aide moves it to Doing. A paused run can move it to Waiting.
After success, Aide asks before marking it Done.

### Docs

Docs combines Notes, Docs, and Journal views over real Markdown.

The Markdown file is always the source of truth.

Editor modes:

- **Visual** — default for supported content;
- **Source** — exact text.

The editor remembers the last mode. The first candidate is Milkdown/Crepe, but this is **spike first**.
It is accepted only after round-trip tests prove that Alles-specific and Obsidian syntax survives.

The editor must preserve:

- YAML frontmatter;
- wikilinks and aliases;
- embeds;
- task syntax;
- tables;
- fenced code;
- math;
- Mermaid;
- callouts;
- raw HTML;
- comments and block IDs;
- unknown syntax.

Unsupported content appears as a protected raw block instead of being rewritten.

Every open file carries a version/hash. If Obsidian or another program changes it, Alles stops autosave
and shows a conflict comparison. It never silently overwrites the external change.

Docs includes autosave status, local draft recovery, revision history, and trash.
`Ask Aide about this note` opens Aide with the note attached; there is no separate Ask Docs chat mode.

Obsidian is a deeply supported and recommended companion, not a runtime requirement. For the
connected-vault desktop profile, setup checks for Obsidian, guides installation when it is missing, and
offers the shared vault and companion plugin. Alles still owns a complete Visual/Source editor so a
headless Linux server, phone, recovery session, or broken Obsidian install never blocks access to the
vault.

**Keep the vault inside the Alles folder** defaults on and uses `~/Alles/Vault`. Turning it off connects
an explicitly selected existing vault. Changing this later uses a move wizard: create a safety backup,
check space and permissions, pause saves/watchers, stage a copy, verify hashes, update configuration and
indexes, reopen the vault, and delete the original only after a separate confirmation. A failure or
external edit leaves the original usable and rolls back the switch.

For journal migration:

- new non-private daily entries can use Markdown daily notes;
- existing locked journal data stays in its protected store;
- a locked journal is never copied into plaintext automatically;
- moving existing journal data into the vault requires an explicit privacy warning and confirmation.

### Files

Files remains Alles-native. File Browser is a credited interaction reference, not an embedded Go/Vue
service.

Desktop layout:

- left location rail;
- center list or visual grid;
- right preview and inspector.

Mobile shows one pane at a time with a selection action bar.

Locations include:

- Alles files;
- explicitly approved local folders;
- macOS sync folders such as iCloud Drive when present;
- WebDAV;
- S3/object storage with honest capability limits.

External local folders begin read-only. The owner can grant management per location.
Every file identity is `location_id + normalized_path`, not path alone.

Search can switch between **Alles only** and **All locations**.

Core operations:

- multi-select;
- cut, copy, paste, move, duplicate, and rename;
- drag and drop;
- folder upload;
- resumable upload queue;
- progress, cancel, and retry;
- replace, keep both, or skip conflicts;
- undo for supported moves, renames, overwrites, and deletes.

Preview supports images, PDF, video, audio, text, Markdown, code, JSON, CSV, DOCX, and spreadsheets.
It never autoplays media. Markdown edits open in Docs; photo management opens the Photos/Gallery view.

Remote files can be marked available offline. Offline or concurrent changes preserve both versions.
A live remote location is not presented as a backup.

Search, storage totals, recent files, and duplicate detection use a background metadata index rather
than walking the entire tree on each request.

The personal Gallery becomes **Files → Photos**. AI-generated images become **Aide → Creations** so the
two galleries no longer share a name.

Files → Photos preserves the existing macOS PhotoKit path rather than replacing it with browser upload.
It keeps explicit confirmation, Apple permission states, batches of at most 500 visible items, Hidden
exclusion, stable source identity that prevents duplicate re-imports, and local hidden/favorite choices.
Non-macOS hosts show a clear unavailable state while retaining normal folder and upload imports.

## Specialist experiences

### Finance

Finance merges Money and Subscriptions in the interface while preserving their records.

Main views:

- Overview
- Accounts
- Transactions
- Budgets
- Subscriptions
- Import

Actual Budget is the intended Finance ledger and budgeting engine, accessed through its official Node
API and an Alles-owned bridge. The architecture spike must prove the exact supported version, managed
sync-server lifecycle, backup/restore, identifiers, currency handling, and safe migration before any
source-of-truth switch.

After that gate, Actual is canonical for accounts, transactions, payees, categories, budgets, and
schedules. Alles remains the product shell and keeps only Alles-specific sidecar data such as
subscriptions, import receipts, source-currency/rate evidence, notification provenance, and links to
Actual IDs. It does not keep a second writable ledger.

If Actual cannot safely be the core, Phase 8 remains blocked until the architecture is fixed. The plan
does not silently demote it to optional import/export. Explicit import/export and reconciliation are
still built first so migration can be proven before the canonical switch.

Every transaction stores:

- original amount;
- original currency;
- exchange rate and source;
- base-currency amount;
- rate date;
- import/source identity.

Changing the base currency does not rewrite original values.

CIBC and China Merchants Bank each receive a connection report covering official APIs, supported Actual
bank-sync providers, region/account eligibility, cost, privacy, refresh behavior, and failure modes.
Where a supported provider is proven, the owner can connect it through Actual. Otherwise support begins
with safe statement or device-notification imports. Alles does not scrape bank websites, store bank
passwords, or pretend an unofficial feed is reliable. Every import has a preview, duplicate detection,
stable source identity, and undo.

### Inbox, Library, and Health

Inbox combines Mail and Contacts but keeps their data models separate. Contacts appears where composing,
searching, or viewing a sender needs it.

Library combines Books, Read/Watchlist, and explicitly saved News. A feed entry only enters Library when
the owner saves it.

Health combines health logs and habits. Selecting a Project never adds Health records to AI context;
sensitive records require an explicit grant.

### Passwords

Passwords is the renamed secure vault. It stays separate from Files and is never treated as Project
folder context automatically.

The browser extension starts with Chrome and Chromium browsers.

Connection flow:

1. Enter the Alles URL.
2. Open **Connect browser**.
3. Unlock Passwords in Alles.
4. Approve and name the browser.
5. Revoke it later from Connected browsers.

The extension never asks the user to paste a raw vault token.
Pairing identifies a browser but does not permanently unlock the vault.

Version-one defaults:

- current-tab permission only after the extension is clicked;
- permission for the chosen Alles server;
- exact-site matching;
- HTTPS required except localhost;
- release only the selected credential;
- never submit a form automatically;
- never fill a password-change or unrelated third-party frame by accident;
- lock on inactivity, browser close, or computer lock;
- no permanent **never lock** option;
- no analytics or external service.

Direct save/update prompts, TOTP filling, Firefox, inline suggestions, Safari, and passkey filling come
after the minimal fill flow is reviewed.

### Server

Server replaces System and manages only Alles and Alles-owned companions.

It does not become a root-level host administration product.

Views:

- Overview
- System
- Services
- Storage and Backups
- Network and Access
- Logs and Maintenance

Managed services may include:

- Alles core;
- background Aide scheduler/workers;
- managed Andromeda/SearXNG;
- an Alles-installed proxy;
- future Alles-owned helpers.

External Caddy, Ollama, AdGuard, Nginx Proxy Manager, or other services remain read-only unless Alles
prepared that exact pinned companion and its dual ownership markers still verify.

Normal Server controls exclude arbitrary shell, process killing, package management, firewall changes,
host shutdown, and unmanaged container control.

The existing system monitor remains as the System view and clearly separates:

- server-host uptime;
- Alles process uptime;
- the browser/client device.

Host operating system, platform, and uptime come only from server-side detection. Client information is
labelled **This browser**. A macOS or Linux host must never display Windows merely because a browser or
cached client value reported it.

Destructive Server actions require recent owner authentication, explicit typed actions rather than shell
strings, capability detection, impact text, and an audit record.

#### Proxy and DNS helpers

Reverse proxy and DNS filtering are different jobs and are never presented as one switch.

[Nginx Proxy Manager](https://nginxproxymanager.com/guide/) is the optional visual Compose companion.
Alles pins its image, prepares without starting, keeps the admin listener on loopback, and activates
public listeners only after exact port/interface preflight and rollback capture. The native Server
surface shows proxy-host and certificate state and creates typed proxy hosts through an encrypted local
API token. Caddy remains an owner-managed alternative.

[AdGuard Home](https://github.com/AdguardTeam/AdGuardHome) is the optional DNS companion. Alles pins and
prepares it without starting, checks TCP and UDP DNS listeners, seals its admin credential, and exposes
status, query statistics, filtering, and rewrites through the published API. Alles never changes router
DNS, DHCP, firewall, or operating-system resolver settings.

For either service, an external instance gets health/setup context only. An Alles-prepared instance has
fixed definitions, private data, narrow lifecycle controls, backup coverage, explicit activation, and a
keep-data removal path.

## Backup and recovery

Backup is a separate concept from sync and online file browsing.

Default backup coverage includes critical state:

- SQLite database;
- settings and encrypted connector data;
- encryption keys;
- Passwords ciphertext and attachments;
- Markdown vault;
- managed files;
- tasks, calendars, mail cache, contacts, Finance, Project metadata, background Aide definitions and history;
- indexes only when rebuilding would be expensive.

Photos are opt-in because they can dominate storage.
External locations have an explicit inclusion policy.

First-party destinations:

- local folder or drive;
- WebDAV;
- S3-compatible storage.

Kopia is the preferred engine candidate, but it is **spike first**. It must prove coverage, encryption,
incremental behavior, restore portability, and support for the chosen targets before adoption.

Every full backup is encrypted before it leaves staging. A separate limited export may be plaintext only
when it clearly excludes keys, Passwords, connector secrets, and other protected data.

Backup encryption uses a recovery key that is not stored only inside the live Alles installation. Setup
must help the owner save that key somewhere safe and verify it before the first automatic remote backup.
Losing the running server must not make a valid backup impossible to restore.

Every backup contains a manifest with format version, paths, sizes, and checksums.
The UI shows the last completed backup and the last verified restore check separately.

Restore flow:

1. Read and limit the archive safely.
2. Validate manifest, version, paths, checksums, and required files.
3. Create a safety snapshot.
4. Restore into a staging directory.
5. Boot and migrate the staged copy.
6. Swap only after validation.
7. Restart Alles.
8. Keep a rollback path.

The live SQLite database is never placed inside iCloud, Dropbox, or another live-sync folder.

## Models and AI routing

Settings defines two default model roles:

- Aide Chat;
- Andromeda.

Durable background Aide tasks inherit the Aide default unless one run explicitly overrides it.

### Andromeda local-first profile

The normal Andromeda overview is designed to run locally. It receives a bounded evidence bundle with
source title, URL, date, version, and relevant passages instead of entire unfiltered pages.

Suggested model bands are guidance, not hardcoded model names:

- **Light** — roughly 3B–4B quantized, for low-memory devices and short summaries;
- **Standard** — roughly 7B–8B quantized, the intended normal default;
- **Strong** — roughly 14B+ local or a chosen remote model, for difficult or conflicting evidence.

The owner can select the exact model for each band and override Andromeda per search. **Auto** chooses the
smallest configured local model that has passed the local quality check. Model size alone never marks a
model as suitable.

Normal search never requires a remote model. If a local model fails, runs out of memory, or cannot support
the answer, Alles keeps the regular results and offers **Retry with a stronger model**. It never sends the
query or sources to a remote model without the owner's configured permission.

Deep research has its own model override and may use a stronger model than the normal overview.

Every AI-backed feature may override its role model. A compact chip exposes the effective model where it
matters.

Endpoint model catalogs are live data, not a memorized list shipped with Alles.

- Adding an endpoint accepts custom hosts, ports, base paths, authentication, and provider adapters.
- **Refresh all** refreshes every endpoint independently; each endpoint also has its own **Refresh**.
- A successful refresh adds newly returned models to pickers.
- Models no longer returned become **Unavailable** and leave new pickers, while historical runs keep
  their exact model IDs.
- A failed refresh marks that catalog **Stale** and keeps the last good list instead of erasing it.
- Endpoints without discovery support keep an editable manual model list.
- A role/default that points to an unavailable model is visibly broken and asks for a replacement; it
  never switches silently.

The **Newest** label is shown only when the provider returns reliable version/release metadata or a
reviewed provider adapter defines it. Alles does not guess “newest” from a model name.

Custom endpoints can be saved as **unverified** when offline or unreachable. They are not treated as
healthy until a successful manual or automatic test.

### Provider account sign-in

AI and Models may offer **Sign in with OpenAI**, **Sign in with Claude**, or **Sign in with Google** only
when that provider has a current official and permitted flow for this type of client. API keys and local
or custom endpoints remain available. Alles never imitates consumer OAuth or ships a flow a provider
forbids.

Before connecting and before making an account the default, show this plain warning:

> This can use your provider quota or credits faster than normal chat.

The connection shows provider, account identity, granted scope, expiry, usage when available, and
**Disconnect**. Browser flows use state, PKCE where supported, exact callback validation, encrypted
access/refresh tokens, rotation, and revocation. A provider-support spike re-checks current official
flows and terms before implementation; unavailable account login falls back honestly to API key or a
local endpoint.

Failure behavior:

- interactive work asks what to do each time;
- background Aide pauses and notifies;
- News still produces a link digest and retries the AI summary later;
- Alles never silently switches to an expensive or remote model outside the configured fallback policy.

Model selection, endpoint health, and fallback decisions are recorded on each background Aide run.

## Settings

Settings uses ten sections:

- General
- Appearance
- AI and Models
- Andromeda
- Aide
- Connections
- Apps
- Storage and Backups
- Security and Access
- Advanced

AI and Models begins with the Aide and Andromeda defaults, followed by endpoints,
local models, discovered/manual catalogs, Cookbook, global and per-endpoint refresh, provider sign-in,
overrides, health, and usage.

Aide contains permissions, allowed tools, folders, effort, background limits, owner instructions, and
Memory controls. It has no assistant-mode setting. The task composer owns the current task's permission
profile, model, and effort override; Settings owns defaults and full catalogs.

Operational views remain in their app. Settings stores configuration.
For example, Server shows backup runs while Storage and Backups configures targets.

Connections stores credentials and connection health. The Jarvis entry controls only the optional
Discord bot connection and delivery scope.

Existing MCP support is preserved and hardened. Connections lets the owner add, edit, test, refresh,
disable, and remove MCP servers. It shows transport/origin, health, last refresh, discovered tools,
resources and prompts, plus the capabilities each server requests. Tools default disabled until the
owner grants them to unscoped Aide, one Project, or one Workflow. Local-command MCP requires review of the
exact executable, arguments, working directory, and environment names. A non-loopback remote MCP
connection requires HTTPS. Removing a tool or revoking a grant takes effect before the next call.

Simple settings save immediately with a visible Saved state. Destructive or connectivity-changing
settings use explicit review and confirmation.

## Language support

Initial interface languages:

- English;
- French;
- Spanish;
- Simplified Chinese;
- Traditional Chinese;
- Japanese;
- Korean;
- Arabic.

Keep these settings independent:

- interface language;
- region and formats;
- timezone;
- 12/24-hour clock;
- first day of week;
- Finance base currency.

The implementation uses local translation files with English fallback.
Dates, numbers, currencies, lists, relative times, and plurals use browser internationalization APIs.
Arabic sets right-to-left layout and receives dedicated layout testing.

Personal notes, mail, files, and search results are not translated automatically.
An optional Translate action creates a separate result and never overwrites the original.

Task and Calendar natural-language input must be localized before a language is called fully supported.

The README receives the same eight languages. English remains canonical, and every translation shows its
source revision and review status.

## Installation and first run

The normal path is native-first on macOS and Linux.

The installer:

- creates an Alles-owned Python/runtime environment;
- does not modify system Python packages;
- installs the `alles` command automatically;
- installs a user service with launchd or systemd-user;
- starts Alles and runs health checks;
- opens resumable first-run setup.

Docker/Compose remains an advanced server option.

Program files and personal data stay separate.
A visible default can provide:

- `~/Alles/Vault`;
- `~/Alles/Files`.

Private database, keys, runtime state, logs, and caches remain in the platform app-data directory.
Existing locations can be selected without copying them silently.

First-run steps:

1. Basics — language, name, timezone.
2. Access — this device, home network, or public server.
3. Files — create or connect a vault and file locations.
4. AI and Search — configure role models and managed SearXNG.
5. Protection — password and automatic backup.

Setup state is saved on the server after every step and can resume on another browser.

Network profiles:

- **This device only** — loopback, default;
- **Home network** — password required;
- **Public server** — authentication, proxy, and HTTPS checks required.

SearXNG stays loopback-only. The Files step exposes **Keep the vault inside the Alles folder**, enabled
by default, and previews the exact path before creation. Selecting an existing external vault leaves it
in place.

On the connected-vault desktop profile, setup checks for Obsidian, offers installation guidance, and
configures the shared vault/companion only after approval. Obsidian is strongly recommended for the full
desktop knowledge workflow but is not required. The server and recovery editor remain usable on
headless Linux even when no GUI app can run there.

The command surface includes start, stop, restart, status, open, logs, doctor, update, backup, and
uninstall. It controls the supervised service and never kills an unknown process merely because a port
is busy.

Normal updates:

1. create a preflight backup;
2. verify the downloaded release;
3. stage the new version;
4. run checks and migrations;
5. switch versions;
6. health-check;
7. roll back on failure.

Uninstall removes program files, the service, launcher, and managed companions.
Personal data is preserved by default and needs a separate explicit deletion confirmation.

## Acknowledgements and notices

Credits are split by purpose:

- origin and direct adaptations;
- product inspiration;
- open-source components;
- models and datasets;
- skills and community sources;
- trademarks and compatibility services.

Odysseus remains the prominent origin credit.
Direct ports or adaptations from IterResearch, Tongyi DeepResearch, OpenCode, and other projects are
named individually.

Product inspiration includes only products that genuinely influenced a shipped design, including
OpenAI Codex Projects, Claude Desktop/Cowork, Obsidian, Actual Budget, SearXNG, File Browser, OpenClaw,
Perplexica, Immich, btop, and neofetch. Perplexica is credited as early AI-search inspiration; the later
Google-style AI Overview direction means Andromeda is not presented as a Perplexica reskin or runtime
dependency.

Files:

- `ACKNOWLEDGMENTS.md` — readable story and major credits;
- `THIRD_PARTY_NOTICES.md` — complete bundled dependency inventory;
- `licenses/` — required license texts;
- Settings → About → Credits — in-app view.

A structured credits manifest drives the readable pages and release notices.
Release checks fail when a direct dependency, vendored/CDN asset, font, model, dataset, or skill source
has no entry. Packaged releases also inventory transitive bundled dependencies.

Provider and product names do not imply endorsement.

## Technical architecture

### Keep one application

Alles remains one FastAPI application with SQLite/SQLAlchemy and a vanilla browser client.

Companion processes are limited to jobs that need their own runtime, such as:

- managed SearXNG;
- an Actual sync server and official Node API bridge if the Finance-core gate passes;
- a supervised helper required by the native installer.

They do not get separate user accounts, competing settings, or independent sources of truth.

### Whole-system structure map

`specifications.md` receives one code-verified map of the current shipped system. It connects browser
surfaces and vanilla JavaScript modules to `app.py`, FastAPI routers, services/jobs, SQLite and file
stores, vault/blob locations, supervised companions, and external connectors. It labels trust
boundaries, process boundaries, owner, and source of truth.

Phase 0 builds the current-state map from code and tests without reading private data. Every later phase
updates the nodes it changes. Release hardening reconciles the final map against actual routes,
processes, stores, and connector tests; a future component is never drawn as already shipped.

### Data ownership

| Data | Canonical store |
|---|---|
| Structured app state | SQLite |
| Human-authored knowledge | Markdown vault |
| Managed files and media | Approved file locations |
| Finance ledger after the Actual gate | Actual budget file through the managed bridge |
| Finance subscriptions/import evidence | SQLite sidecar linked to stable Actual IDs |
| Password contents | Encrypted vault records and encrypted attachments |
| Reviewed Aide memories and owner instructions | SQLite with source and scope metadata |
| Large generated artifacts | Blob store with database references |
| Search and duplicate metadata | Rebuildable indexes |
| Backup snapshots | Encrypted backup repository |

A mirror is never treated as a second authority without an explicit sync identity and conflict rule.

### Folder-backed Project environments

The Project record stays small. It stores an ID, display name, canonical folder path, optional
instructions/scratchpad, display color, and last-opened state. Aide conversations and runs may store its ID.

The folder is the default working directory and context priority. It is not automatically the only
allowed directory. Access outside it uses the normal path and delegated-action permission checks, and
the run records that it left the Project root.

Project selection never creates cross-app membership rows. Files metadata, tasks, notes, searches,
Health, Passwords, and other records keep their existing owners.

If the root is unavailable, the Project becomes **Folder missing**. Alles preserves its threads and
settings and requires an explicit relink instead of guessing a replacement path.

### Model resolver

One resolver calculates the effective model from:

1. explicit request or run override;
2. workflow override;
3. feature default;
4. role default;
5. an allowed fallback in the same privacy/cost class.

The resolver returns endpoint, model, privacy class, price metadata when known, and the reason for the
selection. Foreground and background Aide calls use the same resolver.

### Background Aide records

The durable background core uses records equivalent to the following. Existing class, table, and API
names containing `Jarvis` are legacy compatibility names until a separate safe migration:

- **Workflow** — reusable definition and permission ceiling;
- **Trigger** — schedule, heartbeat, event, webhook, or inbound connector;
- **JarvisRun** — one execution and its state;
- **RunEvent** — append-only progress, source, tool, and output events;
- **RunPrompt** — durable choice or approval;
- **DeliveryAttempt** — one outbox item, retry, and provider response;
- **Connector** — encrypted channel configuration and allowlists.

Names may change during implementation, but these responsibilities must not collapse into one JSON
field or an in-memory task.

### Scheduler rules

- Store canonical times in UTC plus the chosen timezone.
- Give each scheduled occurrence a stable `scheduled_for` value.
- Enforce uniqueness on workflow/trigger plus scheduled occurrence.
- Claim work with a lease and reclaim stale leases after a crash.
- Default workflow concurrency is one.
- Classify failures as transient, permanent, or uncertain.
- Retry transient failures with bounded backoff.
- Never automatically retry an uncertain external side effect.
- Persist next run, last run, duration, failure, and delivery state.
- Test daylight-saving changes even when the server normally runs in a timezone without DST.

A heartbeat stores a signal fingerprint. No changed signal means no model run and no notification.

### Choices and approvals

A choice and an approval are different records.

A **choice** selects among non-mutating paths. It may be answered in Alles or, when safe, through
Discord.

An **approval** authorizes one exact mutation and includes:

- action;
- target or recipient;
- data involved;
- privacy effect;
- cost when known;
- expiry;
- effective capability.

Approvals are single-use, durable, expire, and re-check the pending action immediately before execution.
An answer from Discord can never indirectly widen the approved action.

This delegated-action gate applies to foreground/background Aide and tool-origin mutations. A direct owner action in
the normal UI uses authentication, CSRF protection, scope checks, and a clear confirmation where needed;
it does not create a pretend background-run approval for ordinary editing.

### Deliveries

Every external delivery goes through a persistent outbox.

The outbox records:

- run and event;
- channel;
- privacy level;
- attempt count;
- next attempt;
- safe error class;
- provider message ID;
- final state.

Delivery failure does not change a successful workflow into an unknown state. The result and its
delivery status remain separate.

### Storage locations

A Storage Location exposes capabilities rather than pretending every backend is a normal disk.

Possible capabilities:

- list;
- read;
- write;
- atomic rename;
- conditional write;
- version;
- share;
- offline cache.

WebDAV writes use ETags and conditional requests where supported.
An S3 move is copy, verify, then delete; it is never labelled atomic.
If an S3 object reports a version ID, logical delete fails closed because delete-marker creation
cannot be atomically conditioned on that exact version.

Every operation re-checks root confinement. Symlink changes between validation and use must not escape an
approved local root.

### Indexing

Metadata and text indexes update from:

- known Alles writes;
- filesystem events;
- remote provider change tokens when available;
- bounded periodic reconciliation.

Index work is incremental, resumable, and lower priority than interactive requests.
The UI can report **Indexing** or **Results may be incomplete** instead of blocking.

### Observability

Server exposes redacted structured information for:

- process and companion health;
- scheduler lag;
- queued/running/failed background Aide runs;
- delivery backlog;
- storage/index jobs;
- backup and restore state;
- update state.

Logs never include passwords, API keys, connector URLs containing secrets, full private prompts, vault
tokens, or decrypted Passwords data.

## Security boundaries

### Network

- Fresh installs bind to `127.0.0.1`.
- LAN mode cannot be enabled without owner authentication.
- Public mode requires authentication, HTTPS, trusted hosts, and proxy checks.
- CORS is limited to configured Alles origins and narrowly designed extension flows.
- API tokens become scoped and revocable instead of universal bearer access.

### Connectors

Discord, WebDAV, S3, OAuth, webhook, and other credentials are encrypted at rest, masked in API
responses, redacted from logs, and rotatable.

MCP credentials follow the same rule. MCP schemas, prompts, resources, and tool results are untrusted
content: they cannot change the system prompt, create memory, grant themselves, or widen a Project or
Workflow capability. Stdio servers run only the reviewed command/environment; remote servers are
origin-pinned. A transport and capability-security spike covers the existing stdio/SSE implementation
before it is exposed through the consolidated Connections UI.

The Discord bot pairs with one numeric owner ID using a short-lived one-time flow.
It ignores other users and bot/webhook messages by default.

### External content

Mail, feeds, web pages, Discord messages, files, and tool output are untrusted input.

They cannot:

- change the system prompt;
- grant capabilities;
- approve their own actions;
- select a more privileged model/tool path;
- write durable memory without a trusted policy.

### Models

Before private context leaves the server, Alles shows or records the provider involved.
Automatic fallback remains inside the configured privacy class.

### Files and Docs

- New external roots begin read-only.
- Markdown saves use a temporary file, flush, and atomic replace.
- A save includes the expected previous hash.
- Unknown bytes are never decoded with replacement and written back.
- Delete uses trash.
- Multi-file rename/link rewriting uses an operation journal and is resumable or undoable.

### Backups

Every full backup is encrypted before upload or final local placement. The application secret key may be
included only inside the encrypted backup container. Recovery-key export and restore are tested without
access to the original installation.

Backup validation includes:

- path traversal defense;
- archive and extracted-size limits;
- free-space preflight;
- checksums;
- SQLite integrity;
- schema compatibility;
- selected-location coverage.

Background Aide workers and database writers stop for the final restore swap.
An interrupted restore must leave the original installation bootable.

### Passwords and shares

- Extension tokens are narrow, revocable, device-bound, and are not vault unlock tokens.
- Public-share passwords use a slow password hash.
- Unlock, pairing, and public-share attempts are rate-limited.
- Remote extension connections require HTTPS.

### Finance import safety

Imports never execute statement content, formulas, or embedded links.
Re-importing the same source identity is idempotent.

## Migration strategy

### Global rule

Every migration follows:

1. Expand — add the new schema or file layout.
2. Copy/backfill — keep the old source intact.
3. Verify — counts, hashes, references, and behavior.
4. Switch reads.
5. Observe for at least one stable release.
6. Contract only in a later release with a fresh backup.

Database migrations are idempotent and safe to run twice.
Destructive SQLite rollback relies on the verified pre-migration backup, not a fragile reverse ALTER.

### Navigation and names

- Old Today routes to Home.
- System routes to Server.
- Secrets routes to Passwords.
- Money and Subs route into Finance.
- Notes and Journal route into Docs.
- The personal-media Gallery routes into Files → Photos.
- The AI-image Gallery routes into Aide → Creations.
- Old Cowork or standalone Jarvis view identifiers open the single Aide interface without selecting a mode.

Old subdomains and view IDs remain redirects through at least one stable compatibility window.
Bookmarks keep working.

### Personas

Keep personas. Fix **None** so it reliably selects the base assistant with no persona injection, revise
the shipped defaults, and preserve custom names, prompts, linked documents, dates, and IDs through the
migration.

### MCP connections and memory

Inventory and preserve current MCP servers, routes, UI entries, grants, and tests before moving them into
the consolidated Connections design. Existing connections begin disabled if their old permission scope
cannot be mapped safely; the owner reviews them instead of losing them.

Inventory current memory, user-model, persona-linked, and system-prompt data without reading private
content. Preserve provenance where known. Unknown or externally derived entries do not become trusted
memory automatically; they remain reviewable until the owner accepts or deletes them.

### Current automations

Convert existing rules into paused background Aide Workflows and Triggers.
The owner reviews their model, permissions, delivery, and schedule before enabling them.
Compatibility APIs can read the new records during the transition.

### Projects migration

Use each existing Project working directory as its folder path when that directory still exists.
Keep its chats, instructions, and scratchpad data. A Project with no valid folder becomes **Folder
missing** and waits for explicit relinking; it is not deleted or silently pointed elsewhere.

Projects do not gain cross-app resource memberships during migration.
The current `Project` and `Session.project_id` records already provide most of this model. Reuse them and
add only missing folder-state or safety fields instead of replacing the schema.

### Files migration

Backfill the current Files root as the built-in `alles` Storage Location.

Metadata currently keyed only by path gains a location identity:

- tags;
- stars;
- colors;
- comments;
- versions;
- trash;
- shares.

Backfill and verify every row before switching lookups.

### Docs and Journal

Do not mass-rewrite Markdown during migration.
Index existing files in place and test them against the visual editor corpus.

Existing Notes migration is idempotent by stable source identity.
Locked Journal content remains protected until an explicit owner migration.

### Finance migration

Money and Subscription rows remain in their existing tables for the first Finance release.
The new UI composes them. Multi-currency columns are additive and backfilled without changing original
amounts.

The Actual-core spike and bridge run against synthetic copies first. Migration maps stable IDs, counts,
balances, transfers, categories, payees, schedules, currency evidence, and subscription links. The
existing ledger remains the authority until import, round-trip, backup, restore, and parity checks pass.
At cutover, transaction writes switch to Actual in one staged change; Alles does not dual-write two live
ledgers. Old rows remain read-only for at least one stable release and are removed only after a fresh
verified backup and owner confirmation.

### Server compatibility

`system.localhost` and current system APIs remain compatibility aliases.
Management controls are added behind capability detection; unsupported installs remain read-only.

## Resolved product decisions

1. **Personas stay.** Repair **None**, revise the built-ins, and preserve custom personas.
2. **Actual Budget is Finance's core.** The architecture and migration must make that safe; failure blocks
   Phase 8 instead of silently changing the decision.
3. **Obsidian is deeply supported and recommended, not required.** Alles keeps its own complete editor so
   headless hosting, mobile access, and recovery do not depend on a desktop GUI application.

## Implementation phases

These are dependency boundaries, not dates. Each phase ships in small reviewable changes.
Phases 0 and 1 are release blockers, not optional setup. Urgent Phase 0 protections can ship as focused
hotfixes, but no feature phase begins until both gates pass.

### Phase 0 — Recovery gate and baseline

Do this before redesigning screens or migrating data.

Live implementation status and issue-sized slices are tracked in
[`phase-0-execution.md`](phase-0-execution.md).

- Inventory every current data class and configured root from code and synthetic fixtures, without
  reading private user content.
- Hotfix fresh installs to bind to loopback.
- Retire the prototype broad browser-extension flow: stop issuing broad tokens, revoke existing broad
  extension tokens with a clear upgrade notice, and provide the Alles web UI as the safe fallback until
  the replacement is ready.
- Stop existing commands from killing an unknown process because it owns a port or performing an
  unstaged in-place update. Show safe diagnosis or manual recovery instead.
- Patch legacy automation bookkeeping so an action is not marked successful before it happens and an
  uncertain external effect is never retried blindly.
- Replace the incomplete backup/restore path with the manifest, validation, staging, and rollback flow.
- Produce a consistent SQLite/WAL snapshot while synthetic writers are active.
- Add full-backup encryption and test recovery using the separately saved recovery key.
- Do not wait for Kopia here; first make the current archive path safe and recoverable.
- Add synthetic upgrade fixtures for every supported older schema.
- Build the current whole-system structure/trust map in `specifications.md` from code and tests.
- Inventory current MCP connections, memory/user-model records, personas, system-prompt settings, and
  every app action Aide can currently perform, without reading private content.
- Capture the current Andromeda/search latency baseline on named reference hardware.
- Preserve regression fixtures for the working Photos label alignment and macOS PhotoKit path.
- Add the reported deep-research **No information could be gathered** failure to the regression corpus.
- Record current route, subdomain, and deep-link compatibility tests.
- Record current desktop/mobile browser baselines with isolated `ALLES_DATA`.
- Add build/version metadata and a compatibility version to backups.
- Define feature flags for unfinished new surfaces.

**Gate:** using only a clean release, backup repository, and exported recovery key, a verified backup can
restore into a throwaway directory, migrate, boot, and preserve expected counts, file hashes, and SQLite
integrity after concurrent writes. A default install is unreachable from another device, a legacy broad
extension token is rejected, and no unknown process is killed. No later schema migration starts before
this passes.

### Phase 1 — Platform and security foundation

#### 1A — Shared safety foundations

- Add device/LAN/public access profiles.
- Add trusted-host, scoped-token, reauthentication, rate-limit, and CORS foundations.
- Move connector secrets into one encrypted storage path with masking and rotation.
- Add the service-manager abstraction used by launchd, systemd-user, and Compose.
- Add structured, redacted logs and process/runtime health.
- Add the three model roles and shared model resolver.
- Add provider adapters, live endpoint catalogs, stale/unavailable states, and reconciliation for global
  and per-endpoint model refresh.
- Add trusted memory records, provenance/scope, Off/Ask/Auto policy, incognito exclusion, and separation
  between editable owner instructions and immutable safety rules.
- Preserve current MCP records while moving their credentials into the shared encrypted connector path.
- Run the current-provider account-authentication spike before exposing any OAuth button.
- Add language/region/timezone settings and the translation helper before creating large amounts of new
  UI text.
- Add stable API error codes while preserving human-readable fallback messages.
- Harden the current Markdown paths with expected-hash saves, atomic replace, and trash before adding a
  new visual editor.
- Add root-confinement checks to current local file operations.
- Move public-share passwords to a slow password hash and rate-limit share access.

#### 1B — Server foundation

- Build Server as a read-only-first composition of the current system monitor, backups, network access,
  logs, and owned-service health.
- Keep System routes and subdomains as compatibility aliases.
- Fix host/client platform detection and add macOS/Linux-host crossed with Windows/macOS/Linux-browser
  fixtures so client information can never replace the server OS.
- Complete the Nginx Proxy Manager/native-proxy and AdGuard decision reports, including the linked video,
  current official docs, ownership, ports, network changes, backup, removal, and rollback.
- Add controls only for services Alles can identify as owned; unsupported actions remain unavailable.
- Require recent authentication and typed capabilities for each destructive control.

#### 1C — Backup destinations

- Re-run the full recovery gate after connector secrets move into encrypted storage.
- Run the Kopia spike against the recovery manifest and staging rules.
- Re-validate the local destination, then add WebDAV and S3 one at a time after each encrypted connector
  path and disaster-recovery test pass.
- If a target or Kopia fails its spike, keep the safe encrypted local backup path and leave that target
  unavailable rather than weakening recovery rules.

**Gate:** an unauthenticated LAN client cannot reach a default install; no plaintext test secret exists
in the isolated database, settings, API responses, logs, or backup artifacts. Concurrent Markdown edits
and local-root escape tests preserve data. Server cannot control an unmanaged service. Every enabled
backup destination passes recovery without the original installation. Every host/browser pairing shows
the correct server OS, and no proxy, DNS, router, firewall, or privileged-port change happens without an
exact approval and rollback path.
Model discovery covers added/removed models, custom ports, timeout, authentication error, malformed
reply, stale last-good data, and one failed endpoint during Refresh all. Provider sign-in covers cancel,
state mismatch, expiry/refresh, revoke, account switch, denied scope, and unsupported-provider fallback.
Memory policy covers restart, incognito no-trace, untrusted-memory attempts, and clear-all.

### Phase 2 — Folder Projects and durable background core

- Reuse and simplify the current folder-backed Project and session relationship.
- Add an unscoped no-folder task context, Project/thread grouping, missing-folder state, and explicit
  relinking. Do not expose the legacy General label as a category or Project.
- Make the Project folder the default command, search, context, and output location while keeping
  approved outside-folder work possible and visible.
- Migrate existing Project folders, chats, instructions, and scratchpads without creating cross-app
  resource memberships.
- Add Task stage compatibility for the current `done` state, so Home and background Aide can use Doing and
  Waiting before the full Plan board ships.
- Add Workflow, Trigger, JarvisRun, RunEvent, RunPrompt, DeliveryAttempt, and Connector storage.
- Build scheduler leases, occurrence idempotency, concurrency, retries, missed-run policy, and
  heartbeat fingerprints.
- Route foreground/background Aide and tool-origin mutations through one delegated-action permission gate.
- Build the persistent delivery outbox without Discord-specific behavior.
- Add event hooks from existing apps.
- Migrate current automations as paused workflows that need review.
- Add capability grants that can scope existing MCP tools to unscoped Aide, one Project, or one Workflow.
- Reconcile interrupted legacy background work honestly.

**Gate:** Project commands and relative outputs start in the selected folder; outside-folder work is
visible and permission-checked; a moved folder requires relinking while its threads remain. Crash tests
immediately before and after each test side effect use provider idempotency where available. When an
external outcome cannot be proved, the run becomes **uncertain**, is never retried automatically, and
asks the owner. Choices, approvals, runs, retries, and delivery state survive restart.

### Phase 3 — Product shell, Home, Aide Projects, and Settings

- Make Home the default page and keep the legacy launcher reachable through the app drawer during the
  transition.
- Build the final navigation shell behind per-destination feature flags. Promote Aide and Andromeda to
  permanent destinations only after their own gates pass.
- Add Needs you, Schedule, In progress, Briefs, and Pinned apps.
- Add the consolidated Settings sections.
- Add Aide and Andromeda model defaults. Background Aide inherits the Aide choice unless one run has an
  explicit override.
- Add global and per-endpoint model refresh, catalog status, manual model editing, and unavailable-model
  replacement flows.
- Add provider account connections only for flows accepted by the Phase 1 spike, including the quota or
  credits warning and Disconnect.
- Add permission, allowed-tool, background-limit, Memory, and owner-instruction controls without adding
  assistant mode controls.
- List loose conversations directly under **Tasks** and folder-backed conversations under a separate
  **Projects** category. Do not show General or add a Projects app.
- Add old-name, old-view, and old-subdomain redirects.
- Keep all specialist app behavior available during the shell migration.

**Gate:** every old bookmark still lands on its feature; no destination is promoted before it works; all
current apps remain reachable in at most two actions; Home works with no configured model. Model and
provider settings expose the same effective choices everywhere, one endpoint failure does not break the
others, and the selected Aide model and permission settings survive restart.

### Phase 4 — Aide and Andromeda

#### 4A — Aide

- Make every Aide conversation tool-capable. Simple questions may get simple answers; work uses approved
  tools automatically when useful.
- Remove the old Chat/Agent switch, the temporary Chat/Jarvis selector, Answer only, and every default
  mode setting.
- Remove the separate Ask Docs and Research toggles.
- Remove Compare instead of moving it to another action.
- Detect research-worthy requests, ask the owner, and continue approved research in the same task.
- Add the desktop-open sidebar with its split-sidebar control, mobile-closed overlay, separate
  Tasks/Projects categories, exact conversation/Project top-bar treatment, custom multipurpose `+`
  menu, speech, and optional right task-tools edge sidebar.
- Add the text-first Brain, Skills, and Reminders tools in the same primary group as New task and
  Scheduled, without a separate Tools heading. Keep background checks in Settings. Give each row a
  restrained matching icon. Give Tasks
  and Projects stronger type and group spacing without adding separator clutter.
- Use 1-pixel borders and tight 3–5-pixel corner radii, including one composer border. Keep one text-only,
  icon-free composer permission control with
  exactly auto mode, ask for approval, and plan; only Auto mode is purple. Keep desktop top-bar icon
  controls compact, preserve mobile touch targets, and never add a second textarea-focus bezel inside
  the composer. Add compact per-task model and effort controls. Let Search extend left across the Aide
  wordmark with transform-only motion. Keep Settings as footer text, add Home, and align microphone/send
  controls at 36 pixels on desktop and 44 pixels on mobile.
- Fix **None** as the no-extra-prompt default, revise built-in personas, and preserve custom personas.
- Let longer work keep running as Aide in the same conversation without losing Project context.
- Fix streaming scroll ownership.
- Remove repeated author labels. Show thinking, progress, and steps before the answer, with completed
  detail collapsible from a disclosure that remains before the answer. Keep conversation and Project
  naming in the top bar instead of repeating it inside the thread.
- Add the vertically centered message rail only at three or more user messages, with one
  keyboard-accessible tick per message, one scroll-aware bright current tick, stable hit geometry,
  pointer-proximity scaling, focused-tick reach, and click-to-jump behavior. Keep pinned summaries out.
  Make Terminal replace the task-tools body with only the terminal surface.
- Let Git carry safe uncommitted Project changes when switching local branches. Show conflicts clearly
  only when Git proves the switch would overwrite work, and keep the branch menu attached to its button.
- Add Remember this, Forget this, memory suggestions/review, scope display, incognito no-memory, and
  visible owner-instruction/memory provenance.
- Complete and test the Aide capability rows for Home, Aide, Plan, Docs, and Andromeda; later phases own
  their specialist rows.
- Fix and screenshot-test the original incognito states on desktop/mobile; keep the token glyph pending
  owner visual approval instead of inventing one.
- Show the effective model and provider before private context leaves Alles.

#### 4B — Andromeda

- Complete the managed SearXNG spike first: pin the image/version, prove loopback isolation, health,
  supervised start/stop, safe update, and low-resource startup.
- If that spike fails, support an external SearXNG URL without claiming managed support.
- Build one result page with AI Overview above the normal result list.
- Integrate managed and external SearXNG.
- Keep AI Overview and normal-results settings independent.
- Support standalone `!ai` anywhere in the query as a one-request overview skip.
- Render regular results without waiting for overview generation.
- Build the bounded evidence bundle and Light, Standard, Strong, and Auto local-model behavior.
- Add primary-source routing, full-page retrieval, version/date extraction, and freshness checks.
- Add claim-to-citation verification and a clear insufficient-evidence state.
- Replace the reported deep-research no-information dead end with failure details, attempted sources,
  normal links, and Retry/Broaden/Edit/Return recovery actions.
- Add citations, source quality display, and saved results.
- Connect long searches to background Aide research.
- Add Server health for managed SearXNG.

**Gate:** normal overview-plus-results, `!ai` results-only, globally disabled overview, disabled normal
results, both disabled, no-model, no-SearXNG, timeout, partial-source, and offline states all produce
useful output or clear recovery steps. Software fixtures confirm that stale versions are not presented
as current and every factual claim marked as verified is supported by its cited page. A Standard local
model must pass the representative grounding corpus on supported baseline hardware before it becomes a
default; failure leaves normal results usable and never triggers a silent remote request.
The old no-information fixture plus empty provider, blocked page, and extraction failure all retain
useful recovery. Regular links and overview first text meet the locked Phase 4 speed budget.
Aide success, failure, cancellation, restart, keyboard, and screen-reader fixtures prove steps-before-answer
ordering, the steps toggle, message-rail navigation, scroll ownership, one-mode automatic tool use,
persona None, memory controls, and incognito behavior.

### Phase 5 — Background Aide and channels

#### 5A — One Aide, foreground and background

- Remove all Chat/Agent/Jarvis mode controls and route every conversation through one tool-capable Aide
  runtime.
- Build Workflows, Runs, Schedule, and Connections inside the Aide shell using Aide product language.
- Add capability review, run timelines, durable choices, approvals, cancel, retry, and resume.
- Add exact schedules, intervals, heartbeats, events, and webhooks.
- Keep long work in the same conversation when it moves to a durable background run.
- Keep old `jarvis_*` storage and API names internal until a separate compatibility-safe migration.
- Preserve and harden existing MCP support in Connections: add/edit/test/refresh/disable/remove servers,
  inspect discovered tools/resources/prompts, and enforce unscoped-Aide/Project/Workflow grants.
- Surface Needs you and In progress in Home.

#### 5B — Jarvis Discord connection

- Add paired owner DMs and exact private-channel allowlists.
- Add non-mutating choices and in-app mutation approvals.
- Add privacy-aware delivery and revoke.

**Gate:** wrong users, wrong channels, forged choice IDs, duplicate events, reconnects, revoked pairing,
quiet hours, model failure, and server restart are covered. Foreground/background transitions stay
inside one Aide conversation and preserve the active Project, task state, and history. MCP malicious schemas/output, secret redaction,
offline servers, removed tools, revoked grants, and restart pass.

### Phase 6 — Docs and knowledge migration

Obsidian is the recommended connected-vault desktop companion, while the built-in editor remains a
complete standalone and recovery path.

#### 6A — Editor spike

- Create a standalone KOKUEN Docs HTML starter with fake data and minor local interactions, then wait
  for explicit owner approval before changing the real Docs interface.
- Build a representative Markdown corpus, including unsupported and malformed syntax.
- Test Visual → Source → Save byte-for-byte where no edit occurred.
- Test focused edits without rewriting unrelated syntax.
- Reject the candidate if preservation cannot be guaranteed.

#### 6B — Safe editor foundation

- Extend the Phase 1 expected-hash, atomic-write, and trash foundation with conflict comparison, drafts,
  and revisions.
- Journal multi-file rename/link operations.
- Keep Obsidian filesystem watching.
- Build the safe vault move/relink transaction: backup, stage, hash, switch, rollback, and separate
  confirmation before deleting an old location.
- Capture a configured external vault in encrypted recovery archives and remap it under the restored
  Alles data root instead of writing into an old external path.

#### 6C — Unified Docs

- Add Visual and Source modes.
- Merge Notes and non-private Journal views.
- Add Ask Aide about this note.
- Preserve the private locked-Journal path and provide explicit migration.

#### Small Apps consistency follow-up

- Revise or replace the standalone Apps HTML starter and get explicit approval first.
- Make only the small spacing, type, navigation, compact-state, and shared empty/error-state adjustments
  needed to match the delivered Home, Aide, and Andromeda shell.
- Keep specialist app flows and the larger Phase 8 consolidation out of this pass.

**Gate:** simultaneous Obsidian edits, invalid bytes, crash during rename, delete/restore, large files,
and every supported Markdown construct pass. Same- and cross-filesystem vault moves, no-space,
permission failure, external edit during move, crash, rollback, and watcher restart leave the original
or verified replacement usable.

### Phase 7 — Files and storage locations

#### 7A — Location identity migration

- Add Storage Location records and management APIs without exposing credentials.
- Backfill path-only Files metadata to `location_id + normalized_path`.
- Keep compatibility reads and verify counts, paths, hashes, tags, stars, versions, trash, shares, and
  other file metadata before switching lookups.
- Do not add remote writes in this subphase.
- Reuse the location identity and operation journal for the vault-location toggle without treating live
  sync as backup.

**7A gate:** old and new lookups return the same files and metadata, and running the migration twice
changes nothing.

#### 7B — Local Files experience

- First build and test a standalone KOKUEN Files starter, then wait for explicit owner approval before
  materially changing the real Files interface.
- Add the three-pane Files interface, multi-select, operation queue, undo, and background index.
- Add explicit read-only and managed permissions for local roots.

#### 7C — WebDAV and offline cache

- Add capability detection, ETag writes, conditional conflicts, resumable transfers, and available
  offline.
- Preserve both versions when the network or ETag changes.

#### 7D — S3 and Photos

- Add honest object-storage operations and non-atomic move progress.
- Add Files → Photos while preserving the specialist gallery behavior and current macOS PhotoKit path.
- Test PhotoKit allowed/denied/restricted permission, cancellation, the 500-item boundary, repeated
  import, Hidden exclusion, source identity, restart, and the clean non-macOS unavailable state.
- Keep AI-generated media under Aide → Creations.

**Gate:** network loss during upload, move, delete, cache, and restore cannot lose the only copy.
Indexing a large location does not block interactive browsing.

### Phase 8 — Specialist app consolidation

#### 8A — Low-risk composition

- Before each specialist app or coherent app group changes visually, make a standalone KOKUEN HTML
  starter and get explicit owner approval. Begin with small consistency changes; do not redesign every
  app at once.
- Compose Plan from Calendar, Tasks, and Reminders.
- Compose Inbox from Mail and Contacts.
- Compose Library from Books, Read, and saved News.
- Compose Health from health logs and habits.
- Keep existing tables and APIs.

#### 8B — Finance schema and parity

- Add original/base currency fields, deterministic conversion records, and stable import identity using
  additive migrations.
- Backfill without changing current stored values, balances, or renewal records.
- Verify account and aggregate totals before switching Finance reads.

**8B gate:** old and new calculations match for existing data, original values are unchanged, and the
migration is idempotent.

#### 8C — Finance interface and imports

- Compose Money and Subscriptions only after the parity gate passes.
- Produce the current CIBC and China Merchants Bank connection report, then add supported Actual bank
  sync or safe statement/notification profiles according to the evidence.
- Add preview, duplicate detection, and undo.

#### 8D — Actual core and canonical cutover

- Spike the official Node API bridge and managed Actual sync-server lifecycle.
- Prove explicit export/import, reconciliation, stable IDs, currency sidecar links, backup, and restore.
- Migrate a synthetic and upgraded ledger, compare balances and counts, then switch transaction writes
  to Actual in one staged cutover without dual-writing two ledgers.
- Keep old Alles ledger rows read-only for one stable release.
- If the core gate fails, stop and return the fallback decision to the owner.

**Gate:** merging navigation changes no balances, renewals, tasks, events, mail, contacts, health records,
or Library items. Importing the same statement twice creates no duplicate transaction. An Actual-core
cutover preserves accounts, transactions, transfers, categories, payees, budgets, schedules, original
currency evidence, subscriptions links, backup/restore, and totals; failure rolls back to the unchanged
Alles ledger.

### Phase 9 — Distribution and browser access

These are independent tracks and do not share a release gate.

#### 9A — Installer and updates

- Finish the macOS/Linux native installer on top of the service abstraction.
- Add resumable server-side first run.
- Install the `alles` command automatically and expose the default-on vault-inside-Alles toggle.
- Apply the recorded Obsidian connected-vault policy and companion setup without silently modifying an
  existing vault.
- Add staged updates and rollback.
- Add safe uninstall with data preservation.

**9A gate:** clean install, upgrade, failed upgrade, rollback, and uninstall-keep-data pass on supported
macOS and Linux versions.

#### 9B — Passwords extension

- Replace the prototype browser extension with paired, current-tab, exact-site access.
- Add Connected browsers and immediate revoke.

**9B gate:** browser lock, browser restart, revoke, frames, HTTP downgrade, lookalike hosts, and rejected
legacy tokens pass before the extension is offered again.

### Phase 10 — Localization, credits, and release hardening

- Complete all eight UI languages.
- Add localized Task and Calendar input.
- Test right-to-left layout and CJK/Arabic font fallback offline.
- Publish translated READMEs with review state.
- Generate acknowledgements, notices, and license bundles.
- Run compatibility, accessibility, performance, security, backup/restore, and recovery sweeps.
- Audit every Aide capability row and record any intentional exclusion.
- Reconcile the whole-system structure/trust map in `specifications.md` with the shipped routes,
  services, processes, stores, and connectors.
- Update the rest of `specifications.md` only for behavior that is now shipped.

**Gate:** no language is labelled complete with missing keys or English-only core flows.
No bundled dependency, asset, font, model, dataset, or skill source lacks a notice.

### Phase 11 — Post-development review and handoff

- Compare every item in the original brainstorm mapping with shipped behavior and evidence.
- Perform a detailed code, security, privacy, migration, dependency, and data-loss review.
- Run the full unit and integration suites plus isolated desktop/mobile end-to-end tests on supported
  macOS and Linux using throwaway `ALLES_DATA`.
- Inspect browser console/page errors, keyboard/focus/reduced-motion behavior, offline and partial states,
  backup/restore, clean install, upgrade, failed upgrade, rollback, uninstall-keep-data, and secret leaks.
- Record commands, versions, outputs, evidence links, open risks, and intentionally deferred work in
  `docs/plans/afterlife/final-review.md`.

**Gate:** Final acceptance cannot pass with an unmapped original requirement, an unexplained failing
check, missing end-to-end evidence, or a high-severity unresolved review finding.

## Work that must stay separate

Do not combine these in one change:

- backup/restore replacement and the first destructive data migration;
- background Aide scheduler core and Jarvis Discord transport;
- the Docs editor dependency decision and vault-wide migration;
- Files location-ID migration and first remote write support;
- Finance navigation merge and the Actual canonical-ledger cutover;
- product-shell navigation changes and deletion of old routes/tables;
- service supervision and destructive Server web controls;
- installer/update work and the Passwords browser extension;
- Passwords extension pairing and broad inline-autofill permissions.
- provider account OAuth and live model-catalog reconciliation;
- MCP connection migration and granting a server's tools broadly.

## Technical spikes

| Topic | Proof required | Fallback |
|---|---|---|
| Milkdown/Crepe | Markdown preservation corpus and bundle size | Keep Source plus current reader while trying another editor |
| Kopia | encrypted incremental backup and staged restore across targets | Keep the encrypted manifest/staging archive as local backup and offer limited plaintext export separately |
| Managed SearXNG | pinned image, loopback isolation, health, update, low-resource boot | External SearXNG URL; keep AI Overview only when its retrieval path is healthy |
| Local Andromeda overview | grounded answer quality, citation support, latency, and memory across Light/Standard/Strong bands | keep normal results and offer an explicitly chosen stronger model |
| Actual as Finance core | official Node API/version, managed sync server, canonical IDs, migration parity, currency sidecar, backup/restore | keep Phase 8 blocked until Actual can safely remain the core |
| CIBC and China Merchants Bank | official/provider coverage, eligibility, cost, privacy, refresh, notification/file fallback | reviewed statement or notification import only |
| Provider account sign-in | current official permitted OpenAI/Claude/Google flows, PKCE/state, refresh/revoke, quota warning | API keys and local/custom endpoints |
| MCP transport and grants | preserve current stdio/SSE, command/origin confinement, discovery refresh, per-scope grants, hostile output | keep the connection disabled or use built-in tools only |
| Nginx Proxy Manager | pinned preparation, loopback admin, encrypted token, proxy/certificate API, exact listeners, rollback | keep inactive or use an external proxy |
| AdGuard Home | pinned preparation, TCP/UDP port 53 preflight, sealed auth, published API, config backup, failure rollback | keep inactive or use external DNS |
| WebDAV/S3 | conditional writes, interruption recovery, capability truth | Read-only connection or backup-only target |
| Packaged runtime | reproducible macOS/Linux build and update rollback | installer-created private virtual environment |
| Discord bot | owner pairing, private-channel allowlist, reconnect/dedup | outbound webhook delivery only |
| Browser extension | revocable device flow with narrow permissions | open Passwords in Alles for copy/fill |
| Background Aide continuation | safe checkpoint before/after tools and uncertain-side-effect handling | mark interrupted and ask before retry |
| Localization | offline font coverage and reviewed RTL/CJK layouts | ship a language as beta, not complete |

## Verification for every phase

Use fresh evidence before claiming a phase is complete.

Required checks, in proportion to the changed area:

- narrow unit and integration tests first;
- migration tests from supported older schemas;
- repeat each migration twice;
- server/integration tests with a throwaway `ALLES_DATA`;
- `python -m unittest discover -s tests -v`;
- `ruff check .`;
- `ruff format --check .`;
- JavaScript syntax/unit checks where present;
- browser tests on a non-conflicting port;
- desktop and mobile widths;
- keyboard and visible focus;
- reduced motion;
- console and page-error inspection;
- offline, partial, empty, failure, and recovery states;
- backup/restore verification for data-shape changes;
- focused security review for permissions, connectors, network exposure, Files, Docs, Finance, and
  Passwords.
- model-catalog refresh and provider-auth failure matrices;
- MCP malicious-schema/output and grant-revocation tests;
- exact regression fixtures named in the original brainstorm;
- credits-manifest and license updates in the same phase that adds any dependency, asset, font, model,
  dataset, adapted code, or skill source.

No phase proceeds with an unresolved data-loss, unauthenticated-exposure, secret-leak, duplicate
side-effect, or restore-blocking issue.

## Final acceptance

The redesign is ready when:

- Home is useful without AI.
- Aide has one interface and one tool-capable behavior with no Chat/Agent/Jarvis or Answer only mode.
- Aide automatically uses approved tools when useful, keeps simple answers simple, and never bypasses
  mutation approval.
- Aide shows thinking and steps before the answer, keeps completed detail reopenable, and never captures
  scroll while the owner reads or types. Its message rail jumps to each user message without replacing
  normal scrolling.
- Remember this, Forget this, review/edit/export/clear, Project scope, and incognito no-memory work, and
  untrusted content cannot write memory or owner instructions.
- Every daily product area has implemented or explicitly excluded Aide read/action/customization coverage.
- A normal Andromeda search shows a cited AI Overview above regular results, while `!ai` shows the same
  results without the overview.
- Version-sensitive software answers prefer current official sources, show when they were checked, and
  never present unsupported claims as verified facts.
- Deep research never ends at the old no-information dead end and always offers useful recovery.
- On supported hardware, normal Andromeda overviews can run entirely locally; a local failure keeps the
  regular results and never causes a silent remote request.
- Background Aide survives restarts and never performs an unapproved mutation.
- Jarvis exists only as the owner-scoped, revocable Discord bot.
- User-managed MCP connections are testable, refreshable, disableable, revocable, and scoped to the
  exact Aide/Project/Workflow grant.
- A Project selects one folder as the default working environment, keeps its threads together, and can
  work outside that folder only through visible normal permissions.
- Markdown survives visual editing and concurrent Obsidian changes.
- Vault placement is explicit and a failed move leaves the original usable.
- Files can browse approved local and online locations without confusing sync with backup.
- The macOS PhotoKit path and already-correct Photos alignment survive the Files redesign.
- Finance uses the owner-approved Actual-core decision, preserves original currency, and keeps imports
  idempotent without two writable ledgers.
- Server manages only Alles-owned services and can recover from a failed update.
- Server never confuses browser OS with host OS; proxy and AdGuard paths have recorded decisions and
  cannot mutate network settings silently.
- Model catalogs refresh globally and per endpoint, preserve the last good catalog on failure, and mark
  removed or broken defaults honestly.
- Provider account login appears only for current permitted flows and always shows the quota/credits
  warning before use.
- A verified encrypted backup can restore the whole selected installation.
- The browser extension never receives a general vault token or permanent all-site access.
- All supported languages, credits, licenses, old bookmarks, mobile flows, keyboard flows, and
  reduced-motion behavior are verified.
- `specifications.md` contains a code-verified whole-system structure/trust map, and the final review has
  line-by-line requirement, code-review, test, and end-to-end evidence.

## Explicit non-goals

- multi-user teams, roles, billing, or organization administration;
- using Jarvis as any in-app mode, runtime, model role, app, or name outside the Discord bot;
- replacing FastAPI/SQLite or adopting a frontend framework;
- using OpenClaw or File Browser as a runtime dependency;
- requiring a desktop GUI process for a headless server to boot or recover;
- full host, firewall, package, power, or arbitrary container administration;
- bank-password scraping;
- dual-writing or silently syncing two canonical Finance ledgers;
- unsupported or provider-forbidden consumer OAuth;
- a public SearXNG endpoint;
- automatic translation or rewriting of personal content;
- equal Windows support in the first release;
- deleting legacy data in the first release that introduces its replacement.

## Immediate next step

Use [`final-review.md`](final-review.md) for the owner validation and release decision. Phase 11 is
complete: 40 of 41 original brainstorm requests are satisfied and all 27 final-acceptance rows pass.
The first-class scheduled-News-to-Home/Jarvis flow was completed in the approved 2026-07-22
remaining-gap work. Only the token-glyph visual approval remains explicit future work; it is not
hidden inside the delivered status.
