# ui-6a — gallery UI rebuild (header / grid / lightbox)

The gallery was functional but ragged: every header control carried its own inline
`style="font-size:0.72rem"`, the lightbox actions wrapped in a loose flex row, and the grid/lightbox
spacing was tight. Reworked `#photos-view` into a coherent layout — no functional change, just chrome.

- **Header** (`static/index.html`): `class="page-view-head photos-head"`; dropped the per-control inline
  font sizes. One scoped rule (`.photos-head .btn/.custom-select/.photos-search`) sizes them; album/model
  selects keep their caps via `.photos-album-sel`/`.photos-model-sel`; trash pinned right with
  `.photos-trash { margin-left:auto }`.
- **Grid**: column gap 1.3→1.5rem, moment label typography, cells `minmax(130→140px)` gap `3→4px`.
- **Lightbox**: side panel `240→264px` with more padding/gap; actions are now a tidy 2-col grid
  (`.photos-lightbox-actions { display:grid; grid-template-columns:1fr 1fr }`) with centered icon+label
  buttons; exif rows get a top border.

Gallery is account-gated (hidden on the test server), so verification reads computed styles via the DOM.

Tests: `tests/test_photos_gallery.py` (7 source-contract) + `docs/evidence/ui-6a/verify.py` (header
controls share one font-size, no inline font-size, lightbox side ≥260px + 2-col action grid, 0 console
errors).
