# ui-9 — final regression (capstone)

- **Full backend suite**: `python -m unittest discover -s tests` → 2512 tests, OK.
- **Broad sweep** (`docs/evidence/ui-9/sweep.py`): all 16 hosts (apex + aide + 14 apps) boot with 0 real
  console/page errors.
- **Deep click-through**: 6 primary flows exercised live — files smart folders, calendar segmented view
  switch (all 5 views), tasks add, contacts add/open, gallery upload + lightbox, vault unlock + settings
  (Stage-8 panels) + lock — all clean.
- **Cache stamps** bumped to `?v=89` / `const _v='89'` / sw `VERSION='v63'` `STAMP='89'`.

All earlier microversions (Stages 0–8) carry their own gate tests + `docs/evidence/<v>/verify.py`.
