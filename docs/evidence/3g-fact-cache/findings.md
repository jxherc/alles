# stage 3g - deep_research fact-cache + dedup - audit findings (2026-06-23)

## current state
- `DeepResearcher` accumulates `findings` (dicts {url, title, summary, ...}) within a single run, and
  `urls_fetched` dedups WITHIN a run. `prior_findings`/`prior_urls` let a follow-up round reuse the same
  run's state.
- but there is NO cross-session persistence: every new research run re-fetches + re-extracts the same
  URLs the user already researched last week. nothing caches findings, nothing flags when two sources
  contradict each other, and there's no cache-first path.

## the gap
- persist findings across sessions, keyed by URL, deduped.
- a cache-first lookup so a repeat/overlapping question can reuse stored findings.
- flag contradictions: two stored findings about the same topic where one negates the other.

## fix
- `ResearchFinding` model (new table -> create_all): url, question, title, summary, ts.
- `services/research/fact_cache.py`:
  - `dedupe(findings)` -> unique by normalized URL (strip trailing slash + #fragment).
  - `store(db, findings, question)` -> insert findings whose URL isn't already cached; returns count.
  - `cached(db, question)` -> prior findings whose question overlaps (cache-first source).
  - `contradictions(findings)` -> pairs sharing >=3 content tokens where exactly one carries a negation.
- wire `store` into the research handler's done path (best-effort) + a route GET /api/research/cache.

tested: url-normalized dedupe, store insert + skip-existing + in-batch dedupe + count, cached overlap
match + empty, contradictions flags opposite-polarity same-topic pairs + ignores same-polarity/unrelated.
