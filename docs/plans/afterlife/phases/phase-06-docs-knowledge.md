# Afterlife Phase 6 — Docs and knowledge migration

- **Status:** delivered — Docs migration and the cross-app correction gate passed fresh verification
- **Started:** July 14, 2026
- **Parent design:** [`../design.md`](../design.md)
- **Depends on:** Phase 5 delivered and verified
- **Interface rule:** approve a standalone KOKUEN HTML starter before changing the real Docs interface
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

## Goal

Make Docs safe enough to use as the main Markdown workspace without trapping the owner inside Alles.
Obsidian remains the recommended desktop companion. The built-in editor remains a complete local and
recovery path.

At the end of this phase:

- normal Markdown opens in Visual or Source mode without silent rewriting;
- focused edits preserve unrelated syntax and files;
- external Obsidian edits produce an understandable conflict instead of lost work;
- drafts, revisions, trash, restore, rename, links, and vault moves recover safely after failure;
- Notes and non-private Journal content share one Docs surface;
- private locked Journal content keeps its stronger boundary;
- Aide can discuss the open note only with the owner's normal permission and context rules.

## 6A — preservation proof

- [x] Inventory the current Docs, Notes, Journal, vault, watcher, write, trash, backup, and restore paths.
  See [`../phase-06-preservation-spike.md`](../phase-06-preservation-spike.md).
- [x] Build a throwaway Markdown corpus with frontmatter, wiki links, embeds, callouts, tables,
  footnotes, task lists, HTML, code blocks, malformed syntax, invalid bytes, and very large files.
- [x] Test the source-authority round trip with no edit and require byte-for-byte equality. Visual
  editor candidates must pass the same corpus before they can ship.
- [x] Test small edits and require unrelated syntax and files to remain unchanged.
- [x] Record unsupported constructs clearly. Reject an editor candidate that cannot preserve them.
- [x] Keep every spike and test on a throwaway vault; never use the owner's normal vault.

## 6B — interface approval

- [x] Create `docs/mockups/afterlife-navigation/docs.html` as a standalone KOKUEN starter.
- [x] Include fake notes and only minor local interactions needed to inspect navigation, Visual/Source,
  conflict, empty, loading, and error states.
- [x] Test the starter on desktop and mobile with keyboard, reduced motion, no native controls, no
  overflow, and no console errors.
- [x] Owner approved the Docs direction on July 14, 2026, with one correction: replace the generic
  rectangular file and folder marks with clear document, note, Journal, and folder icons.

The approved direction is viewer-first. **Open in Obsidian** is the main action. The built-in editor is
an on-demand, open-source CodeMirror 6 Markdown editor over the exact same file, not a proprietary
document format or a replacement vault. The existing Journal heatmap, mood, topic, search, and history
experience remains intact inside the Docs product instead of being flattened into a generic note list.

## 6C — safe document foundation

- [x] Extend expected-hash and atomic writes with comparison, exact conflict copies, private drafts,
  and exact-byte revisions. These APIs remain disconnected from the current Docs reader until 6B is
  approved.
- [x] Make partial Notes updates preserve unknown frontmatter, comments, key order, line endings, and
  unrelated body bytes. Stale no-op updates and ambiguous duplicate managed keys fail closed.
- [x] Journal multi-file rename and link updates so a crash can resume or roll back safely without
  replacing a newer external edit.
- [x] Build an explicit Journal migration transaction for non-private and deliberately unlocked daily
  notes. It stages privately, preflights every source and target before writing, resumes exact files,
  and rolls back only unchanged files it created. The Journal database remains authoritative until the
  approved Docs cutover.
- [x] Keep external filesystem watching, use nanosecond signatures, and distinguish local, external,
  and draft-conflicting changes across a process restart.
- [x] Preserve trash and restore without deleting the only copy. The registry is committed before the
  move, move failure rolls it back, missing trash bytes keep their registry row, and restore never
  replaces a newer file.
- [x] Build vault move/relink as backup → stage → hash → switch → verify → optional old-location delete.
  The operation is restart-safe, keeps the old vault by default, and never cross-device renames the
  source.
- [x] Require a separate exact confirmation before deleting an old vault location; keep the verified
  private backup so rollback can restore the old location.
- [x] Include a configured external vault in encrypted local, WebDAV, and S3 recovery archives. A
  restore remaps it under the new Alles data root and never writes into the old external path.

## 6D — unified Docs

- [x] Implement only the approved starter direction in the existing vanilla JavaScript/CSS stack,
  with the corrected semantic icons.
- [x] Make the rendered viewer the default; keep **Open in Obsidian** primary and expose the
  CodeMirror 6 live/source editor only when the owner chooses Edit.
- [x] Add Visual and Source editing modes over the same exact Markdown file.
- [x] Merge Notes and non-private Journal views without deleting or duplicating source files.
- [x] Connect the explicit Journal migration to the approved interface while keeping private locked
  Journal content behind its existing unlock boundary.
- [x] Keep the existing Journal heatmap, mood trends, correlations, topics, search, on-this-day, and
  recent-entry tools available from the unified Docs product.
- [x] Add **Ask Aide about this note** with visible note scope and normal Aide permissions.
- [x] Preserve old Notes, Journal, and Docs links through compatibility redirects. Unit, host, and
  rendered-browser checks keep the original query, fragment, and deep-link state while moving legacy
  hosts into `docs.localhost`.

## Small Apps follow-up

The current Apps directory is already approved and working. A requested minor consistency pass is
tracked separately from Docs data work:

- [x] revise the standalone Apps HTML starter first and test its desktop/mobile, keyboard, reduced-
  motion, custom-control, overflow, and console behavior;
- [x] get explicit owner approval;
- [x] then align shared spacing, type, and navigation with Home, Aide, and Andromeda;
- [x] align compact, empty, loading, partial, and error states without changing specialist data flows;
- [x] do not redesign specialist data flows or pull Phase 8 consolidation into Phase 6.

## Cross-surface stabilization completed during Phase 6

- [x] Keep Home's Aide brief short and plain-text even when its source contains Markdown or a long
  model answer. Bump the shell/module cache stamp so the fixed Home cannot remain stuck on an older
  script after refresh.
- [x] Close the Project branch menu after a refused switch and replace the oversized raw Git error with
  a short bounded conflict message. Safe uncommitted changes still move with the branch; only proven
  overwrite conflicts are refused.
- [x] Keep macOS, Linux, Windows, and fallback ASCII marks on the same 1:1 stage. Use one seamless
  six-second color cycle with no pulse, bloom, second loop, or visible restart.
- [x] Verify Home/Apps, Aide, and the Linux System mark in rendered desktop and mobile browsers with no
  unexpected console errors.

## Gate

Phase 6 is delivered only when simultaneous Obsidian edits, no-op saves, focused edits, malformed input,
invalid bytes, large files, rename crashes, delete/restore, watcher restart, same- and cross-filesystem
vault moves, no-space, permission failure, external edit during move, rollback, and backup/restore all
leave the original or a verified replacement usable. Desktop, mobile, keyboard, reduced-motion, empty,
loading, conflict, offline, and error checks must use isolated data and report no unexpected console,
page, or server errors.

The 6A/6C preservation and recovery gate and the approved 6D interface are green with isolated data.
The final repository-wide backend run passes 4,190 tests with 4 skips. The final frontend run passes
225 JavaScript tests. Rendered-browser gates cover the viewer-first Docs flow,
lazy CodeMirror loading, exact Markdown source, safe saves, external-edit conflicts, private drafts,
Aide note scope, Journal migration prepare/apply/rollback, retained Journal tools, legacy routes,
desktop/mobile layout, themes, keyboard behavior, reduced motion, and console errors.

The owner vault was not used for these checks. The later cross-app correction pass was reopened after
its truth audit, then completed with live SearXNG/model coverage, all permission and speech flows, and
the 19-app browser matrix. Its final evidence lives in
[`phase-06-correction-pass.md`](phase-06-correction-pass.md). Phase 7 may now resume.
