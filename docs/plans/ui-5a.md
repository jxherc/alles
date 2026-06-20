# ui-5a — real free-disk display (Docker-aware)

`/api/files/quota` already returns `free` from `shutil.disk_usage(files_dir())` (so it reports the volume the
data dir actually lives on — the Docker mount in a container), but the UI only showed used/total. Surfaced
**free space as the headline** in `_renderQuota` (`static/js/files.js`): the label now reads
`<b class="files-quota-free">N GB free</b> · M used of T` with free coloured green (`.files-quota-free`).

Tests: `tests/test_files_quota.py` (3: quota has used/total/free, free is a real positive figure ≤ total,
used ≤ total) + `docs/evidence/ui-5a/verify.py` (quota bar present, free shown + sized + green, still shows
used/total, bar renders, 0 console errors) + `quota.png`.
