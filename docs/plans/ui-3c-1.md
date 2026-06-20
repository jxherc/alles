# ui-3c-1 — live preview: inline marks

Extend the live-preview engine in `.cmbuild/cm-entry.js` (rebuilt to `static/vendor/cm6.bundle.js`).

- **Highlight `==x==`**: added a tiny `@lezer/markdown` inline extension (`HighlightExt`, same shape as GFM
  strikethrough) → `Highlight`/`HighlightMark` nodes. `Highlight` → `.cm-mark`; `HighlightMark` hidden off-line.
- **Link**: the link text becomes a real `<a>` (mark with `tagName:"a"` + `href`/`target`), and `[` plus
  `](url)` are replaced (hidden) when the cursor isn't on the line — so only the styled text shows, never the URL.
- bold/italic/strike/inline-code already worked; kept.

Tests: `tests/test_docs_live.py::InlineMarks3c1` (bundle+CSS gate) + `docs/evidence/ui-3c/verify.py`
(behavioral: link is an anchor with href, URL hidden, highlight renders).
