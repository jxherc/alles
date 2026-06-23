# stage 2k - recall/money observability + mail-body indexer - audit findings (2026-06-23)

## audit result: already delivered in prior phases - NO rebuild (reuse-over-rebuild rule)

the plan's three 2k deliverables were each shipped incrementally during the personal-RAG phase
(recall) and the 4c money phase (dashboard). audited each by running it:

### (a) recall settings UI - DONE
`static/js/settings.js` `loadRecallPane()` (line ~1462): master + per-source `pidx_*` toggles bound to
`/api/recall` settings, live stats from `/api/recall/stats`, reindex + clear buttons. backed by
`routes/recall.py` (stats / reindex per-source / clear) + `personal_index._source_enabled`. covered by
`tests/test_api_recall.py` + `tests/pw_recall_settings.py`.

### (b) mail-body indexer - DONE (was mislabeled a stub)
`personal_index._index_mail_batch` is fully implemented: it walks `body_indexed=False` cached messages,
pulls each body via `_fetch_mail_body` (monkeypatchable seam), indexes subject+sender+body into recall,
and flips `body_indexed` only once a body is actually retrieved (failed fetches stay retryable).
`stats()` reports `mail_pending`. covered by `test_personal_index.test_mail_subject_indexed_and_body_batch`
+ `test_mail_failed_fetch_retryable`. the ONLY defect was a stale call-site comment ("stub returns 0
until A6") - corrected. live-verified: a word present ONLY in a mail body becomes recall-findable.

### (c) money workspace dashboard - DONE
`static/js/money.js` already renders forecast, net-worth history (`_nwhist` via /networth-history),
holdings, an alerts strip (/alerts), and reorderable show/hide cards persisted in localStorage (4c).
backend endpoints all present (/forecast, /networth-history, /networth-base, /summary, /holdings,
/alerts).

## conclusion
nothing genuinely missing in the backend. verified all surfaces green (22 targeted tests + full suite
3015 OK). remaining nice-to-haves (a money dashboard pane that calls the 2a NL money_query directly,
richer watchlist) are frontend reactive surfaces and belong with Phase 5 (the reactive client layer),
per the roadmap's own sequencing rationale.
