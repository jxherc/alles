# alles — long-term build roadmap

## Context

`alles` is a self-hosted, single-user everything-app (FastAPI + SQLite + vanilla-JS SPA,
no build step) whose purpose is to **replace a stack of paid subscription apps** (Notion,
Obsidian, Gmail, Drive, Google Calendar, Apple Photos/Contacts, 1Password, YNAB, Simplifi,
Rocket Money, ChatGPT/Claude) with one system the user fully owns. This roadmap turns the
competitor-gap checklist into a **months-long, dependency-ordered sequence of microversions**,
each one shippable-quality and built **depth-first, one at a time** (fully built + tested
before the next starts).

It was produced by auditing every checklist item against the **current** code (16-agent sweep,
2026-06-19) — so already-shipped work is dropped, partials are completed, and only real gaps
are scheduled. The prior per-app TDD backlogs in `docs/plans/*.md` (Phases 1–15) were
**already delivered** on branch `autorun` per `docs/plans/regression.md`; their still-open /
deferred items are folded in below.

**Build discipline (every microversion):** audit by *running* the area (boot `python app.py`,
curl real flows, drive every UI view with Playwright, leave evidence under
`docs/evidence/<microversion>/`) → write tasks to `docs/plans/<microversion>.md` + `progress.json`
(≥8 tests each, build only what's missing/broken) → strict TDD (RED → GREEN) → `ruff check` +
`ruff format --check` + `node --check` on touched JS → update `progress.json` → full-app
Playwright regression with seeded data → run `python -m unittest discover -s tests`. Microversions
are milestones in `progress.json`, **not** releases — no commits between them; one clean
commit + a GitHub Release only after the final microversion and a clean regression.

### Decisions locked with the user (2026-06-19)
1. **Front-load `docs`** (Obsidian + Notion) immediately after the foundational stage.
2. **Heavy local ML is out-of-scope for now** — CLIP/visual+content search, OCR-in-images,
   face recognition, perceptual-hash dedup, object-removal/inpainting, and voice cloning are
   deferred (large onnx/torch deps). Search/dedup stay **metadata / EXIF / exact-hash**; TTS
   stays **preset-voice**. (Text embeddings via the *existing* `fastembed` dep are fine.)
3. **Realtime full-duplex voice** stays in the roadmap as a **final, gated** item (needs a
   realtime provider wired into the endpoint model; no fake shell).

### What's already done (verified in code — NOT re-scheduled)
- **Step 2B #1** typed-secret per-type field schemas (`vault.js` TYPES, card has no password
  field, API-key labeled correctly) ✓ · **Step 2B #2** full-width 7×53 journal heatmap ✓
- aide: git tools (status/diff/branch/commit/PR), subagents (`spawn_agent[s]`), plan mode,
  checkpoints/rewind, per-tool permission rules + docker sandbox, multi-session runs drawer,
  computer-use (pyautogui), chat fork + audio-overview (`services/audio_overview.py`) ✓
- calendar event search ✓ · nested/hierarchical tags (parsing) ✓ · subs price-hike detection,
  payment log + undo, forecast, duplicate detection ✓ · alles↔aide subdomain unification + SSO
  handoff ✓ · CSV transaction import + sub→money auto-post ✓ · outline/TOC pane ✓

---

## Overview — all stages & microversions

| # | Microversion | Theme | Effort |
|---|---|---|---|
| **1** | **Cross-cutting foundations** | shared layers many apps reuse | **L** |
| 1a | Share & Publish primitive | generic `share_token` + read-only `/s/{token}` viewer + permission level | M |
| 1b | Offline & sync engine | SW write-queue + IndexedDB, replay on reconnect | M |
| 1c | Local text index | reuse `fastembed`; reusable embedding/search over vault + code | M |
| 1d | Trash & restore primitive | generic soft-delete model + helpers | S |
| 1e | File versioning primitive | generalize `DocRevision` → blob revision store | M |
| 1f | Transaction ingestion + recurring-detection | OFX import + recurring-pattern finder over txns | M |
| **2** | **docs — Obsidian parity** | power editor + databases | **L** |
| 2a | Editor power-ups | folding, hover-preview, bookmarks, hierarchical tag tree | M |
| 2b | Inline query blocks + saved views | dataview code-fence, grouping, formula-lite | M |
| 2c | Bases multi-view databases | table/gallery/calendar/list over notes, relations, rollups | L |
| 2d | Canvas / spatial whiteboard | `.canvas` JSON files, nodes + edges | L |
| 2e | Panes, themes & offline | split panes/tabs + layouts, per-vault CSS, offline editing (1b) | L |
| **3** | **docs — Notion parity** | blocks, publish, workspace AI | **L** |
| 3a | Rich blocks | toggles, columns, page covers + icons/emoji, @date/@page mentions | M |
| 3b | Live embeds + synced blocks | allow-listed iframes (YouTube/Maps/tweets), mirrored blocks | M |
| 3c | Publish + templates | page→site publishing (1a), page/db templates, template buttons | M |
| 3d | Workspace AI + DB extras | ask-anything over vault (1c), in-doc automations, charts, forms, clipper | M |
| 3e | Inline comments | threaded comments/discussions anchored to text | M |
| **4** | **money & subs — financial core** | replace YNAB/Simplifi/Rocket | **L** |
| 4a | Transaction depth | splits, structured tags + receipts, cleared/reconcile | M |
| 4b | Envelope budgeting (YNAB) | assigned-vs-spent, rollover, funding targets, Age of Money | L |
| 4c | Forecast & investments (Simplifi) | spending-plan forecast, net-worth history, watchlists, holdings, alerts, dashboard | L |
| 4d | Goals, reports, currency | savings/debt goals, custom-range reports, multi-currency FX | M |
| 4e | Subs intelligence | auto-detect from txns (1f), unused detection, non-sub bills, low-balance, cancel-helper | M |
| **5** | **mail — Gmail/Apple parity** | triage, send, compose | **L** |
| 5a | Triage | list-unsubscribe, saved/smart mailboxes, search operators, archive + mute | M |
| 5b | Send control | schedule send, undo send, snooze (jobs) | M |
| 5c | Rich compose | HTML compose + inline images + multiple signatures | M |
| 5d | Rules & AI | rules engine, vacation responder, smart compose/reply (LLM) | M |
| 5e | Labels & push | multi-label + category tabs, IMAP IDLE push | M |
| **6** | **files — Drive parity** | trash, versions, share | **M** |
| 6a | Recover & history | trash (1d), version history (1e), starred, storage-quota | M |
| 6b | Browse & dedup | grid thumbnails, office preview, exact-hash dedup, activity view | M |
| 6c | Share | file/folder share links + permission levels (1a), comments | M |
| **7** | **gallery — Photos parity (metadata-first)** | organize, places, share | **M** |
| 7a | Organize & recover | captions/keywords/tags, hidden/locked album, trash (1d), favorites filter | S |
| 7b | Places & memories | GPS map view, date-based Memories/collages (no ML) | M |
| 7c | Share & motion | shared albums (1a), Live-Photo/video assets, phone-backup watch-folder | M |
| **8** | **calendar & contacts — scheduling & sync** | views, invites, sync | **L** |
| 8a | Views & scheduling | agenda + year view, default durations, ICS-URL subscribe, tz/working-hours | M |
| 8b | Invites & booking | invites + RSVP (local + email), video links, booking pages (1a) | L |
| 8c | Contacts depth | multi-field, photo, groups, dup-merge, Me card, address map | L |
| 8d | CardDAV sync | two-way contact sync (reuse caldav pattern) | M |
| **9** | **secrets — 1Password parity** | TOTP, attachments, vaults | **L** |
| 9a | TOTP + Watchtower | 2FA codes, weak/reused/expiring + breached (HIBP k-anon) | M |
| 9b | Attachments + share | encrypted file attachments, per-item share links (1a) | M |
| 9c | Vaults & unlock | multiple vaults, Travel Mode, biometric (WebAuthn) unlock | L |
| 9d | Passkeys & autofill | passkey storage, hardware-key 2FA, local browser-extension autofill | L |
| **10** | **aide — agent & assistant depth** | code, background, plugins, voice | **L** |
| 10a | Code intelligence | semantic codebase index (1c), tool-event hooks, git worktree isolation | M |
| 10b | Background agents | durable detached runs that survive browser close | M |
| 10c | Plugins via skills | git-backed shareable skill install/update (marketplace-lite) | M |
| 10d | Custom assistants | personas + knowledge files + share (1a), more MCP connectors | M |
| 10e | Vision + browser | video-input understanding, browser-automation tool (Playwright/CDP) | M |
| 10f | Realtime voice (gated) | full-duplex voice — gated on a realtime provider | L |
| **11** | **platform — macOS, mobile, unification, tests** | productionize on the Mac mini | **L** |
| 11a | macOS native | PhotoKit + EventKit + Keychain + iCloud Drive (PyObjC) full integration | L |
| 11b | Mobile | PWA offline polish (1b), optional Capacitor wrapper | M |
| 11c | Unification | alles↔aide cross-app audit + polish | S |
| 11d | Test hardening | per-module ≥8-test backlog + full regression sweep | M |

---

## Detailed breakdown by microversion

> Format per item: **name** — behavior · *why* · effort · deps · files · ✓acceptance.
> Effort: S = hours, M = a day or two, L = multi-day/structural.

### Stage 1 — Cross-cutting foundations
Built first because 2+ apps each depend on them; ordered by first consumer (docs uses 1a/1b/1c).

**1a — Share & Publish primitive** · M · deps: none
- **Generic share token + viewer** — promote the session-only `share_token` (`routes/shared.py`)
  into a reusable `Shareable` helper: a `share_token` + `share_level` (view / download) usable by
  docs, files, photos, vault items, contacts, calendar. One public read-only route family
  (`/s/{token}`) renders the right resource type. *Why: unblocks docs-publish, file links, shared
  albums, vault item shares, booking pages — one primitive, six consumers.* · files:
  `routes/shared.py`, `core/database.py` (token cols on consuming models), `static/js/util.js` ·
  ✓ create/revoke a token for a doc + a file; `/s/{token}` returns read-only HTML; revoke → 404;
  unit tests cover token mint/lookup/revoke per resource type.

**1b — Offline & sync engine** · M · deps: none
- **Write-queue service worker** — extend `static/sw.js` from read-cache to an IndexedDB
  outbox: queue mutating `/api/*` calls while offline, replay FIFO on reconnect, surface a
  "pending sync" indicator. *Why: prerequisite for offline doc/journal/task editing and the
  mobile PWA.* · files: `static/sw.js`, `static/js/util.js`, new `static/js/sync.js` ·
  ✓ go offline, edit a doc, reload → edit persists locally and POSTs on reconnect; queue
  survives a tab close; conflict = last-write-wins with a visible marker.

**1c — Local text index** · M · deps: none
- **Reusable embedding/search index** — generalize `services/rag.py` (already uses `fastembed`)
  into a small index API (`index(kind, id, text)` / `search(kind, query)`) backed by SQLite,
  reusable by vault docs and code symbols. Text-only (no OCR/CLIP — out of scope). *Why: powers
  docs "ask anything" (3d) and aide codebase semantic search (10a) without new heavy deps.* ·
  files: `services/rag.py`, `core/database.py` · ✓ index N docs, semantic query returns ranked
  hits; falls back to keyword when fastembed absent; reindex on save.

**1d — Trash & restore primitive** · S · deps: none
- **Soft-delete model** — a `TrashItem` table + `soft_delete()/restore()/purge()` helpers
  (path or row ref, kind, deleted_at, original location) and a shared "Recently deleted" view
  pattern. *Why: files + gallery both need recoverable delete; today both hard-`unlink`.* ·
  files: `core/database.py`, new `services/trash.py`, `services/files_store.py`,
  `routes/files.py`, `routes/photos.py` · ✓ delete → item hidden but restorable; restore puts it
  back; purge after N days; covered for files and photos.

**1e — File versioning primitive** · M · deps: 1d
- **Blob revision store** — generalize `DocRevision` into versioning for arbitrary files
  (snapshot-on-write, SHA dedup, capped count, restore). *Why: Drive-style version history for
  any file, not just markdown.* · files: `core/database.py`, `services/files_store.py`,
  `routes/files.py` · ✓ overwrite a file twice → 2 restorable versions; restore reverts content;
  large-file guard (size cap / delta) prevents runaway storage.

**1f — Transaction ingestion + recurring-detection** · M · deps: none
- **OFX/QFX import + recurring finder** — add OFX/QFX parsing alongside the existing CSV import,
  and a `detect_recurring(transactions)` helper that clusters by payee + cadence + amount.
  *Why: shared by money (recurring txns, bill calendar) and subs (auto-detect, unused detection)
  — the local, no-Plaid path.* · files: `routes/money.py`, new `services/txn_ingest.py`,
  `routes/subscriptions.py` · ✓ import a sample OFX → deduped txns; recurring finder flags a
  monthly Netflix-like series with ≥8 unit cases.

### Stage 2 — docs: Obsidian parity

**2a — Editor power-ups** · M · deps: none
- **Folding headings & lists** — wire CM6 `foldGutter`/`foldInside`; persist fold state in
  localStorage. *Why: navigating long notes.* · S · `static/js/vaultmd.js` · ✓ fold arrow
  collapses a section; state survives reopen.
- **Hover preview of linked notes** — debounced mouseover on `.wikilink` → popover with note
  excerpt (reuse embed render). *Why: follow links without leaving the note.* · M ·
  `static/js/vaultmd.js`, `routes/vault_md.py` · ✓ hovering `[[note]]` shows first ~200 chars;
  dismiss on leave.
- **Bookmarks** — mark a note/line; bookmarks panel jumps to it (stored in frontmatter or a
  `_bookmarks` file). *Why: quick return to key spots.* · S · `static/js/vaultmd.js` · ✓ add/
  remove/jump works; persists.
- **Hierarchical tag tree** — group the existing `#a/b/c` tags into a collapsible tree in the
  tag panel. *Why: parsing already supports nesting; only the UI is flat.* · S ·
  `static/js/vaultmd.js`, `routes/vault_md.py` · ✓ `#project/x` nests under `project`; click
  filters.

**2b — Inline query blocks + saved views** · M · deps: none (extends existing query engine)
- **Dataview-lite code fences** — render ```query``` / ```dataview``` blocks inline in preview
  using the existing `query_notes()` engine. *Why: the panel query exists but isn't embeddable in
  a note.* · M · `static/js/vaultmd.js`, `routes/vault_md.py`, `services/vault_md.py` · ✓ a query
  fence renders a live table in preview; updates on note open.
- **Grouping + formula-lite + saved views** — group results by a property; simple computed
  columns (sum/count/date-diff); save a named view (JSON). *Why: power querying.* · M ·
  same files + `core/database.py` · ✓ group-by renders sections; a saved view reopens with its
  filter/sort.

**2c — Bases multi-view databases** · L · deps: 2b
- **Multi-view DB over notes** — treat a folder + frontmatter schema as a database with
  table / gallery / calendar / list views; inline cell edit writes back to frontmatter;
  relations (link to other notes) + rollups (aggregate over linked notes). *Why: Notion/Obsidian
  "Bases" — the headline DB feature.* · L · `services/vault_md.py`, `routes/vault_md.py`,
  `static/js/vaultmd.js`, `core/database.py` · ✓ a folder renders as an editable table; switch to
  gallery/calendar; a rollup column sums a linked field; edits round-trip to the `.md` files.
  (Timeline/Gantt view: optional sub-task, marked low-priority.)

**2d — Canvas / spatial whiteboard** · L · deps: none
- **Infinite canvas** — `.canvas` JSON files (nodes = notes/cards/images, edges = arrows);
  pan/zoom, drag, link; open a node → the note. *Why: spatial thinking; Obsidian Canvas.* · L ·
  new `static/js/canvas.js`, `services/vault_md.py`, `routes/vault_md.py` · ✓ create canvas, add
  + drag nodes, draw an edge, reload restores layout; node links open notes.

**2e — Panes, themes & offline** · L · deps: 1b
- **Split panes & tabs + saved layouts** — multiple editor panes side-by-side + a tab strip;
  persist the workspace layout. *Why: compare/edit notes together.* · L (frontend) ·
  `static/js/vaultmd.js`, `static/index.html`, `static/style.css` · ✓ open two notes side by
  side; layout restores on reload.
- **Per-vault themes / CSS snippets** — user-editable `_vault-theme.css` auto-loaded; snippet
  toggle. (No plugin-JS — see out-of-scope.) *Why: personalization without a plugin runtime.* ·
  S · `routes/vault_md.py`, `static/js/app.js` · ✓ editing the file restyles the vault.
- **Offline editing** — vault edits work offline via 1b. *Why: notes must work on the go.* ·
  M · `static/js/vaultmd.js`, `static/sw.js` · ✓ edit offline, syncs on reconnect.

### Stage 3 — docs: Notion parity

**3a — Rich blocks** · M
- **Toggles + columns** — `<details>` toggle blocks and a column layout syntax rendered in
  preview + toolbar inserts. · M · `static/js/vaultmd.js`, `services/vault_md.py` · ✓ toggle
  collapses; columns render side-by-side.
- **Page covers + icons/emoji** — `cover:` / `icon:` frontmatter rendered as a header banner +
  emoji. · S · same · ✓ cover image + emoji show in header.
- **@date / @page mentions** — `@` autocomplete for dates and pages (pages already via `[[`).
  · S · `static/js/vaultmd.js` · ✓ `@today` inserts a date link; `@note` links a page.

**3b — Live embeds + synced blocks** · M
- **Allow-listed live embeds** — YouTube player, OpenStreetMap, tweets via sandboxed iframes
  from an allow-list. *Why: today only YouTube transcripts import.* · M · `routes/vault_md.py`,
  `static/js/vaultmd.js` · ✓ a YouTube URL renders a player; non-allow-listed host shows a link.
- **Synced blocks** — a block referenced by id mirrors edits across notes (one source of
  truth, computed on render). · M · `services/vault_md.py`, `static/js/vaultmd.js` · ✓ edit
  source block → all mirrors update on render.

**3c — Publish + templates** · M · deps: 1a
- **Public web publishing** — publish a note/folder as a styled read-only site via the 1a
  share primitive. *Why: Notion "publish to web".* · M · `routes/shared.py`, `services/vault_md.py`
  · ✓ publish → public URL renders the note; unpublish revokes.
- **Page/database templates + template buttons** — extend `_templates` with in-note "insert
  template" buttons and repeatable rows for Bases. · S · `services/vault_md.py`,
  `static/js/vaultmd.js` · ✓ a template button appends a pre-filled section/row.

**3d — Workspace AI + DB extras** · M · deps: 1c
- **Ask-anything over the vault** — RAG Q&A across all notes using the 1c index (extends the
  current per-doc `ai-edit`). *Why: "ask your notes".* · M · `routes/vault_md.py`,
  `services/rag.py` · ✓ a question returns an answer citing source notes.
- **Charts on query results** — render bar/line/pie over a query/Base (lightweight inline SVG).
  · S · `static/js/vaultmd.js` · ✓ a query → a chart.
- **Forms + web clipper** — a simple form block that appends submissions to a note; a
  bookmarklet that POSTs the current page into the vault (no browser extension). · M ·
  `routes/vault_md.py`, `static/js/vaultmd.js` · ✓ form submit creates a row; bookmarklet saves a
  page as a note.
- **In-doc/database automations** — extend `doc_tag` automations to fire on DB row changes.
  · S · `services/automations.py` · ✓ adding a tagged row triggers a rule.

**3e — Inline comments** · M
- **Threaded comments anchored to text** — a `Comment` model + inline markers + side thread.
  *Why: review/annotate your own notes.* · M · `core/database.py`, `routes/vault_md.py`,
  `static/js/vaultmd.js` · ✓ select text → add comment → marker + thread persist and resolve.

### Stage 4 — money & subs: financial core

**4a — Transaction depth** · M
- **Split a transaction across categories** — `SplitItem` child rows; summaries/budgets honor
  splits. *Why: one charge, many categories (groceries+household).* · M · `core/database.py`,
  `routes/money.py`, `static/js/money.js` · ✓ a split txn distributes across categories in the
  by-category chart and budgets.
- **Structured tags + receipt attachments** — a tags column + receipt upload (reuse
  `routes/uploads.py`, stored locally). *Why: label + prove a transaction.* · M · same +
  `routes/uploads.py` · ✓ tag filter works; receipt image attaches + previews.
- **Cleared/uncleared + reconcile** — `cleared` flag + a reconcile-to-statement flow (enter a
  statement balance, tick txns to match). *Why: catch errors vs the bank.* · M · same · ✓
  marking cleared updates a cleared balance; reconcile flags a mismatch.

**4b — Envelope budgeting (YNAB)** · L · deps: 4a
- **Zero-based / envelope budgeting** — `assigned` per category per month; "to be budgeted"
  banner; assign-every-dollar UI. · L · `core/database.py`, `routes/money.py`,
  `static/js/money.js` · ✓ assigning money decrements available; overspend flags red.
- **Category rollover** — unused/overspent balance carries to next month. · L · same · ✓
  month nav shows carried balance.
- **Per-category funding targets** — target amount + date; progress. · M · same · ✓ a target
  shows % funded.
- **Age of Money** — median days between income arrival and spend. · M · `routes/money.py`,
  `static/js/money.js` · ✓ a summary card shows a sane "age of money".

**4c — Forecast & investments (Simplifi)** · L · deps: 1f
- **Spending-plan forecast** — project balance to month-end by simulating recurring txns
  forward (reuse `_advance`). · M · `routes/money.py`, `static/js/money.js` · ✓ forecast line
  reaches month-end with projected balance.
- **Net-worth-over-time** — monthly net-worth snapshots + history graph. · M · `core/database.py`,
  `routes/money.py` · ✓ graph shows net-worth trend, not just 6-mo income/expense.
- **Watchlists + alerts + customizable dashboard** — watch a payee/category; large-purchase &
  upcoming-bill alerts (via jobs/push); reorder/hide summary cards. · M · `routes/money.py`,
  `static/js/money.js` · ✓ a watch fires an alert; dashboard order persists.
- **Investment holdings + cost basis** — manual holdings (symbol/qty/cost), optional free
  price fetch; live auto-prices marked adapted/optional. · M · `core/database.py`,
  `routes/money.py` · ✓ holdings show value + unrealized gain; price fetch optional.

**4d — Goals, reports, currency** · M
- **Savings & debt-payoff goals** — goal model + progress + payoff projection. · M ·
  `core/database.py`, `routes/money.py`, `static/js/money.js` · ✓ goal card shows progress/ETA.
- **Custom-range reports + export** — arbitrary date-range report + CSV/PDF export. · S ·
  `routes/money.py` · ✓ a custom range produces totals + export.
- **Multi-currency FX roll-up** — per-account currency converted to a base via free ECB rates
  for net-worth. · M · `core/database.py`, new `services/fx.py`, `routes/money.py` · ✓ mixed-
  currency accounts roll up correctly in the base currency.

**4e — Subs intelligence** · M · deps: 1f
- **Auto-detect subs from transactions** — surface 1f recurring candidates as proposed subs.
  *Why: local Rocket-Money-style detection, no Plaid.* · M · `routes/subscriptions.py`,
  `services/txn_ingest.py` · ✓ a recurring charge is proposed as a new sub.
- **Unused-subscription detection** — flag subs with no matching charge in N cycles. · M ·
  `routes/subscriptions.py`, `routes/money.py` · ✓ a sub with no recent charge is flagged.
- **Non-sub bill reminders + low-balance alerts** — bill reminders via `RecurringTxn`; alert
  when an account dips below a threshold. · M · `routes/money.py`, `services/jobs.py` · ✓
  reminders + low-balance push fire.
- **Cancellation helper** — store per-sub cancel URL/steps + a "cancel by" reminder (the local
  adaptation of concierge). · S · `routes/subscriptions.py`, `static/js/subs.js` · ✓ cancel link
  + reminder show on a sub.

### Stage 5 — mail: Gmail/Apple parity

**5a — Triage** · M
- **One-click List-Unsubscribe** — parse `List-Unsubscribe` header → button (http/mailto). · S
- **Saved / smart mailboxes** — `SavedSearch` model beyond the fixed unread/flagged/VIP. · S
- **Advanced search operators** — parse `from:`/`to:`/`subject:`/`has:attachment`/`before:` →
  IMAP SEARCH + cache filter. · M
- **Archive + mute thread** — IMAP MOVE archive; `muted` flag hides a thread. · M ·
  files (all 5a): `services/mail.py`, `services/mail_cache.py`, `routes/mail.py`,
  `static/js/mail.js`, `core/database.py` · ✓ unsubscribe button appears on list mail; a saved
  search reopens; `from:x has:attachment` filters; archive/mute work cache-first + best-effort IMAP.

**5b — Send control** · M · deps: jobs
- **Schedule send + undo send + snooze** — outbound queue with a send-at time + a short undo
  window; snooze re-surfaces a message later. · M · `core/database.py`, `routes/mail.py`,
  `services/jobs.py`, `static/js/mail.js` · ✓ a scheduled mail sends at its time; undo cancels
  within the window; a snoozed mail reappears.

**5c — Rich compose** · M
- **HTML compose + inline images + multiple signatures** — multipart/alternative builder, a
  light WYSIWYG, inline image upload, a signature picker. · M · `services/mail.py`,
  `routes/mail.py`, `static/js/mail.js`, `core/settings.py` · ✓ a formatted mail with an inline
  image sends and renders; signature picker switches signatures.

**5d — Rules & AI** · M
- **Rules engine + vacation responder** — extend mail automations to move/label/auto-reply;
  an out-of-office canned reply. · M · `services/automations.py`, `routes/automations.py`,
  `core/database.py` · ✓ a rule routes mail; vacation reply fires once per sender/day.
- **Smart compose / smart reply** — LLM-generated reply suggestions (reuse the model layer). ·
  M · `routes/mail.py`, `static/js/mail.js` · ✓ a reply suggestion is offered and editable.

**5e — Labels & push** · M
- **Labels (multi per message) + category tabs** — label table + many-to-many; map to IMAP
  folders; simple Primary/Social/Promotions heuristics. · L · `core/database.py`,
  `services/mail_cache.py`, `routes/mail.py`, `static/js/mail.js` · ✓ multiple labels per
  message; tab filters.
- **IMAP IDLE push** — persistent IDLE connection per account → instant new-mail. · M ·
  `services/mail.py` · ✓ new mail appears without the 30s poll.

### Stage 6 — files: Drive parity

**6a — Recover & history** · M · deps: 1d, 1e
- **Trash + restore** (1d), **version history** (1e), **starred** (FileTag favorite),
  **storage-quota view** (sum sizes + disk). · files: `services/files_store.py`,
  `routes/files.py`, `static/js/files.js`, `core/database.py` · ✓ delete→restore; restore an old
  version; star filter; a quota bar shows usage.

**6b — Browse & dedup** · M
- **Grid thumbnail view** — image grid alongside the list. · M
- **Office-doc preview** — docx/xlsx/pptx → HTML/image preview (LibreOffice headless or
  python-docx/openpyxl). · M
- **Exact-hash duplicate detection** — SHA-256 dedup (perceptual/visual dedup = out-of-scope).
  · M · files (6b): `static/js/files.js`, `services/files_store.py`, `routes/files.py` · ✓ grid
  shows thumbs; an office file previews; identical files flagged as duplicates.

**6c — Share** · M · deps: 1a
- **File/folder share links + permission levels** (1a) + **file comments**. · files:
  `routes/files.py`, `routes/shared.py`, `core/database.py`, `static/js/files.js` · ✓ a share
  link serves a file read-only/download; a comment persists on a file.

### Stage 7 — gallery: Photos parity (metadata-first)

**7a — Organize & recover** · S · deps: 1d
- **Captions/keywords/tags**, **hidden/locked album**, **trash** (1d), **favorites filter**
  (heart exists; add the filter). · files: `core/database.py`, `routes/photos.py`,
  `static/js/photos.js` · ✓ caption + tags edit in lightbox; hidden album gated; trash restores;
  favorites filter shows only ♥.

**7b — Places & memories** · M
- **Places map view** — cluster photos by existing GPS EXIF on a Leaflet/OSM map (no API key).
  *Why: GPS is already extracted; only the map view is missing.* · M
- **Date-based Memories/collages** — "a year ago" highlights + PIL collage (no ML). · M ·
  files (7b): `static/js/photos.js`, `routes/photos.py`, `services/photos_store.py` · ✓ map
  shows located photos; a memory collage generates.

**7c — Share & motion** · M · deps: 1a
- **Shared albums** (1a read-only link), **Live-Photo/video assets** (accept mov/mp4, ffmpeg
  thumbnail, playback), **phone-camera backup** (watch a synced folder, e.g. iCloud Drive on the
  Mac mini). · files: `routes/photos.py`, `services/photos_store.py`, `services/photo_sync.py`,
  `static/js/photos.js`, `core/database.py` · ✓ album share link works; a video plays in the
  lightbox; dropping a file in the watch folder imports it.

### Stage 8 — calendar & contacts: scheduling & sync

**8a — Views & scheduling** · M
- **Agenda/schedule + year view** (agenda endpoint exists; add UI), **default event durations**
  (setting + NL already parses "for 2h"), **subscribe to ICS URL** (auto-refresh job),
  **secondary tz/world clock + working hours/OOO**. · files: `static/js/calendar.js`,
  `static/index.html`, `routes/calendar.py`, `routes/calendars.py`, `core/database.py`,
  `services/jobs.py` · ✓ year + agenda render; an external ICS URL refreshes on schedule; a
  second time zone shows; working hours shade the grid.

**8b — Invites & booking** · L · deps: 1a, mail
- **Invites + RSVP** (send via mail, track yes/no/maybe locally), **video-meeting links**
  (paste or self-hosted Jitsi room), **appointment/booking pages** (public free-slot page via
  1a where a guest books). · files: `routes/calendar.py`, `routes/mail.py`, `routes/shared.py`,
  `core/database.py`, `static/js/calendar.js` · ✓ an invite emails guests + records RSVPs; a
  booking link creates an event in a free slot.

**8c — Contacts depth** · L
- **Multiple labeled emails/phones/addresses + social/custom fields** (`ContactField` table),
  **contact photo/avatar**, **groups w/ smart membership**, **duplicate detect + merge / linked**,
  **Me card**, **address map**. · files: `core/database.py`, `routes/contacts.py`,
  `services/vcard.py`, `static/js/contacts.js` · ✓ a contact holds work+home email with labels
  and round-trips to vCard; an avatar shows; a smart group auto-populates; dup-merge combines two;
  the Me card is marked; an address opens a map.

**8d — CardDAV sync** · M
- **Two-way contact sync** — reuse the caldav pattern for CardDAV (iCloud/Google with the
  user's own credentials). · files: `services/caldav_sync.py` (or new `carddav_sync.py`),
  `routes/caldav.py`, `core/database.py`, `routes/contacts.py` · ✓ a remote contact syncs in and
  a local edit pushes out, with sync UIDs.

### Stage 9 — secrets: 1Password parity

**9a — TOTP + Watchtower** · M
- **TOTP/2FA generation** (`pyotp`, time-remaining ring), **Watchtower** (weak via existing
  strength meter, **reused** by comparing hashes across entries, **expiring**, **breached** via
  HIBP k-anonymity range API — no full password leaves the box). · files: `services/pwtools.py`,
  `routes/vault.py`, `static/js/vault.js` · ✓ a TOTP code ticks; Watchtower lists reused/weak/
  breached items.

**9b — Attachments + share** · M · deps: 1a
- **Encrypted file attachments** (AES-GCM blobs linked to an entry) + **per-item share link**
  (1a, careful reveal scoping). · files: `core/database.py`, `routes/vault.py`,
  `services/crypto.py`, `static/js/vault.js` · ✓ attach + download a file encrypted; a one-off
  share link reveals a single item read-only and revokes.

**9c — Vaults & unlock** · L
- **Multiple vaults** (vault_id + per-vault master key), **Travel Mode** (subset flag filters
  list/reveal), **biometric unlock** (WebAuthn platform authenticator). · files: `core/database.py`,
  `routes/vault.py`, `services/crypto.py`, `static/js/vault.js` · ✓ switch vaults; Travel Mode
  hides flagged items; biometric unlocks on a supported device.

**9d — Passkeys & autofill** · L
- **Passkey storage**, **hardware-key (FIDO2/YubiKey) 2FA for unlock**, **local browser-
  extension autofill** (a thin extension talking to the localhost vault API). · files:
  `routes/vault.py`, `static/js/vault.js`, new `extension/` · ✓ store/use a passkey entry; a
  hardware key gates unlock; the extension fills a login on a test page. (Extension packaging
  noted as a separate deliverable.)

### Stage 10 — aide: agent & assistant depth

**10a — Code intelligence** · M · deps: 1c
- **Semantic codebase index** (1c over code symbols), **tool-event hooks** (run a rule on
  `write_file`/`edit_file`/etc.), **git worktree isolation** (per-run worktree for parallel
  agents). · files: `services/agent_tools.py`, `services/agent_runtime.py`, `core/database.py` ·
  ✓ semantic search finds a function by description; a hook fires on edit; an agent run uses an
  isolated worktree.

**10b — Background agents** · M
- **Durable detached runs** — a job-queue so a run survives browser close and resumes; status
  in the runs drawer. · files: `services/agent_runtime.py`, `services/agent_state.py`,
  `services/jobs.py`, `routes/agent.py` · ✓ start a run, close the tab, reopen → it continued and
  shows progress.

**10c — Plugins via skills** · M
- **Git-backed shareable skills** — install/update a skill bundle from a git URL; export your
  own (the self-hosted "marketplace-lite"). · files: `services/skills_store.py`,
  `services/skills_github.py`, `routes/skills.py`, `static/js/skills.js` · ✓ install a skill from
  a URL → it's discoverable by the agent; update pulls changes.

**10d — Custom assistants** · M · deps: 1a
- **Personas + knowledge files + share** — attach knowledge files to a persona; bundle/share
  (1a); **more MCP connectors** with one-click setup presets. · files: `routes/personas.py`,
  `routes/connections.py`, `routes/mcp.py`, `routes/shared.py`, `core/database.py` · ✓ a persona
  answers from its attached files; a shared bundle imports; an MCP preset connects in one click.

**10e — Vision + browser** · M
- **Video-input understanding** (frame extraction for capable models), **browser-automation
  tool** (a Playwright/CDP agent tool distinct from pixel computer-use). · files:
  `routes/chat.py`, `services/agent_tools.py`, `services/imagegen.py` · ✓ a video attaches and is
  summarized; the agent navigates a page via the browser tool. *(Video generation stays
  out-of-scope — see below.)*

**10f — Realtime voice (gated)** · L
- **Full-duplex voice** — barge-in streaming voice, **gated** on wiring a realtime-capable
  provider (WebRTC/Realtime API) into the endpoint model; ships only when a real backend exists
  (no fake shell). · files: `routes/voice.py`, `static/js/voice.js`, `services/llm.py` · ✓ with a
  realtime endpoint configured, the user can interrupt mid-response; otherwise the feature stays
  hidden behind the gate.

### Stage 11 — platform: macOS, mobile, unification, tests

**11a — macOS native** · L
- **PhotoKit / EventKit / Keychain / iCloud Drive full integration** — replace the CLI seams
  (`osxphotos`, `icalBuddy`, `security`) with PyObjC bindings where it pays off; iCloud Drive
  watch-folder for photo/file ingestion; back the vault onto Keychain. *(macOS-only, guarded.)*
  · files: `services/macos_bridge.py`, `services/photo_sync.py`, `services/caldav_sync.py`,
  `routes/photos.py`, `routes/calendar.py`, `routes/vault.py` · ✓ on the Mac mini, Photos +
  Calendar + Reminders import structured data; Keychain stores a secret; non-darwin still
  fails loud.

**11b — Mobile** · M · deps: 1b
- **PWA offline polish** (1b across docs/journal/tasks/mail) + an **optional Capacitor wrapper**
  for an installable iOS/Android shell. · files: `static/sw.js`, `manifest.json`, `static/style.css`,
  new `mobile/` · ✓ installs to home screen; core apps work offline; responsive at phone widths.

**11c — Unification** · S
- **alles↔aide cross-app audit + polish** — verify every subdomain scope, SSO handoff, and
  cross-jump; fix any rough edges (the audit found none in code, but this hardens it as the suite
  grows). · files: `static/js/subdomain.js`, `static/js/app.js`, `core/auth.py`, `routes/auth.py`
  · ✓ a Playwright sweep cross-navigates all subdomains with one login, 0 console errors.

**11d — Test hardening** · M
- **Per-module ≥8-test backlog + full regression** — bring every module touched above to the
  repo's ≥8-cases bar; a final `pw_sweep`/`pw_final` across all subdomains. · files: `tests/*`,
  `docs/plans/regression.md` · ✓ `python -m unittest discover -s tests` green; broad + deep
  Playwright sweeps pass with 0 real console errors.

---

## Out-of-scope / adapted

Every item below is a checklist entry deliberately **not** built as-is; each has a reason and,
where possible, the local adaptation that *is* in the roadmap.

| Item | Decision | Reason / adaptation |
|---|---|---|
| Real-time multiplayer co-editing (Notion) | **Out** | Single-user by design; CRDT/WebSocket stack unjustified. *Adapted:* read-only publish + share links (1a, 3c). |
| Native iOS/Android apps (aide, money, docs) | **Adapted** | True native is a separate product. *Adapted:* PWA offline (11b) + optional Capacitor wrapper. |
| Bank linking via Plaid/Yodlee (money, subs) | **Out** | Paid third-party, not self-hostable. *Adapted:* CSV/OFX import + local recurring-detection (1f, 4e). |
| Cancellation concierge + bill negotiation (Rocket Money) | **Out** | Human/vendor services. *Adapted:* store cancel links/steps + a "cancel by" reminder (4e). |
| Credit-score monitoring (subs) | **Out** | Requires a credit-bureau API; impossible locally. |
| Spam filtering (mail) | **Out** | IMAP providers filter server-side. *Adapted:* optional SpamAssassin hook noted, not built. |
| Hide My Email aliases · Mail Drop (mail) | **Out** | Apple-cloud features. *Adapted:* large attachments via file share links (6c). |
| IDE plugins — VS Code / JetBrains (aide) | **Out** | Native plugin ecosystems out of a self-hosted app's scope. *Adapted:* aide already exposes an OpenAI-compatible API, so external editor extensions (Continue-style) can point at it. |
| Full community plugin marketplace w/ sandboxed JS (docs) | **Out** | Arbitrary-JS execution is a security liability for one user. *Adapted:* per-vault CSS snippets (2e) + git-backed skills (10c). |
| Cross-device / desktop sync client (files) | **Out** | A standalone sync daemon is its own app. *Adapted:* watch-folder ingestion (7c/11a) + PWA offline (11b). |
| **Heavy local ML** — visual/content (CLIP) search, OCR-in-images, face recognition/People, perceptual-hash dedup, object-removal/inpainting (gallery, files) | **Out (per decision)** | Large onnx/torch deps vs the minimal, no-build philosophy. *Adapted:* filename/EXIF/date search, **exact-hash** dedup (6b), date-based Memories (7b). Revisit as opt-in extras later. |
| Voice cloning (odysseus-style) (aide) | **Out (per decision)** | Needs a heavy local voice model. *Adapted:* preset-voice TTS stays; revisit with a local model later. |
| Video **generation** (aide) | **Out** | No self-hostable model in-stack. *Note:* video **input/understanding** **is** in 10e. |
| Investment **live** auto-prices (money) | **Adapted** | "Live" needs a market-data API. *Adapted:* manual holdings + cost basis with an **optional** free price fetch (4c). |
| File requests (files) | **Out** | Inherently multi-user (collect uploads from others); no fit for single-user. |

---

## Coverage cross-check

Every Step-2 checklist item and Step-2B fix is accounted for:

- **docs→Obsidian (10):** Canvas→2d · split panes/tabs→2e · hover preview→2a · inline queries→2b ·
  Bases+formulas→2c · nested tags→**done** (tree UI 2a) · folding→2a · bookmarks→2a (outline **done**) ·
  plugins/CSS→2e (full plugins **out**) · mobile offline→2e/11b.
- **docs→Notion (14):** relational+rollups→2c · multi-view→2c · formula/grouping/saved→2b/2c ·
  templates/buttons→3c · comments→3e · multiplayer→**out** (sharing→3c) · publish→3c · synced blocks→3b ·
  block types→3a (callout/color/divider **done**) · covers/icons→3a · @-mentions→3a (pages **done**) ·
  live embeds→3b · in-DB automations + ask-AI→3d · clipper/forms/charts→3d (clipper=bookmarklet).
- **aide→Code tools (11):** codebase index→10a · IDE integ→**out/adapted** · git→**done** · subagents→**done** ·
  background agents→10b · plan mode→**done** · checkpoints→**done** · hooks→10a · plugins/marketplace→10c ·
  per-tool perms+isolation→**done** (worktree→10a) · multi-session dashboard→**done**.
- **aide→Assistants (6):** realtime voice→10f (gated) · video gen→**out** / video input→10e ·
  computer use→**done** (browser tool→10e) · custom assistants+store→10d · connector ecosystem→10d (MCP) ·
  native mobile→**out/adapted** (11b).
- **mail (14):** schedule/undo→5b · snooze→5b · server rules→5d · labels+tabs→5e · smart mailboxes→5a ·
  HTML compose+signatures→5c · smart compose/reply→5d · vacation→5d · unsubscribe→5a · archive/mute→5a ·
  spam→**out** · search operators→5a · IMAP IDLE→5e · remind/MailDrop/HideMyEmail→**out/adapted** (snooze 5b).
- **files (9):** trash→6a · versioning→6a · sharing→6c · desktop sync→**out/adapted** · OCR→**out** ·
  office preview→6b · shared-with/starred/recent/activity→6a/6b (recent **done**, shared **out**) ·
  grid+dedup→6b (exact-hash; perceptual **out**) · quota/comments/requests→6a/6c (requests **out**).
- **calendar (8):** invites/RSVP→8b · video links→8b · booking→8b · ICS-URL subscribe→8a · search→**done** ·
  secondary tz/working hours→8a · year/schedule view→8a · suggested times/default durations→8a.
- **gallery (11):** visual search→**out** · face rec→**out** · places map→7b · memories→7b ·
  editing+object removal→editing **done**/removal **out** · dedup→**out** (perceptual) · trash→7a ·
  shared albums→7c · live/video→7c · captions/keywords/hidden→7a · phone backup→7c.
- **contacts (6):** multi-field→8c · photo→8c · CardDAV→8d · dup-merge→8c · groups→8c · map/share/Me→8c.
- **secrets (8):** TOTP→9a · passkeys→9d · autofill→9d · Watchtower→9a · attachments→9b ·
  typed schemas→**done (Step 2B #1)** · sharing→9b · multi-vault/Travel/biometric/YubiKey→9c/9d.
- **subs (7):** auto-detect→4e · concierge→**out** · negotiation→**out** · bank+price-hike→price-hike **done**/bank **out-adapted** (1f/4e) · alerts+non-sub bills→4e · unused→4e · credit score→**out**.
- **money general (7):** bank/investment sync→**out-adapted** (1f) · splits→4a · tags+receipts→4a ·
  cleared/reconcile→4a · bill reminders/calendar→4e · goals/reports/export→4d · mobile/multi-currency→11b/4d.
- **money YNAB (4):** envelope→4b · rollover→4b · funding targets→4b · Age of Money→4b.
- **money Simplifi (4):** spending-plan forecast→4c · watchlists→4c · investment tracking→4c (live prices adapted) · net-worth graph/dashboard/alerts→4c.
- **Step 2B (2):** typed secrets→**done** · journal heatmap→**done**.
- **Don't-drop (plan docs):** macOS PhotoKit/EventKit/iCloud→11a · odysseus voice clone→**out (per decision)** ·
  alles↔aide unification→11c · per-module test backlog→11d (+ every microversion's TDD gate).

**Unplaced: none.**
