# ui-6a — gallery rebuild (findings)

## Audit
Gallery is account-gated, so on the test server only the crumb shows until a photo is uploaded (an
upload makes cells render). The header repeated `style="font-size:0.72rem"` on every control; the
lightbox actions wrapped as a ragged flex row; grid/lightbox spacing was tight.

## Fix
Scoped the header to `.photos-head` with one control-sizing rule (no inline font sizes), pinned trash
right, loosened the grid, widened the lightbox side panel to 264px and made its actions a centered
2-column grid.

## Verify
`verify.py` (computed styles via DOM on `gallery.localhost:8872`): header controls all share one
font-size (11.52px), no inline font-size remains, the force-shown lightbox side is 264px and its actions
lay out as 2 columns. 0 console errors.
