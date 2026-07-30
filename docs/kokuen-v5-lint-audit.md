# KOKUEN v5 lint audit

The canonical KOKUEN linter is run against `static/kokuen.css`, the final v5 overlay that owns the
shipped shell and workbench presentation.

Current acceptance:

- hard errors: 0
- reviewed warnings: 195
- unexplained warnings: 0
- `small-type`: 123 reviewed 12-13px secondary metadata or compact workbench labels. The hard 12px
  floor is preserved; interactive silhouettes remain at least 44px and primary text keeps the essential
  hierarchy.
- `nested-boundary`: 72 reviewed control bezels or independent scroll/select/dialog/rail subregions.
  The descendant and ancestor edges have distinct jobs and the rendered pass found no same-level double
  bezel.

The acceptance is fail-closed. `scripts/check_kokuen_v5_lint.py` fingerprints every canonical warning,
assigns each one a declared semantic job, and fails if any warning appears, disappears, changes line or
message, or lacks a known resolution. Run its `--report` mode for the exhaustive line-by-line table.

```sh
python3 scripts/check_kokuen_v5_lint.py
python3 scripts/check_kokuen_v5_lint.py --report
```

This is a source-level advisory audit. It supplements, and does not replace, real rendered checks for
one perceived boundary, focus clipping, target size, text legibility, zoom, responsive layout, and
reduced motion.

The companion regression also scans shipped CSS, HTML, and dynamic JavaScript templates for `rem` or
pixel text below 12px, closing the legacy source and inline-style gap outside the overlay.
