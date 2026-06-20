# docs / wiki — audit findings (2026-06-18)

Drove `docs.localhost:8799` in Playwright (chromium, 1280×850). Screenshots: 01-empty, 02-doc-open
(tree visible), 03-after-reload, 04-tree-hidden-head. Console log in `audit.json`.

## What was exercised (real data)
- empty state renders (recent list + new/today/guide actions).
- tree lists real docs (Periodic/2026-06, 2026-W25, projects/alpha, beta, GA…GE, q1-3, Roadmap, sprint…).
- opened `Periodic/2026-06.md` → live CM editor renders headings, formatting toolbar present.
- mode/ai/guide/outline/props/query/board/todos/tasks/history/export/delete buttons all present.
- **Zero console errors** across load, open, reload.

## Defects confirmed

### B (the real one, user-reported) — no per-doc URL; refresh loses the open doc
- After opening a doc the URL stays `http://docs.localhost:8799/` — **no `?doc=`** (measured: "URL has ?doc= : False").
- On reload, `#wiki-current` resets to "no doc open" and the empty state reappears
  (measured: "DOC SURVIVES RELOAD: False"). Violates the global routing rule and is exactly the user's
  complaint: "every doc should have a unique address so if i refresh in the documents i wont be located
  to the home page of docs again."

### A — editor-head buttons stranded far-right (the "too far away" gap)
- The plan hypothesized "edge-to-edge huge gaps"; the buttons are actually tightly grouped
  (inter-button gaps 5–6px — `#wiki-stats{margin-left:auto}` absorbs `.page-view-head`'s
  `justify-content:space-between`). So the *button spacing* is fine.
- BUT in the **default tree-hidden** state the head spans full width (1279px): doc-name ends at x=158,
  the first action button starts at x=640 — a **482px dead gap** — and the cluster runs to the far-right
  edge (x=1213). That stranded cluster + huge empty middle is the "buttons too far away" imperfection
  (see `04-tree-hidden-head.png`).

## Fix (one task → `docs-ui-1`)
- **Routing:** `openFile()` → `history.replaceState` `?doc=<path>`; `_resetEditor()` clears it;
  `initVault()` after `loadTree()` reads `?doc=` and opens it → deep-link + refresh restore the doc.
- **Head balance:** override `.docs-editor-head { justify-content: flex-start }` and drop the
  `margin-left:auto` stranding on `#wiki-stats`, so the doc-name + stats + action buttons form one
  left-aligned cluster with no dead gap (buttons sit next to the title, still tightly grouped).

No backend change. Verified via Playwright (≥8 assertions, RED→GREEN) + screenshot, zero console errors.
