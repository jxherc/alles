# ui-3g — remaining element live-views

Most live-views (bullet, checkbox, quote, callout, separator/hr, inline-code) were delivered by the ui-3c
engine. This microversion adds the two that were still raw + polishes inline code:

- **Fenced code** → a shaded live block: `FencedCode` lines get `.cm-codeblock` (+ `-top`/`-bot`) line
  decorations in `.cmbuild/cm-entry.js` — monospace on a `var(--panel)` fill, rounded top/bottom; CM's
  syntax highlighting still applies inside.
- **Inline code** reads **Discord-style**: `.cm-code` gets a subtle `var(--faint)` pill background + padding.
- Re-verified the 3c live-views all render together (bullet/check/quote/callout/hr).

Scope note: the roadmap mentioned ordered-list **style options (1. / a. / i.)**. Markdown ordered lists are
plain `1.` text; rendering them as `a.`/`i.` would desync what's shown from the portable source (and no
parser would round-trip it), so that gold-plating is intentionally **not** built — numbered lists already
render correctly and losslessly.

Tests: `tests/test_docs_live.py::CodeViews3g` (2) + `docs/evidence/ui-3g/verify.py` (code block shaded +
monospace, inline-code pill, bullet/check/quote/callout/hr all present, no console errors).
