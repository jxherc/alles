# ui-3c audit — inline live-preview engine (RED state)

Seeded `livetest.md` with every element, opened it in docs live mode (`live-current.png`,
`live-dom.html`). The existing `livePreview` plugin in `.cmbuild/cm-entry.js` only handles **headings**
(line class) and **inline marks** (bold/italic/strike/inline-code) + hides their syntax markers. Everything
block-level renders as raw markdown text. Confirmed via DOM probe: `imgs:0 tables:0 checkboxes:0 callouts:0
links:[]`.

What's broken in live mode (each becomes a 3c sub-task):

**3c-1 inline:**
- **Link** `[text](url)` → shows `text` *and* the raw `https://…url` (LinkMarks hidden but the `URL` node
  isn't). Want: only the text, styled as a link (`<a>` with href), URL hidden unless cursor on the line.
- **Highlight** `==x==` → shows raw `==x==` (not in lezer base). Want: rendered highlight, `==` hidden.

**3c-2 block widgets:**
- **Image** `![alt](url)` and `![[file]]` → render as alt/name text, no `<img>`. Want real `<img>` (the
  `![[ ]]` form resolves via `/api/vault-md/raw?path=`).
- **Table** (GFM) → raw `| col |` rows. Want a real `<table>` when the cursor isn't inside it.
- **Callout** `> [!note] title` → shows `> !note title` as a plain quote. Want a styled callout block.
- **Quote** `>` and **HR** `---` → raw. Want a left-bar quote line and an `<hr>`.

**3c-3 lists:**
- **Bullet** `- x` → raw dash. Want a `•` marker.
- **Numbered** `1.` → raw (kept as text, just needs to read as a list).
- **Checkbox** `- [ ]` / `- [x]` → raw text. Want a real `<input type=checkbox>` that toggles the source.

Build target: extend `buildDeco()` in `.cmbuild/cm-entry.js` with widget (`WidgetType`) replace-decorations
for the block/inline elements, revealed to raw only on the cursor's line(s) (same `active` line-set the
plugin already computes). Rebuild the bundle with
`cd .cmbuild && npx esbuild cm-entry.js --bundle --format=esm --minify --outfile=../static/vendor/cm6.bundle.js`
(confirmed: reproduces the current 589 kB bundle byte-for-byte).
