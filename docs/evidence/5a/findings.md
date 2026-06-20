# 5a audit — mail: triage

Mapped the mail app (16-point sweep). Live `:8839`: `/saved-searches`, `/mute/x`, `/archive/x`,
`/adv-search/x` all **404**.

## Baseline (testable without IMAP)
- `CachedMessage(account_id, folder, uid, sender, subject, date, date_ts, seen, flagged)` — the
  offline cache. `mail_cache` does save/get/get_unified/get_filtered(unread|flagged)/search/set_flag/
  set_seen — all cache-only.
- pure helpers: `mail.normalize_subject`, `group_threads`, `is_vip`.
- `fetch_message` extracts From/To/Subject/Date/Message-ID/References but **not List-Unsubscribe**.
- No `SavedSearch`/`Mute`/`Label` models; no advanced-operator search; no archive/mute.

## Gaps (net-new, all cache-first)
1. List-Unsubscribe parse + a per-row unsubscribe button (needs a cache column).
2. Saved/smart mailboxes beyond the fixed unread/flagged/VIP (a `SavedSearch` model).
3. Advanced search operators (`from:`, `subject:`, `before:`, `after:`, `has:attachment`, `to:`).
4. Archive (drop from inbox cache) + mute thread (`muted` column, excluded from lists).

Plan: docs/plans/5a.md (5a-1 backend, 5a-2 frontend with seeded cache).
