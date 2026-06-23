# stage 0d - unified blob / attachment store - audit findings (2026-06-23)

## current blob handling (no dedup anywhere except file-versions)
| kind | store | dedup | encryption |
|---|---|---|---|
| Upload (receipts/chat) | `data/uploads/<uuid><ext>` | none | none |
| GalleryImage | `data/gallery/<uuid><ext>` | none | none |
| Photo | `data/photos/<uuid><ext>` + `.thumbs` | none | none |
| VaultAttachment | `data/vault_attachments/<id>.enc` | none | AES-GCM (user pw) |
| FileVersion | `data/.versions/<uuid>` | **sha256** (services/fileversions.py) | none |

grep confirms `hashlib.sha256` is used ONLY in `services/fileversions.py`. so the same 5 MB
receipt attached three times is stored three times; there is no content-addressed store, no
generic attachment join, and no GC of orphaned blobs.

## consumers read raw paths (why adoption is deferred)
the Upload path is read in TWO places - `routes/uploads.py:serve_upload`/`delete_upload` AND
`routes/chat.py:186` (chat image attachments base64 the file directly) - and
`tests/test_api_uploads.py:test_delete_removes_file_from_disk` monkeypatches `UPLOAD_DIR` and
asserts the file count there. Photo/Gallery/Vault are the same: each has consumers reading its
specific directory. so swapping any of them to a content-addressed store is a multi-file sweep
with real regression surface.

## decision (scope)
build the genuinely-missing FOUNDATION now - `Blob` (content-addressed, sha256, refcount) +
generic `Attachment` join + `services/blobstore.py` (put/read/attach/detach/gc) + a GC job -
fully tested in isolation, proving dedup + refcount + GC end to end. do NOT rewire the existing
upload/photo/vault writes in this stage (they work; their consumers read raw paths). adoption is
incremental and lands with the features that consume it (4c unified vault-attachment indexing +
photo export, file-versioning-for-any-model), exactly per the roadmap's "new writes first, then
a one-time backfill" note. encryption-at-rest per blob is a documented extension point built in
4c (it needs the vault user-password path), not here.

verified pre-state: no Blob/Attachment model, dedup only in file-versions.
