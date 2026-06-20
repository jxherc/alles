# 1e — File versioning primitive — audit (2026-06-19)

Backend-focused. Current state: `DocRevision` versions **vault markdown only**
(`routes/vault_md.py:_snapshot`). The **files app** has no version history — `save_upload`
(`services/files_store.py:134`) does `dst.write_bytes(data)`, overwriting in place with no snapshot.
So overwriting a generic file loses the prior content irrecoverably.

## Gap (1e)
A generic blob-revision store for arbitrary files: snapshot-on-overwrite, SHA dedup, capped count,
restore. Reuses the DocRevision *pattern* without touching it.

## Plan
- 1e-1: `FileVersion` model (path/sha/size/stored/created_at) + `services/fileversions.py`
  (snapshot/list/restore, blobs in `<data>/.versions`, 25MB cap, keep last 20, sha dedup) + wire
  snapshot before overwrite in upload + `GET /api/files/versions` + `POST /api/files/versions/restore`.
  Unit tests >=10.
- 1e-2: files row "versions" popover + restore. Playwright >=8.
