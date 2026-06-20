# ui-3t — docs settings + AI status + model picker; remove Guide

- **Removed the markdown Guide** (`#wiki-help-btn`, the home `guide` button, and the whole `#wiki-help`
  cheat-sheet panel + its CSS) — the live-preview editor is self-explanatory now.
- **Docs settings** ⚙ button (`#wiki-docs-settings`) → `openDocsSettings()` popup (`static/js/vaultmd.js`):
  an **AI status line** (green dot "AI ready · using <model>" / muted "no model — add one in settings") read
  from `/api/models`, and a **model picker** listing every connected model; choosing one PATCHes
  `docs_ai_model`.
- **Backend honours it**: new `_docs_ai(db)` resolver (`routes/vault_md.py`) prefers the `docs_ai_model`
  setting (when an enabled endpoint serves it) and otherwise falls back to the first enabled endpoint. The
  four doc-AI routes (`ai-snippet`, `extract-todos`, `ask`, `ai-edit`) all route through it.

Tests: `tests/test_docs_ai_snippet.py::DocsAiModelTests` (3: setting picks the right endpoint/model, falls
back without a setting, falls back on an unknown model) + `tests/test_docs.py::DocsSettingsTests` (4) +
`docs/evidence/ui-3t/verify.py` (guide gone, popup opens with AI-ready status + 2 models, selecting sets it,
PATCH writes docs_ai_model, 0 errors) + `settings.png`.
