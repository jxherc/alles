# DOCS App UI Audit — findings.md

Audited: http://docs.localhost:8870/
Date: 2026-06-20
Scripts: audit_script.py, audit2.py, audit3.py, audit4.py (in this directory)
Screenshots: all *.png files in this directory

---

## 1. Initial Load / Home State

**Exercised:** cold load.
**Works:** page loads, empty state shows "no docs yet", three CTA buttons visible (+ new doc, today's note, guide).
**Looks bad:** entire left rail (+doc button, tree) is hidden — just a blank black canvas. `#wiki-new-btn` is in the DOM but not visible until a doc exists.

Screenshots: 01-initial-load.png, 02a-home-empty.png

---

## 2. New Doc Modal

**Exercised:** clicking `#wiki-empty-new`, filling dialog, pressing Enter.
**Works:** dialog appears centered, input auto-focuses, Enter submits, doc creates and editor opens.
**Looks bad:** dialog label sits outside the input, no visual dialog title, input affordance is underline-only.

Screenshot: 02b-new-doc-dialog.png

---

## 3. Editor — Live Mode Rendering

**Works:**
- Table renders as actual cell layout (not raw pipe characters)
- Code block shows Python syntax coloring, language tag, fold indicator
- Headings are visually distinct (bold + underline decoration)
- Bold and italic render inline (not raw **)
- Inline code renders with monospace + subtle background
- Links show as styled anchor + URL

**Broken:**
- Checkboxes — `- [ ]` and `- [x]` render as literal text, not interactive tick boxes
- Image — `![alt](url)` renders as "alt-text URL" on one line, no image widget
- Callout — `> [!note]` shows as literal text lines, no callout box
- Blockquote — `>` lines have no left-border decoration in live mode
- Numbered list double-prefix — renders "2. 2. Second numbered item" (number duplicated — bug)
- HR — `---` renders as literal three dashes, not a visual divider
- Wikilink — `[[...]]` has no special styling, same color as body text

Screenshots: 03-rich-md-live-mode.png, a4-01-doc-ready.png

---

## 4. Editor — Source Mode

**Works:** raw markdown in monospace. Format toolbar stays available.
**Looks bad:** no line numbers, no visible border — hard to distinguish from live mode at a glance.

Screenshot: 04-mode-step1-source.png

---

## 5. Editor — Preview Mode

**Works:**
- H1/H2/H3 render as proper headings
- Bold, italic, inline code render as HTML elements
- Table renders as HTML table with borders and headers
- Code block has language label + copy + run buttons + syntax highlight
- HR renders as a visible horizontal rule
- Links render as blue underline anchors
- Checkboxes render as `<input type="checkbox">` elements
- ol/ul render correctly

**Broken:**
- Image — zero `<img>` elements in `#wiki-preview`, image is completely absent
- Callout — `> [!note]` renders as plain blockquote with the `[!note]` as text content
- Checked checkbox — `- [x]` does NOT pre-check the input, both render unchecked
- Wikilink — `[[...]]` has no special link styling

Screenshot: 04-mode-step2-preview.png

---

## 6. Toolbar Buttons

All 19 buttons exercised. Results:

- wiki-mode-toggle: OK — cycles live/source/preview
- wiki-ai-toggle: OK — activates AI edit bar at bottom
- wiki-ask-btn: OK — opens ask-your-notes right panel with search + web-clipper
- wiki-help-btn: OK — opens markdown guide right panel
- wiki-outline-btn: OK — opens outline panel
- wiki-props-btn: OK — opens properties/frontmatter panel
- wiki-query-btn: OK — opens query/dataview panel
- wiki-base-btn: OK (activates, no visible output for single-doc context)
- wiki-canvas-btn: PARTIAL — requires "canvas name:" dialog with no default name
- wiki-board-btn: BROKEN — shows "failed to load board" on full-screen overlay
- wiki-todos-btn: OK (fires, no feedback without AI model configured)
- wiki-taskroll-btn: OK — opens tasks panel
- wiki-history-btn: BROKEN — panel opens but is blank, no history entries shown
- wiki-bookmark-btn: OK — shows "bookmarked" toast at bottom-right
- wiki-comments-btn: OK — opens comments panel (empty)
- wiki-publish-btn: OK — publishes, shows URL in toast
- wiki-split-btn: OK — opens split view with placeholder in right pane
- wiki-theme-btn: OK — opens CSS snippet editor panel
- wiki-export-btn: OK — dropdown with: word (.docx), html, pdf/print
- wiki-delete-btn: OK — confirmation dialog "delete filename.md? cancel / confirm"

**Broken:**
- `#wiki-board-btn` shows "failed to load board" — feature completely non-functional. Screenshot: a3-tb-wiki-board-btn.png
- `#wiki-history-btn` panel is blank — no version history despite multiple saves. Also leaks "no tasks" text from tasks panel DOM. Screenshot: a3-panel-history.png

**Mutual exclusivity test (outline + props + query all clicked):**
Props AND query both remain showing "active" glow simultaneously, only one panel rendered. Screenshot: a3-mutual-excl.png

**Looks bad:**
- "published" button stays glowing after publish with no unpublish affordance
- Published URL appears only in a transient toast with no copy button
- Bookmarked + published toasts overlap at bottom-right corner
- History panel leaks "no tasks" text from adjacent panel DOM
- "tasks" vs "todos" buttons distinction is not communicated in their labels

---

## 7. Format Toolbar (#docs-toolbar)

**Exercised:** all 21 [data-fmt] buttons with text selected.
**Works:** all 21 buttons clicked successfully — inline formats wrap text, block formats prepend prefix, insert formats add template markdown.
**Looks bad:**
- No visual group dividers between inline / block / insert sections — 21 buttons in an unbroken flat strip
- `A` (font color) label is cryptic
- Format row sits immediately below the doc toolbar row with almost no visual gap

Screenshot: a3-fmt-toolbar.png

---

## 8. Multiline Selection

**Works:** 5-line selection completes correctly.
**Broken/bad:** selection highlight background starts 52px left of the text content, bleeding into the fold-indicator gutter. Confirmed by geometry: sel.x=357, editor.x=290, content.x=309 — highlight fills the full editor wrapper including the gutter. The selection color is browser-default blue, not the accent color.

Screenshot: a4-multiline-sel.png — clearly shows the purple selection covering the gutter margin left of the text.

---

## 9. Right-Click Context Menu

**Works:** a CUSTOM context menu appears (class: `ctx-menu`) — confirmed via DOM query. Not the native browser menu.
**Looks bad:** menu was not captured in the screenshot (may have appeared at a position partially outside the viewport).

Screenshot: a4-right-click.png

---

## 10. History Panel

**Works:** panel opens.
**Broken:** completely blank — no version history entries despite multiple saves. Also displays "no tasks — add - [ ] items in your docs" text leaked from the tasks panel.

Screenshot: a3-panel-history.png

---

## 11. Export Menu

**Works:** dropdown opens with three options: "word (.docx)", "html", "pdf / print".
**Looks bad:** bare text-only items, no icons, no keyboard shortcuts. "pdf / print" slash inconsistent with other labels.

Screenshots: a3-tb-wiki-export-btn.png, a4-export-menu.png

---

## 12. Split View

**Works:** split activates, right pane appears with "open another doc to split" placeholder.
**Looks bad:** placeholder has no button or action affordance. No visible draggable divider. Tab bar becomes ambiguous in split mode.

Screenshots: a3-tb-wiki-split-btn.png, a4-split-view.png

---

## 13. Tabs Bar (#wiki-tabs)

**Works:** tabs render with doc name and x close button. Active tab styled differently. Flex layout, does not overflow for 3 tabs.
**Looks bad:**
- Close x is a bare character — small hit target
- Names truncate on narrow tabs with no tooltip
- Entire main toolbar disappears when navigating to home, only the tab bar stays — jarring mode shift

Screenshot: a4-tabs-bar.png

---

## 14. Backlinks

**Works:** element present at doc bottom, shows "no backlinks".
**Looks bad:** no "Backlinks" section heading — user must already know what they are looking at. Text is muted to near-invisibility.

---

## 15. Delete Button

**Works:** confirmation dialog "delete filename.md? / cancel / confirm" appears, confirm is red, Escape dismisses.
**Looks bad:** file extension `.md` leaks into the dialog. No warning icon for a destructive action.

Screenshot: a3-tb-wiki-delete-btn.png

---

## 16. Outline Panel

**Works:** headings listed (Heading 1, Heading 2, Heading 3 confirmed).
**Looks bad:** H2 and H3 are NOT indented under H1 — all headings appear at the same left margin, no hierarchy visible.

Screenshot: a3-panel-outline.png

---

## 17. Query Panel

**Works:** full dataview UI — property field, operator select (eq/ne/contains/gt/lt/exists/missing), sort, run, insert block, save view.
**Looks bad:** no explanation of what the panel does or what properties the current doc has. Operators listed with no descriptive labels.

Screenshot: a3-panel-query.png

---

## 18. Comments Panel

**Works:** opens.
**Looks bad:** completely blank — no empty state message, no instructions for adding a comment.

---

## 19. Publish

**Works:** doc publishes, URL shown at bottom-right.
**Looks bad:** URL only in transient toast, no copy button, no persistent link. Button changes to "published" with no visible unpublish affordance.

Screenshot: a3-tb-wiki-publish-btn.png

---

## 20. Console Errors

No JavaScript errors captured during toolbar interaction and normal navigation. The board "failed to load board" was a gracefully-caught UI error message, not a thrown exception.

---

## TOP FINDINGS SUMMARY

### BROKEN (functional — need fixes)

1. Kanban board broken — `#wiki-board-btn` shows "failed to load board". a3-tb-wiki-board-btn.png
2. Images not rendered — zero `<img>` in preview; live mode shows alt+url as inline text. 04-mode-step2-preview.png
3. Callouts not rendered — `> [!note]` stays as plain blockquote in both live and preview.
4. Numbered list double-prefix in live mode — "2. 2. Second". 03-rich-md-live-mode.png
5. History panel empty — no entries; also leaks tasks-panel DOM text. a3-panel-history.png
6. Panel mutual exclusivity broken — props+query both glow active, only one renders. a3-mutual-excl.png
7. Checkboxes not rendered in live mode — `- [ ]` stays as literal text.
8. Checked checkbox (`- [x]`) not pre-checked in preview mode.

### LOOKS BAD (visual / UX — need polish)

1. Selection highlight bleeds into gutter — ~52px overshoot left of text column. a4-multiline-sel.png
2. No format toolbar group dividers — 21 buttons in a flat unbroken strip.
3. Outline panel no indentation — H2/H3 same left margin as H1.
4. Comments panel blank — no empty state.
5. Split view right pane has no action button — hint text with no affordance.
6. Publish URL only in transient toast — no persistent copy affordance.
7. Multiple active-glow buttons for closed panels — misleads user.
8. Export dropdown bare — text-only, no icons, no shortcuts.
9. Image fallback in live mode — alt-text + raw URL on one line is noisy.
10. History panel shows leaked "no tasks" text from adjacent panel.
