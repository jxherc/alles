# 1c — Local text index — audit (2026-06-19)

Server: `ALLES_DATA=…/alles1c_data PORT=8813`. Evidence: `curl-audit.txt`. Backend-only microversion
(no UI surface; UI health covered by the post-MV regression sweep).

## Current state (confirmed)
- `services/rag.py` is a **vault-only, in-memory, lazily-built** index: `_collect()` reads vault `.md`,
  `_chunk()` (700/120), `build_index()` embeds via `memory_store._embed` (fastembed) into a module
  global `_index`; `retrieve()` cosine-ranks with a `_jaccard` keyword fallback. `/api/rag/{status,
  reindex,ask}` drive it. It is **not persistent** (lost on restart), **not multi-kind** (docs only),
  and **not reusable** by code search (10a) or anything but the vault RAG.
- `memory_store` exposes reusable `_embed(texts)->list|None`, `_cosine`, `_jaccard`, `_tokenize`.
- `/api/index/*` does not exist (404).

## Gap (1c)
A **reusable, persistent, multi-kind** index so docs *and* code (and later more) share one embedding
store — powering workspace "ask anything" (3d) and codebase semantic search (10a). Without rebuilding
the working `rag.py`.

## Plan
- **1c-1** `services/textindex.py` + `IndexChunk` model (kind/ref/chunk_no/text/vec JSON, SQLite-
  persisted): `index(db,kind,ref,text)` (chunk+embed+upsert), `search(db,query,kind=,k=)` (cosine with
  jaccard fallback), `remove(db,kind,ref)`, `reindex_kind(db,kind,items)`, `stats(db)`. Reuses
  `memory_store._embed/_cosine/_jaccard`. Unit tests (≥10) with a deterministic fake embedder + a
  forced-keyword-fallback path.
- **1c-2** integration: reindex-on-save/delete/rename in `routes/vault_md.py` (best-effort, never
  breaks a save) + a `routes/textindex.py` router (`GET /api/index/search`, `POST /api/index/reindex`).
  Unit tests (≥8): save→indexed→search finds it; edit re-indexes (old gone, new found); delete removes;
  rename moves; API search shape + kind filter; reindex rebuilds from the vault.
