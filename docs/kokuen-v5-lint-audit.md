# KOKUEN v5 lint audit

The canonical KOKUEN linter is run against `static/kokuen.css`, the final v5 overlay that owns the
shipped shell and workbench presentation.

The stabilization layout changed warning line numbers. Comparing the canonical
warnings with `c696c42` by severity, rule and message found no added or removed
warning semantics. The digest was updated for those offsets. This preserves the
historical lint review; current rendered acceptance remains in the stabilization
ledger and is not established by this inventory.

Historical lint review:

- hard errors: 0
- reviewed warnings: 191
- unexplained warnings: 0
- `small-type`: 120 reviewed 12-13px secondary metadata or compact workbench labels. The hard 12px
  floor is preserved; interactive silhouettes remain at least 44px and primary text keeps the essential
  hierarchy.
- `nested-boundary`: 71 reviewed control bezels or independent scroll/select/dialog subregions.
  The descendant and ancestor edges have distinct jobs and the rendered pass found no same-level double
  bezel.

The acceptance is fail-closed. `scripts/check_kokuen_v5_lint.py` fingerprints every canonical warning,
assigns each one a declared semantic job, and fails if any warning appears, disappears, changes line or
message, or lacks a known resolution. Run its `--report` mode for the exhaustive line-by-line table.

```sh
python3 scripts/check_kokuen_v5_lint.py
python3 scripts/check_kokuen_v5_lint.py --report
```

The checker discovers an installed canonical linter beside the repository or in the user's skill
directories. Set `KOKUEN_LINTER` to its `lint_ui_rules.py` path to override discovery.
The September 21 cleanup removed three warnings belonging to the retired Files sort, quota, and tag
styles; the remaining warning messages are unchanged, with refreshed source positions.
The September 25 Plan repair added two overlay lines. Running the same canonical linter
on the earlier and current sources confirmed the same 192 severity/rule/message tuples;
the digest is refreshed for those offsets without approving any new warning.
The real-app contrast and switch gates supplement
the unchanged source-level acceptance; warning reconciliation alone is not visual proof.

The September 26 Files recovery rules move existing source positions without adding warning
semantics. A comparison against the preceding commit retains the same 192 severity/rule/message
tuples. Transfer error reasons use 14px text; their wrapping and scroll clearance are checked in the
Files transfer browser gate at desktop and phone widths, including constrained height.

This is a source-level advisory audit. It supplements, and does not replace, real rendered checks for
one perceived boundary, focus clipping, target size, text legibility, zoom, responsive layout, and
reduced motion.

The companion regression also scans shipped CSS, HTML, and dynamic JavaScript templates for `rem` or
pixel text below 12px, closing the legacy source and inline-style gap outside the overlay.

The Server feedback and Settings context additions likewise retain the same
192 warning semantics. Settings' persistent section name uses 14px essential text;
its wrapping header and close target have narrow-width browser checks. Source
positions are refreshed after the scoped rules are inserted.

The September 27 app-name switcher removes the persistent rail and its border. The
canonical audit now has 71 nested-boundary warnings rather than 72; small-type stays
at 120 and there are no hard errors. The digest is refreshed for that removal and the
shifted source lines. Rendered desktop/phone and settings checks remain separate proof.

The later neutral Settings controls shifted source positions in `static/kokuen.css`.
Comparing the installed canonical linter's findings before and after that change found
the same 191 severity/rule/message tuples, with no added or removed warning meanings.
Only the line-sensitive digest was refreshed; rendered Settings checks remain separate.
