# personal rag - ask aide over your own data (design)

## context

alles already has the pieces for retrieval-augmented answers, just aimed narrowly:

- `services/textindex.py` - a persistent, multi-kind text index over the `IndexChunk` table
  (`kind, ref, chunk_no, text, vec`). it chunks (700 chars / 120 overlap), embeds via
  `memory_store._embed` (fastembed on cpu, onnx), falls back to jaccard keyword scoring when
  fastembed is missing, and `search(db, query, kind=None, k)` already ranks **across all kinds at
  once** with a cosine relevance floor of 0.6. today only `doc` (vault docs, feature 3d) and
  `code` (10a) are indexed.
- `services/rag.py` - a separate vault-only in-memory rag with an `answer()` that retrieves then
  asks an llm to answer with cited `[1][2]` sources.
- the **agent** (`services/agent_runtime.py` + `services/agent_tools.py`) is already a tool-using
  loop that routes a question to the right tool and blends results. it has cross-app tools
  (calendar/task/note/contact/mail) and shell/python, plus a prompt-injection guard.
- the **jobs** engine (`services/jobs.py`) ticks background work every ~30s and lets features
  register their own jobs / react to events.

so "personal rag" is mostly: **feed the rest of the apps' text into `textindex`, give the agent a
`recall` tool over it, and let the agent blend recall with live db queries for analytics.** we are
extending existing infrastructure, not building a new engine.

## goals

- aide can answer **recall** questions grounded in your own text: "what did sam email about the
  trip", "what was i journaling about in march", "find that note about the apartment" - retrieving
  the right text, quoting it, and linking back to the source record.
- aide can answer **analytical** questions ("how much did i spend on coffee", "how many events next
  week") by querying the structured db live - handled by agent tools, not the index.
- the two **blend** in one normal aide chat turn: the agent picks recall vs a structured tool (or
  both) per question and synthesizes one cited answer.
- the index stays **fresh** as you add/edit/delete records, without re-embedding everything.
- it is **private and controllable**: the vault is never indexed, the journal respects its lock,
  embedding is local, and you can toggle/reindex/clear it.

## non-goals

- no new retrieval engine - reuse `textindex`. no new vector db.
- no indexing of structured numerics for analytics - the agent queries the db live for those.
- no multi-user / sharing. single user, local.
- not trying to answer from data we don't have cheaply (e.g. full mail history is fetched
  incrementally, not all-at-once - see freshness).

## architecture overview

```
  apps (notes, journal, mail, contacts, read, books, docs)
        │  create / update / delete
        ▼
  services/personal_index.py  ── source adapters: record -> (kind, ref, text, label, link)
        │  index() / remove()  (incremental, per-record)
        ▼
  textindex.py  ──►  IndexChunk (sqlite)   ◄── backfill + reconcile job (jobs.py)
        ▲
        │  search(query, kinds, k)  -> hits {kind, ref, chunk, score, label, link}
        │
  agent tool: recall(query, k, kinds?)        agent tools: money_query / etc. (analytics, live db)
        └──────────────┬───────────────────────────────┘
                        ▼
                 agent_runtime (routes + blends + cites)
                        ▼
                 normal aide chat answer (with source links)

  settings surface: enable, per-source toggles, reindex now, stats, clear
```

three layers, built in order:

- **phase a - the recall index** (`services/personal_index.py`): source adapters, on-write hooks,
  backfill, the reconcile job, the mail-body indexer, and the privacy gates. self-contained and
  testable with no agent/ui.
- **phase b - the blend** (agent tools): the `recall` tool with provenance, plus read-only
  structured-query tools where missing (notably money), and the citation/answer behaviour.
- **phase c - control surface**: settings to enable/disable, per-source toggles, reindex, stats,
  clear.

## data model

reuse `IndexChunk` as-is. add new `kind` values and a stable `ref` scheme per source:

| source | kind | ref | text indexed | label | deep-link |
|---|---|---|---|---|---|
| vault docs (existing) | `doc` | vault rel path | doc body | path | docs app |
| notes | `note` | note id | title + content + checklist item text | title | notes app |
| journal | `journal` | entry date (iso) | entry content (+ mood/tags) | "journal YYYY-MM-DD" | journal app |
| mail | `mail` | `<account_id>:<uid>` | subject + sender + body | subject | mail message |
| contacts | `contact` | contact id | name + company + title + notes + field values | name | contacts app |
| read-later | `read` | read_item id | title + extracted text | title | read app |
| books | `book` | book id | title + author + notes | title | books app |

`ref` is opaque to `textindex`; `personal_index` owns the mapping `ref -> {label, link}` so the
recall tool and ui can render a human label and a deep-link without `textindex` knowing app
specifics. the "personal kinds" set (everything except `code`) is a constant in `personal_index`.

## ingestion - source adapters

`personal_index.py` exposes, per source, a pure `text_for(record) -> str` and the `(kind, ref)`
builder, plus three verbs that wrap `textindex`:

- `index_one(db, kind, ref, text)` -> `textindex.index` (drops old chunks for that ref first).
- `remove_one(db, kind, ref)` -> `textindex.remove`.
- `reindex_source(db, kind)` -> iterate that source's records, `textindex.reindex_kind`.

adapters skip empty text and obey the privacy gates (below). chunking/embedding stays in
`textindex` - adapters only produce text.

## freshness (the high-risk part)

three mechanisms, layered so a miss in one is caught by another:

1. **on-write hooks (precise, incremental).** each app's create/update route calls
   `personal_index.index_one(...)`; each delete calls `remove_one(...)`. one record re-embedded,
   never the whole kind. hooks are added at the **store/route layer** for: notes, journal,
   contacts, read-items, books. (docs already index via their own path.) the call is best-effort
   and wrapped so an index failure never breaks the user's save.

2. **backfill (catch existing data).** `reindex_source` per kind, run once on first enable and
   exposed via the reindex endpoint. idempotent (`index` deletes old chunks for the ref first).

3. **reconcile job (catch drift).** a registered `jobs.py` job runs periodically and:
   - drops `IndexChunk` rows whose `ref` no longer exists in the source (orphans from missed
     deletes),
   - re-indexes records changed since last reconcile (using each source's `updated_at` where it
     exists; notes/journal/contacts have one),
   - advances the **mail-body indexer** (next item).
   the reconcile is the safety net for any write path a hook missed.

### mail is special

`CachedMessage` stores only headers (sender, subject, date) - **bodies are fetched on demand**, not
stored. so:

- the `mail` adapter indexes subject + sender immediately from the cache (cheap, already local).
- a **rate-limited background body indexer** (part of the reconcile job) fetches bodies for a small
  batch of not-yet-body-indexed cached messages per tick, indexes subject+sender+body, and marks
  them done via a `body_indexed` flag column on `CachedMessage` (added with the existing in-place column-migration helper in `core/database.py`). it backs
  off on imap errors. this bounds cost and network so we never block on "embed all mail".
- recall over mail therefore improves over time: subjects are searchable at once, bodies as the
  indexer catches up. this tradeoff is documented in the ui.

## privacy & security (non-negotiable)

- **the vault is never indexed.** no `vault_entries` / `vault_attachments` kind exists; no adapter
  reads them. a test asserts no `IndexChunk` row ever has a vault-derived kind/ref.
- **the journal respects its passcode lock.** if a journal passcode is configured, journal entries
  are **not** indexed (and any existing `journal` chunks are dropped) until it's unlocked; the
  control surface reflects this. default (no passcode) indexes normally.
- **embedding is local.** fastembed runs on cpu; nothing leaves the machine to build the index.
- **answering is not local by default.** the agent sends retrieved chunks to whatever model you
  picked. this is the one place personal text leaves the machine, and only the top-k retrieved
  snippets, only when you ask. documented plainly; use a local (ollama) model for fully-offline
  recall.
- **per-source + master toggle.** indexing is opt-in-able and reversible (clear drops all personal
  kinds). a source toggled off is removed from the index, not just hidden.

## agent integration (the blend)

- **`recall` tool** (`agent_tools.py`): `recall(query, k=6, kinds?=[...])` -> `textindex.search`
  over the personal kinds (optionally filtered), returns
  `[{kind, ref, label, link, chunk, score}]`. the tool description tells the agent to use it for
  "find / what did / remember / which" questions over the user's own notes, mail, journal,
  contacts, saved articles, and books, and to **cite each claim** with the returned label/link.
- **provenance + citations.** hits carry `label` + `link`; the agent cites them, and the chat ui
  renders the links (reusing the existing agent "sources" affordance). this is the anti-
  hallucination control: answers point at real records.
- **analytics tools.** the agent already has calendar/task/note/contact/mail tools. add the missing
  read-only structured-query tool(s) - notably **money** (`money_query`: totals by
  category/payee/date-range, recent transactions) - so "how much did i spend on coffee" is a real
  db query, not a guess. this is a small targeted read-only tool (no shell access).
- **routing is the agent's job.** no custom classifier. a blended question ("what did sam say about
  the trip and how much have i spent on it") becomes: `recall` for the first clause, `money_query`
  for the second, one synthesized cited answer.

## control surface (settings)

a "personal data / recall" settings section:

- **master enable** + **per-source toggles** (mail, notes, journal, contacts, read, books).
- **reindex now** (per source or all) -> calls the backfill.
- **stats** - chunks per kind (`textindex.stats`) + last reconcile time + mail-body indexer
  progress.
- **clear index** - drops all personal kinds.
- a short privacy note (vault excluded, journal-lock honoured, answering sends snippets to your
  model).

## error handling / degradation

- fastembed missing -> jaccard keyword fallback (already in `textindex`); recall still works, just
  lexical.
- an embedding/index failure on a single record is swallowed and logged; the user's save still
  succeeds (hooks are best-effort).
- imap errors in the mail-body indexer -> back off, retry next tick; never block.
- index/source drift -> the reconcile job converges it; manual reindex is the escape hatch.
- empty index / no hits -> recall returns nothing and the agent says it found nothing rather than
  inventing.

## testing strategy

- **unit (per adapter):** `text_for` produces expected text incl. edge cases (empty, checklist-only
  note, contact with custom fields); `(kind, ref)` is stable.
- **index round-trip:** index a record -> `search` finds it; update -> reindexed (old chunk gone);
  delete -> removed. against a throwaway db.
- **privacy:** a vault entry is never indexed (no adapter touches it); with a journal passcode set,
  journal entries are absent from the index and existing ones are dropped.
- **freshness:** create/update/delete via the real routes leaves the index consistent; the
  reconcile job drops orphans and re-indexes changed rows; the mail-body indexer indexes a batch
  and marks progress without refetching.
- **agent:** `recall` returns hits with label/link; structured `money_query` returns correct
  numbers; a fake-model agent run blends both and cites.
- **control:** toggle off a source removes its chunks; clear empties the personal kinds; stats
  report per-kind counts.

reuse the existing in-process api harness (TestClient + in-memory db) and the playwright pattern
for the settings surface.

## risks & mitigations

| risk | mitigation |
|---|---|
| **freshness drift** (a write path misses its hook -> stale/wrong recall) | the reconcile job is the backstop: orphan-drop + changed-row reindex on a timer, independent of hooks. |
| **mail volume/cost** (embedding all bodies is heavy + network) | incremental rate-limited body indexer; subjects searchable immediately; bounded batch per tick; back off on imap errors. |
| **privacy leak** (vault or locked journal getting indexed) | no adapter reads the vault; explicit journal-lock gate; tests assert exclusion; clear/disable removes data. |
| **hallucination** (agent answers beyond the evidence) | recall returns real labels/links; tool description forces citation; "found nothing" path. |
| **embedding cost on weak hardware** | jaccard fallback already works with no model; indexing is incremental and opt-out-able per source. |
| **scope creep into analytics-by-index** | analytics stay live-query via tools; the index is text-recall only (explicit non-goal). |

## build phases

- **phase a:** `services/personal_index.py` (adapters + verbs + privacy gates), on-write hooks in
  the note/journal/contact/read/book stores, the backfill, the reconcile + mail-body job, and unit
  + freshness + privacy tests. ships a correct, fresh, private index with no agent/ui.
- **phase b:** the `recall` agent tool (with provenance), the missing analytics tool(s) (money),
  citation behaviour, and agent tests. ships the blended ask experience in normal chat.
- **phase c:** the settings control surface (enable, per-source toggles, reindex, stats, clear) +
  its tests + cache-stamp bump.

each phase is independently testable and leaves the app working.
