# Phase 2 — mail (`mail.js` + `routes/mail.py` + `services/mail.py` + `services/mail_cache.py`)

## Audit (2026-06-18)

Target: Apple Mail. IMAP/SMTP backend; a SQLite header cache (`CachedMessage`) warms the inbox so
reads are instant/offline. Verified working (DO NOT rebuild): multi-account CRUD, inbox fetch + cache,
folders/mailboxes, threading (`group_threads`), message view, attachments (list/open), search (live +
cached), compose/reply/forward (in_reply_to/references), mark-seen-on-open, AI summarize / make-task /
extract-event. UI loads with 0 console errors (Playwright). IMAP/SMTP I/O is not unit-testable here, but
the cache + pure helpers are — new work is designed cache-first with best-effort IMAP side-effects.

Confirmed gaps vs Apple Mail (no backend today): **drafts persistence** (compose is ephemeral),
**flag/star**, **unified inbox** (all accounts), **smart mailboxes** (unread/flagged), **VIP senders**,
**read/unread toggle** (only mark-seen-on-open exists). No flag/move/delete endpoints at all.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **mail-1 Drafts.** `MailDraft` table + POST/GET/GET{id}/DELETE `/api/mail/drafts`. Compose "save draft",
  drafts list, click-to-resume, auto-delete on send. *Why: Apple Mail has full drafts; here compose is
  lost on close.* Fully testable (DB CRUD).
- **mail-2 Unified inbox + smart mailboxes + flag.** Add `flagged` col to `CachedMessage`;
  `mail_cache.get_unified` / `get_filtered(unread|flagged)` / `set_flag`; GET `/api/mail/unified`,
  GET `/api/mail/smart/{aid}`, POST `/api/mail/flag/{aid}` (cache truth + best-effort IMAP STORE).
  UI: "All Inboxes", unread/flagged filter chips, flag toggle. *Why: core Apple Mail triage; none exist.*
- **mail-3 VIP senders + read/unread toggle.** VIP email list in settings + `is_vip` helper + VIP filter;
  `mail_cache.set_seen` + POST `/api/mail/read/{aid}?seen=` (cache + best-effort IMAP). UI: VIP star,
  VIP filter, mark read/unread. *Why: VIP + unread toggling are Apple Mail staples.*

## Out of scope (IMAP-bound / lower ROI here)

Server-side move/archive/trash/junk (needs a live IMAP to verify; risky to fake) — deferred; the
cache-first flag/unread give most of the triage value. Rules/filters, snooze — revisit later if needed.
