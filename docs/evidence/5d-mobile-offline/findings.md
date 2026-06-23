# stage 5d - mobile PWA + offline sync - audit findings (2026-06-23)

## current state - mostly already delivered
- responsive layout: `static/style.css` already has multiple `@media (max-width: 720px)` blocks +
  home-grid collapse breakpoints (1080/860/620/410) + a 480px block. mobile reflow substantially exists.
- offline editing: `static/js/sync.js` (offline write-queue client) + the `sw.js` IndexedDB outbox
  already stash mutating /api writes offline and flush on reconnect, with a queued-count badge.

## the genuinely-additive, testable gap
the offline outbox has no pure, tested DECISION logic: which requests are queueable, and how to dedup a
queue so a flush doesn't replay 5 stale edits when only the last matters. that logic was implicit in the
service worker. extracting it makes it correct + testable.

## fix - new `static/js/outbox.js` (vanilla ESM, node-testable)
- `isQueueable(method, url)` -> true only for mutating writes (POST/PUT/PATCH/DELETE) to `/api` that
  aren't streaming/agent endpoints.
- `dedupe(queue)` -> collapse redundant ops on the same resource url: a later PUT/PATCH supersedes
  earlier writes to that url; a DELETE drops prior writes to that url (keeps the DELETE); order otherwise
  preserved.
- `summarize(queue)` -> { count } for the badge.
DEFERRED (already present, not rebuilt): the @media CSS, the SW IndexedDB store, bottom-sheet nav polish.

tested: isQueueable for verbs/paths/streaming exclusions, dedupe last-write-wins, delete-supersedes,
unrelated-urls-kept, order preserved, summarize count.
