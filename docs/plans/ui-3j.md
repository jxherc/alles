# ui-3j — native spellcheck / typo underline

The raw source textarea already had `spellcheck="true"`; the CM wysiwyg surface defaults it **off**. Added
`EditorView.contentAttributes.of({ spellcheck:"true", autocorrect:"on", autocapitalize:"sentences" })` to the
editor extensions in `.cmbuild/cm-entry.js` (rebuilt bundle), so the browser's native misspelling underline
now works on both editing surfaces without fighting CodeMirror.

Tests: `tests/test_docs_live.py::EngineShape::test_spellcheck_enabled` + `docs/evidence/ui-3j/verify.py`
(both `.cm-content` and `#wiki-source` report `spellcheck="true"`).
