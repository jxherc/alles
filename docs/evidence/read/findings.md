# read-later — audit findings

New read-later archive. Reuses the research extractor (`fetch_webpage_content`) to fetch + store readable
page text so links don't rot and stay searchable offline. Isolated server `:8915`, seeded real articles
(a Paul Graham essay 59 min, Hacker News, example.com).

## What was exercised (works ✓)
- **Save a URL** — paste + save; alles fetches + extracts the text, stores title/site/excerpt/read-time
  (PG essay correctly read as "How to Do Great Work · 59 min") — `01-list`.
- **List** — cards with title, excerpt, site · read-time, star/read/archive/delete actions; filter chips
  (all / unread / starred / archive) — `01-list`.
- **Search** — full-text over title + stored body (`q=work` filters) — `02-search`.
- **Reader view** — clean centered article column, back + open-original, title + meta + paragraphs — `03-reader`.
- **Star + filter** — star an item, switch to the starred filter — `04-starred-filter`.
- **Archive / mark-read / delete** — all wired (mark-read on open; archive toggles; delete confirms).
- **Responsive** — single column at 460px — `05-narrow`.
- **Breadcrumb / tile / subdomain** — `read` tile (book icon), `read.localhost`, breadcrumb `read / alles`.

## Notes (not bugs)
- Wikipedia returned a stubbed 141-char page through this environment's proxy (so its title fell back to
  the site) — the extractor + the "keep the link even if extraction fails" path handled it gracefully
  (unit-tested). Sources that aren't proxy-stubbed (PG, HN, example) extract full text. This is an
  environment/network artifact, not a product bug.

## Console / errors
- `console.log` — **0 real console errors** across save/search/reader/star/archive/narrow.

## Verdict
Works and looks unified (kokuen tokens, custom chips, reader column capped at ~68ch). Reusing the research
extractor kept it small and consistent with how alles already reads pages.
