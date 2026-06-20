# ui-3s — todos-extraction + backlinks explainers

Two features were powerful but unexplained (`static/js/vaultmd.js`, CSS):

- **AI todo-extraction** (`#wiki-todos-btn`) used to fire immediately. It now opens `openTodosExplainer()` —
  a `.wiki-explainer-pop` that says what it does ("scans this doc for action items… creates real tasks in the
  tasks app. The doc isn't changed.") with an **extract to-dos** button that runs the actual extraction
  (`_runExtractTodos`).
- **Backlinks panel** gets a permanent purpose header (`.wiki-bl-explainer`): "backlinks — other docs that
  `[[link]]` to this one; unlinked mentions name it in plain text without a link yet", and the empty state is
  now actionable: "nothing links here yet — add `[[<doc>]]` in another doc".

Tests: `tests/test_docs.py::ExplainerTests` (4) + `docs/evidence/ui-3s/verify.py` (todos opens an explainer
with a run button — not a direct run; backlinks explains itself; 0 errors) + `explainers.png`.
