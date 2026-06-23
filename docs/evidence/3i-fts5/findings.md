# stage 3i - FTS5 first-class store - audit findings (2026-06-23)

## current state
- recall search runs over `IndexChunk` via `services/textindex.py` using embeddings (fastembed) with a
  Jaccard keyword fallback. it's vector/overlap scoring - there's NO real full-text engine: no phrase
  match ("exact words in order"), no negation (term NOT other), no prefix (runn*), no field weighting
  (a title hit ranking above a body hit).
- SQLite is built WITH FTS5 here (verified: CREATE VIRTUAL TABLE ... USING fts5 works), but nothing
  uses it.

## the gap
- a first-class FTS5 virtual table with phrase / negation / prefix queries + field-ranked results
  (title weighted above body via bm25), filterable + rankable across every kind.
- a {kind, index_fn, weight} registry so any model can register its text, and an index hook the
  Phase-0 mutation spine can call to keep it fresh.

## fix - new `services/fts.py`
- `ensure(db)` -> CREATE VIRTUAL TABLE IF NOT EXISTS fts_docs USING fts5(kind, ref UNINDEXED, title,
  body, tokenize='porter').
- `index(db, kind, ref, body, title="")` -> upsert (delete existing kind+ref, insert).
- `search(db, query, kind=None, limit=10)` -> FTS5 MATCH (phrase/negation/prefix pass through),
  ordered by bm25 with title weighted above body; optional kind filter.
- `remove(db, kind, ref)`, `clear(db)`.
- `on_mutation(db, kind, ref, text)` -> the spine hook (reindex a row when it changes).
- route GET /api/search/fts?q=&kind=.

tested: index+find, phrase-only match, negation exclude, prefix match, title outranks body, kind filter,
reindex replaces, remove drops, no-match empty, porter stemming (run matches running).
