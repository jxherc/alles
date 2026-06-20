# ui-3m — comments: make the select→comment flow work

The comment chip only listened on `#wiki-preview`, but the editor opens in **live** mode by default — so
selecting text and trying to comment did nothing. Fixed (`static/js/vaultmd.js`):

- Renamed `_onPreviewSelect` → `_onDocSelect` and bound it to **both** `#wiki-preview` and `#wiki-live`
  `mouseup`, so a selection in the live (CM) editor surfaces the "comment" chip too.
- The chip is now `position: fixed` (viewport coords) instead of `absolute` + window-scroll math, so it
  lands on the selection inside the internally-scrolling editor.
- Empty-state copy now points at the editor: "select any text in the editor and click the comment chip".

The rest of the flow (chip → prompt → `POST /api/vault-md/comments` → thread render with anchor, replies,
resolve/delete) already worked and is exercised end-to-end.

Tests: `tests/test_docs.py::CommentFlowTests` (3) + `docs/evidence/ui-3m/verify.py` (live selection shows the
chip, prompt opens, thread created + rendered with the body and the selected-text anchor, 0 errors).
