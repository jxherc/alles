# Phase 10 — journal (`journal.js` + `routes/journal.py`)

## Audit (2026-06-18)

Seeded 4 entries (incl. one a year ago) and drove the UI (journal.localhost, 0 console errors).

Verified working (DO NOT rebuild): one entry/day with autosave; mood (emoji) + tags; rotating daily
writing prompt; word count; streak counter; on-this-day (past years); full-text search; export to one
markdown doc; AI reflect (warm model reflection); recent list; prev/next/today nav. (A
`/journal/calendar` heatmap endpoint exists but has NO UI consuming it.)

Genuine gaps vs the spec ("lock + journaling features") and the global rules:

1. **No lock.** The spec's headline journal feature. A diary is private; there's no passcode gate today —
   anyone at the machine can read it. (Secrets has a lock pattern — verifier + unlock token — to reuse.)
2. **Heatmap endpoint with no UI.** `/journal/calendar` returns per-day word counts but nothing renders
   it — a built feature the user can't see.
3. **Mood captured but never analyzed.** Every entry can have a mood; there's no way to see your mood
   distribution/trend over time.
4. **No day in the URL.** Opening a past day (or deep-linking one) doesn't update the URL, so refresh
   drops you back to today — violates the global routing rule.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **journal-1 Passcode lock.** `journal_passcode` verifier in settings (PBKDF2 via the existing
  crypto helpers — no plaintext stored); in-memory unlock tokens (`X-Journal-Token`, sliding TTL);
  endpoints GET `/journal/lock/status`, POST `/journal/lock/set` (set/change, old passcode required to
  change), POST `/journal/unlock`, POST `/journal/lock`, POST `/journal/lock/disable`; when a passcode is
  set the journal data endpoints require a valid token (else 403); when none is set everything is open
  (back-compat). Lock-screen UI over the journal. *Why: the spec's required feature; a diary needs a
  lock.*
- **journal-2 Mood trends.** GET `/journal/moods?days=N` → mood distribution (counts per mood, desc),
  most-common mood, total entries, total with a mood, over the window; a mood-bar in the sidebar. *Why:
  mood is captured on every entry and currently goes nowhere.*
- **journal-3 Year heatmap UI + day URL routing.** Enrich `/journal/calendar` to return per-day
  `{words, mood, level}` with an intensity `level` (0–4) bucketed server-side from word count, plus a
  `years` list (which years have entries) for year nav; render a GitHub-style contribution heatmap that
  clicks to open a day; reflect the selected day in the URL (`?d=YYYY-MM-DD`) so refresh / deep-link
  restores it. *Why: surfaces a built-but-hidden endpoint and satisfies the global routing rule.*

## Out of scope

Per-entry encryption (that's the vault's job — the journal must stay searchable + AI-reflectable),
biometric/WebAuthn unlock (no hardware in this env), media attachments (the files app owns media),
multi-journal/notebooks.
