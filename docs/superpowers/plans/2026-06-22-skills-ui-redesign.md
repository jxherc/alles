# Skills UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the skinny single-column skills view with a category-rail + card-grid surface so 252 skills and the library are browsable without endless scrolling.

**Architecture:** Frontend-only rewrite of the render layer in `static/js/skills.js`, driven by a small module state object (`mode`, `cat`, `q`, `editing`). A left category rail filters a responsive multi-column card grid; the library is a mode of the same surface; the editor moves into a right slide-over drawer. No backend changes — `/api/skills` and `/api/skills/catalog` already serve `category`/`pinned`/`uses`/`source`. Styling follows kokuen.

**Tech Stack:** Vanilla ES modules (no framework), `fetch`, kokuen CSS tokens, Playwright (python sync API) for behavioral tests.

## Global Constraints

- Commits: author name `jxherc`, email `houjx0103@gmail.com`; message all lowercase; no AI/codex/claude attribution. Use `git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit`.
- No backend changes. Reuse existing endpoints only: `GET /api/skills[?q=]`, `GET /api/skills/catalog`, `POST /api/skills/install`, `GET/PUT/POST/DELETE /api/skills/{slug}`, `POST /api/skills/{slug}/pin`, `GET /api/skills/{slug}/export`, `POST /api/skills/{slug}/update`, `POST /api/skills` (create), `POST /api/skills/import-github`, `POST /api/skills/upload`.
- No structural `index.html` change — `#skills-body` is populated entirely by `initSkills`.
- Reuse existing module-level helpers/constants in `skills.js`: `_api`, `esc`, `$`, `toast`, `dlgConfirm`, `dlgPrompt`, `_CAT_LABEL`, `_CAT_ORDER`.
- kokuen styling: greyscale; tiny text; 1px borders; 2–3px radii; `--accent` only for active/interactive; `--signal` for the `✓ added` state; easing `cubic-bezier(0.2,0.7,0.2,1)`; hand-built controls (no native selects). Use existing tokens: `--bg --text --muted --faint --panel --accent --signal`.
- On ship (final task): bump `static/sw.js` `VERSION` + `STAMP` and `static/index.html` `_v`/`?v=` together, or returning clients serve stale JS.
- Server is `python app.py`, no `--reload` — restart it to pick up backend changes (none here, but tests boot their own server).

**Test harness (used by every task):** boot an isolated server, run the test, against a fresh seed with the service worker blocked.

```bash
# in repo root, pick a free port (examples use 8151)
ALLES_DATA=.tmp_skl_redesign AUTH_ENABLED=false PORT=8151 python app.py > .tmp_skl_srv.log 2>&1 &
# wait until it answers, then run the test, then kill it:
#   curl -s -o /dev/null http://127.0.0.1:8151/   # poll until 200
#   python tests/pw_skills_redesign.py 8151
#   netstat -ano | grep ':8151.*LISTENING'  -> taskkill //PID <pid> //F
```

The test file takes the port as `sys.argv[1]`. The skills view is reached at
`http://aide.localhost:<port>/` then `window._navigateTo('skills')`. Chromium resolves
`*.localhost` to 127.0.0.1. Always create the browser context with
`service_workers="block"` (the SW is network-first and would otherwise re-serve stale JS),
and load `skills.js` fresh each run.

---

### Task 1: New shell — header + category rail + installed card grid + category filter

Replaces `initSkills`, `_loadList`, `_groupRows`, `_renderGrouped`, `_skillRow` with a
state-driven shell. After this task the skills view shows a rail (counts per category) and
a multi-column grid of installed-skill cards; clicking a category filters the grid.
The drawer, library mode, search, pin/delete come in later tasks (their rail/cards exist
but their handlers are stubbed to no-ops where noted).

**Files:**
- Modify: `static/js/skills.js` (replace lines 18–153: `initSkills` through end of `_loadList`; also remove `_groupRows`/`_renderGrouped`/`_skillRow` which `_loadList` used — they're superseded). Keep `_collapsed`/`_setCollapsed` deleted (unused now).
- Modify: `static/style.css` (add the skills-redesign block; retire `.skills-wrap/.skills-side/.skills-main/.skl-list/.skl-row*/.skl-group*` once unused — do the retire in Task 6 to avoid churn mid-build).
- Test: `tests/pw_skills_redesign.py` (create).

**Interfaces:**
- Produces (used by later tasks):
  - module state `let _state = { mode, cat, q, editing }`, `let _data = []`, `let _cur = null`
  - `async function _refresh()` — fetch per `_state.mode`, set `_data`, call `_render()`
  - `function _render()` — paint rail + grid from `_state`/`_data`
  - `function _visible()` → filtered array (by `cat` + `q`)
  - `function _catCounts(rows)` → `{ [catKey]: number }` including `'all'`, `'pinned'`, `'custom'`
  - `const _catOf = s => (s.category && _CAT_LABEL[s.category]) ? s.category : 'custom'` (keep existing)
  - `function _card(s)` → card HTML string (extended in Tasks 2/4)
  - grid container id `skl-grid`, rail container id `skl-rail`, drawer host id `skl-drawer-host`

- [ ] **Step 1: Write the failing test**

Create `tests/pw_skills_redesign.py`:

```python
"""behavioral verify for the skills ui redesign. run against a fresh seeded server:
  ALLES_DATA=.tmp_skl_redesign AUTH_ENABLED=false PORT=8151 python app.py
  python tests/pw_skills_redesign.py 8151
"""
import sys
from playwright.sync_api import sync_playwright

IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def _skills_page(p, port):
    b = p.chromium.launch()
    ctx = b.new_context(service_workers="block")
    pg = ctx.new_page()
    errs = []
    pg.on("console", lambda m: errs.append(m.text)
          if m.type == "error" and not any(x in m.text for x in IGN) else None)
    pg.goto(f"http://aide.localhost:{port}/", wait_until="domcontentloaded")
    pg.wait_for_timeout(400)
    pg.eval_on_selector("body", "() => window._navigateTo('skills')")
    pg.wait_for_selector("#skl-rail", timeout=12000)
    pg.wait_for_timeout(400)
    return b, ctx, pg, errs


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8151"
    r = {}
    with sync_playwright() as p:
        b, ctx, pg, errs = _skills_page(p, port)

        # rail: 'all' + >=6 category rows with counts
        rail_rows = pg.eval_on_selector_all(
            ".skl-rail-cat", "els => els.map(e => e.dataset.cat)")
        r["rail_has_all"] = "all" in rail_rows
        r["rail_has_cats"] = len([x for x in rail_rows if x not in ('all',)]) >= 6
        counts = pg.eval_on_selector_all(
            ".skl-rail-cat .skl-rail-count", "els => els.map(e => +e.textContent)")
        r["rail_counts_positive"] = bool(counts) and all(c >= 0 for c in counts) and any(c > 0 for c in counts)

        # grid is multi-column: at least two cards share the same row (same offsetTop)
        tops = pg.eval_on_selector_all(
            "#skl-grid .skl-card", "els => els.slice(0, 8).map(e => e.offsetTop)")
        r["grid_multicol"] = len(tops) >= 2 and len(set(tops)) < len(tops)

        # clicking a category filters: card count changes and matches the rail count
        total = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        pg.eval_on_selector(".skl-rail-cat[data-cat='coding']", "el => el.click()")
        pg.wait_for_timeout(300)
        coding_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        coding_badge = pg.eval_on_selector(
            ".skl-rail-cat[data-cat='coding'] .skl-rail-count", "el => +el.textContent")
        r["filter_changes_count"] = coding_n != total and coding_n == coding_badge
        r["filter_active_marked"] = pg.eval_on_selector(
            ".skl-rail-cat[data-cat='coding']", "el => el.classList.contains('active')")

        r["no_console_errors"] = len(errs) == 0
        pg.close(); ctx.close(); b.close()

    ok = all(r.values())
    for k, v in r.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if not ok:
        print("errors:", errs[:6] if 'errs' in dir() else [])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the test, verify it fails**

Boot the harness server (port 8151), then `python tests/pw_skills_redesign.py 8151`.
Expected: FAIL — `#skl-rail` selector times out (old UI has no rail).

- [ ] **Step 3: Replace the render layer in `skills.js`**

In `static/js/skills.js`, keep lines 1–16 (imports, `_built`, `_cur`, `esc`, `$`, `_api`)
and the `_CAT_LABEL`/`_CAT_ORDER`/`_catOf` constants (lines 70–85). Delete the old
`_collapsed`/`_setCollapsed` (87–88), `_groupRows` (90–99), `_renderGrouped` (101–124),
`_skillRow` (126–135), and replace `initSkills` (18–65) + `_loadList` (137–153) with:

```javascript
// ── view state ────────────────────────────────────────────────────────────────
let _state = { mode: 'installed', cat: 'all', q: '', editing: null };
let _data = [];   // raw rows for the current mode (installed skills or catalog items)

export function initSkills() {
  const body = $('skills-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="skills2">
        <div class="skl-head">
          <span class="skl-title">skills</span>
          <input id="skl-search" class="settings-input skl-search" placeholder="search skills…">
          <button class="btn primary" id="skl-new">+ new</button>
        </div>
        <div class="skl-body">
          <nav class="skl-rail" id="skl-rail"></nav>
          <div class="skl-grid" id="skl-grid"></div>
        </div>
        <div id="skl-drawer-host"></div>
      </div>`;
    let t;
    $('skl-search').oninput = e => { clearTimeout(t); t = setTimeout(() => { _state.q = e.target.value.trim(); _render(); }, 200); };
    $('skl-new').onclick = () => _openDrawer(null);   // drawer added in Task 3; safe no-op until then
    // rail clicks (delegated): category select + library/github/upload actions
    $('skl-rail').addEventListener('click', e => {
      const cat = e.target.closest('.skl-rail-cat');
      if (cat) { _state.cat = cat.dataset.cat; _render(); return; }
      const act = e.target.closest('.skl-rail-act')?.dataset.act;
      if (act === 'library') _toggleLibrary();     // Task 4
      else if (act === 'github') _importGithub();
      else if (act === 'upload') $('skl-file')?.click();
    });
    _built = true;
  }
  _state = { mode: 'installed', cat: 'all', q: '', editing: null };
  _refresh();
}

async function _refresh() {
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  try {
    _data = _state.mode === 'library'
      ? await _api('/api/skills/catalog')
      : await _api('/api/skills' + (_state.q ? `?q=${encodeURIComponent(_state.q)}` : ''));
  } catch {
    if (grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>';
    return;
  }
  _render();
}

function _catCounts(rows) {
  const c = { all: rows.length, pinned: 0 };
  for (const s of rows) {
    if (s.pinned) c.pinned++;
    const k = _catOf(s);
    c[k] = (c[k] || 0) + 1;
  }
  return c;
}

function _visible() {
  const ql = _state.q.toLowerCase();
  return _data.filter(s => {
    if (_state.cat === 'pinned' && !s.pinned) return false;
    if (_state.cat !== 'all' && _state.cat !== 'pinned' && _catOf(s) !== _state.cat) return false;
    if (ql) return (`${s.name} ${s.description} ${s.when_to_use || ''}`).toLowerCase().includes(ql);
    return true;
  });
}

function _render() {
  _renderRail(_catCounts(_data));
  _renderGrid(_visible());
}

function _renderRail(counts) {
  const rail = $('skl-rail');
  if (!rail) return;
  const row = (key, label) => counts[key]
    ? `<button class="skl-rail-cat${_state.cat === key ? ' active' : ''}" data-cat="${key}">
         <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
       </button>` : '';
  let html = '';
  if (counts.pinned) html += row('pinned', 'pinned');
  html += row('all', _state.mode === 'library' ? 'library' : 'all');
  for (const k of _CAT_ORDER) if (k !== 'custom') html += row(k, _CAT_LABEL[k]);
  html += row('custom', 'custom');
  html += `<div class="skl-rail-foot">
      <button class="skl-rail-act${_state.mode === 'library' ? ' active' : ''}" data-act="library">⊕ library</button>
      <button class="skl-rail-act" data-act="github">↳ github</button>
      <button class="skl-rail-act" data-act="upload">↑ upload</button>
    </div>
    <input type="file" id="skl-file" accept=".md,.markdown,.txt" multiple style="display:none">`;
  rail.innerHTML = html;
  const f = $('skl-file'); if (f) f.onchange = _uploadFiles;
}

function _renderGrid(list) {
  const grid = $('skl-grid');
  if (!grid) return;
  if (!list.length) {
    grid.innerHTML = `<div class="skl-empty">${_state.q ? 'no matches' : 'nothing here yet'}</div>`;
    return;
  }
  // pinned first, then by score (server already score-sorted; pinned within installed)
  const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  grid.innerHTML = sorted.map(_card).join('');
  _bindCards(grid);   // defined in Task 2 (pin/delete/open); safe: defined before first real use
}

function _card(s) {
  // library cards (Task 4) carry .installed; installed-list rows carry .uses/.source/.pinned
  const badges = [
    s.uses ? `<span class="skl-badge" title="loaded ${s.uses}×">${s.uses}×</span>` : '',
    s.source ? '<span class="skl-badge git" title="git-backed">git</span>' : '',
  ].join('');
  return `
    <div class="skl-card${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-card-top">
        <span class="skl-card-name">${esc(s.name)}</span>
        ${badges}
      </div>
      <div class="skl-card-desc">${esc(s.description) || '<em>no description</em>'}</div>
    </div>`;
}

// stubs replaced in later tasks so Task 1 runs standalone
function _bindCards(root) {
  root.querySelectorAll('.skl-card').forEach(c => c.onclick = () => _openDrawer(c.dataset.slug));
}
function _openDrawer(slug) { /* Task 3 */ }
function _toggleLibrary() { /* Task 4 */ }
```

Also clean up the now-broken old helpers in the same pass (they reference functions Task 1
just deleted):
- **Delete** the old `_showLibrary` (lines ~164–187) — it calls the removed `_renderGrouped`
  and is fully superseded by `_toggleLibrary` (Task 4).
- **Keep** the old `_install` (~189–196) but change its trailing `_showLibrary()` call to
  `_refresh()`.
- In `_importGithub` and `_uploadFiles` (~198–221), change their trailing `_loadList('')`
  to `_refresh()`.
- Any remaining `_loadList(...)` call anywhere in the file (e.g. in `_togglePin`/`_save`/
  `_delete`/`_update`) → `_refresh()`. After this task `grep -n "_loadList\|_showLibrary\|_renderGrouped\|_groupRows\|_skillRow\|_editNew\|_open\b" static/js/skills.js` should return nothing except the new functions.

- [ ] **Step 4: Add the rail + grid + card CSS**

Append to `static/style.css` (near the existing `.skl-*` block ~line 2964):

```css
/* ── skills v2: header + category rail + card grid ── */
.skills2 { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.skl-head { display: flex; align-items: center; gap: 0.6rem; padding: 0 0 0.7rem; }
.skl-title { font-size: 1rem; color: var(--text); font-weight: 600; }
.skl-search { flex: 1; max-width: 360px; }
.skl-head .btn { flex-shrink: 0; }
.skl-body { display: flex; gap: 1rem; align-items: flex-start; flex: 1; min-height: 0; }
.skl-rail { width: 168px; flex-shrink: 0; display: flex; flex-direction: column; gap: 1px; }
.skl-rail-cat { display: flex; align-items: center; gap: 0.4rem; width: 100%; background: none;
  border: 0; border-left: 2px solid transparent; color: var(--muted); font: inherit;
  font-size: 0.74rem; text-align: left; padding: 0.28rem 0.5rem; cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s; }
.skl-rail-cat:hover { color: var(--text); background: var(--panel); }
.skl-rail-cat.active { color: var(--text); border-left-color: var(--accent); background: var(--panel); }
.skl-rail-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skl-rail-count { font-size: 0.62rem; color: var(--muted); }
.skl-rail-foot { display: flex; flex-direction: column; gap: 1px; margin-top: 0.6rem; padding-top: 0.5rem; border-top: 1px solid var(--faint); }
.skl-rail-act { background: none; border: 0; color: var(--muted); font: inherit; font-size: 0.72rem;
  text-align: left; padding: 0.28rem 0.5rem; cursor: pointer; transition: color 0.15s; }
.skl-rail-act:hover { color: var(--text); }
.skl-rail-act.active { color: var(--accent); }
.skl-grid { flex: 1; min-width: 0; display: grid; gap: 0.5rem; align-content: start;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); overflow-y: auto; }
.skl-card { position: relative; border: 1px solid var(--faint); border-radius: 3px; padding: 0.5rem 0.6rem;
  cursor: pointer; transition: border-color 0.15s cubic-bezier(0.2,0.7,0.2,1), background 0.15s; }
.skl-card:hover { border-color: var(--muted); background: var(--panel); }
.skl-card.active { border-color: var(--accent); background: var(--panel); }
.skl-card-top { display: flex; align-items: center; gap: 0.35rem; }
.skl-card-name { flex: 1; min-width: 0; font-size: 0.8rem; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skl-card-desc { font-size: 0.68rem; color: var(--muted); margin-top: 0.25rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.skl-badge { font-size: 0.58rem; color: var(--muted); border: 1px solid var(--faint); border-radius: 3px; padding: 0 0.25rem; flex-shrink: 0; }
.skl-badge.git { color: var(--accent); border-color: var(--accent); }
```

- [ ] **Step 5: Run the test, verify it passes**

Re-boot the harness server (fresh `.tmp_skl_redesign` so the library is seeded), run
`python tests/pw_skills_redesign.py 8151`. Expected: PASS all rows (rail, multicol grid,
filter). Also run `node --check static/js/skills.js`.

- [ ] **Step 6: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" \
  add static/js/skills.js static/style.css tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" \
  commit -m "skills: rail + card grid shell, category filter"
```

---

### Task 2: Card quick actions — pin (float to top) + delete (confirm)

Adds hover actions to each card so pinning and deleting don't need the editor. Pinned
cards float to the `pinned` rail group and to the top of the grid.

**Files:**
- Modify: `static/js/skills.js` (`_card`, `_bindCards`; add `_togglePin`, `_deleteCard`)
- Modify: `static/style.css` (card action styles)
- Test: `tests/pw_skills_redesign.py` (add assertions)

**Interfaces:**
- Consumes: `_card`, `_bindCards`, `_refresh`, `_state`, `_api`, `dlgConfirm`, `toast`
- Produces: `async function _togglePin(slug, pinned)`, `async function _deleteCard(slug)`

- [ ] **Step 1: Add failing assertions to the test**

Append inside `main()` before the `no_console_errors` line:

```python
        # back to all, then pin the first card -> it gets the 'pinned' state and a pinned rail row appears
        pg.eval_on_selector(".skl-rail-cat[data-cat='all']", "el => el.click()")
        pg.wait_for_timeout(200)
        first = pg.eval_on_selector("#skl-grid .skl-card .skl-card-name", "el => el.textContent")
        pg.eval_on_selector("#skl-grid .skl-card .skl-pin", "el => el.click()")
        pg.wait_for_timeout(400)
        r["pin_adds_rail_group"] = pg.eval_on_selector(
            ".skl-rail-cat[data-cat='pinned']", "el => !!el") or False
        r["pin_floats_top"] = pg.eval_on_selector(
            "#skl-grid .skl-card:first-child .skl-pin", "el => el.classList.contains('on')")
        # unpin to restore state for re-runnable tests
        pg.eval_on_selector("#skl-grid .skl-card:first-child .skl-pin", "el => el.click()")
        pg.wait_for_timeout(300)
```

- [ ] **Step 2: Run the test, verify the new rows fail**

Run the harness. Expected: `pin_adds_rail_group` / `pin_floats_top` FAIL (no `.skl-pin` yet).

- [ ] **Step 3: Extend `_card` and `_bindCards`, add handlers**

Replace `_card` and `_bindCards` (from Task 1) with:

```javascript
function _card(s) {
  const badges = [
    s.uses ? `<span class="skl-badge" title="loaded ${s.uses}×">${s.uses}×</span>` : '',
    s.source ? '<span class="skl-badge git" title="git-backed">git</span>' : '',
  ].join('');
  return `
    <div class="skl-card${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-card-top">
        <span class="skl-card-name">${esc(s.name)}</span>
        ${badges}
      </div>
      <div class="skl-card-desc">${esc(s.description) || '<em>no description</em>'}</div>
      <div class="skl-card-acts">
        <button class="skl-pin${s.pinned ? ' on' : ''}" data-act="pin" title="${s.pinned ? 'unpin' : 'pin to top'}">${s.pinned ? '★' : '☆'}</button>
        <button class="skl-del-q" data-act="del" title="delete">🗑</button>
      </div>
    </div>`;
}

function _bindCards(root) {
  root.querySelectorAll('.skl-card').forEach(c => {
    c.onclick = e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'pin') { e.stopPropagation(); _togglePin(c.dataset.slug, !e.target.classList.contains('on')); }
      else if (act === 'del') { e.stopPropagation(); _deleteCard(c.dataset.slug); }
      else _openDrawer(c.dataset.slug);
    };
  });
}

async function _togglePin(slug, pinned) {
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}/pin`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pinned }),
    });
    await _refresh();
  } catch { toast('pin failed', 'error'); }
}

async function _deleteCard(slug) {
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    if (_cur === slug) _closeDrawer?.();
    await _refresh();
  } catch { toast('delete failed', 'error'); }
}
```

The library cards (Task 4) override the acts row, so pin/delete only render for installed
mode — `_card` is called for both, so guard the acts with `_state.mode === 'installed'`:
wrap the `.skl-card-acts` div in `${_state.mode === 'installed' ? \`…\` : ''}`.

- [ ] **Step 4: Add card-action CSS**

Append to `static/style.css`:

```css
.skl-card-acts { position: absolute; top: 0.3rem; right: 0.35rem; display: flex; gap: 0.15rem;
  opacity: 0; transition: opacity 0.15s; }
.skl-card:hover .skl-card-acts, .skl-card .skl-pin.on { opacity: 1; }
.skl-pin, .skl-del-q { background: none; border: 0; cursor: pointer; font-size: 0.72rem; line-height: 1;
  color: var(--muted); padding: 0.1rem; }
.skl-pin:hover, .skl-del-q:hover { color: var(--text); }
.skl-pin.on { color: var(--accent); opacity: 1; }
.skl-del-q:hover { color: var(--error, #f87171); }
```

- [ ] **Step 5: Run the test, verify it passes**

Run the harness. Expected: PASS including `pin_adds_rail_group`, `pin_floats_top`.
`node --check static/js/skills.js`.

- [ ] **Step 6: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: per-card pin + delete on hover"
```

---

### Task 3: Editor drawer

Moves the name/description/when-to-use/body editor into a right slide-over drawer, opened
by clicking a card or `+ new`. Replaces the old `_editNew`/`_open`/`_save`/`_delete`/
`_export`/`_update` so they target drawer fields.

**Files:**
- Modify: `static/js/skills.js` (implement `_openDrawer`, add `_closeDrawer`, `_drawerHtml`, rewrite `_save`/`_delete`/`_export`/`_update` to read drawer fields; remove old `_editNew`/`_open`)
- Modify: `static/style.css` (drawer + backdrop)
- Test: `tests/pw_skills_redesign.py` (add assertions)

**Interfaces:**
- Consumes: `_api`, `esc`, `toast`, `dlgConfirm`, `_refresh`, `_cur`
- Produces: `async function _openDrawer(slug)` (slug null = new), `function _closeDrawer()`

- [ ] **Step 1: Add failing assertions**

Append in `main()`:

```python
        # open the first card -> drawer slides in, populated
        pg.eval_on_selector("#skl-grid .skl-card .skl-card-name", "el => el.click()")
        pg.wait_for_timeout(350)
        r["drawer_opens"] = pg.eval_on_selector("#skl-drawer", "el => !!el && el.classList.contains('open')")
        r["drawer_name_filled"] = pg.eval_on_selector("#skl-d-name", "el => el.value.length > 0")
        # esc closes
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        r["drawer_esc_closes"] = pg.eval_on_selector("#skl-drawer", "el => !el || !el.classList.contains('open')")
        # + new opens an empty drawer
        pg.eval_on_selector("#skl-new", "el => el.click()")
        pg.wait_for_timeout(300)
        r["new_drawer_empty"] = pg.eval_on_selector("#skl-d-name", "el => el.value === ''")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
```

- [ ] **Step 2: Run the test, verify the new rows fail**

Expected: `drawer_opens` etc. FAIL (`_openDrawer` is a stub).

- [ ] **Step 3: Implement the drawer**

Replace the Task 1 stub `function _openDrawer(slug) {}` and the old
`_editNew`/`_open`/`_save`/`_delete`/`_export`/`_update` (skills.js lines ~223–311) with:

```javascript
function _drawerHtml() {
  return `
    <div class="skl-drawer-backdrop" id="skl-drawer-bd"></div>
    <aside class="skl-drawer" id="skl-drawer">
      <div class="skl-drawer-head">
        <span id="skl-d-heading">new skill</span>
        <button class="skl-drawer-x" id="skl-d-close" title="close">✕</button>
      </div>
      <div class="skl-drawer-body">
        <div class="s-field"><label>name</label><input id="skl-d-name" class="settings-input" placeholder="e.g. PDF form filler"></div>
        <div class="s-field"><label>description</label><input id="skl-d-desc" class="settings-input" placeholder="one line — what it does"></div>
        <div class="s-field"><label>when to use</label><input id="skl-d-when" class="settings-input" placeholder="the trigger"></div>
        <div class="s-field"><label>procedure (markdown)</label><textarea id="skl-d-body" class="settings-textarea" rows="14"></textarea></div>
        <div class="skl-drawer-acts">
          <button class="btn primary" id="skl-d-save">save</button>
          <button class="btn" id="skl-d-export" style="display:none">export</button>
          <button class="btn" id="skl-d-update" style="display:none">update</button>
          <button class="btn danger" id="skl-d-del" style="display:none">delete</button>
          <span id="skl-d-status" class="skl-status"></span>
        </div>
        <div id="skl-d-source" class="skl-source" style="display:none"></div>
      </div>
    </aside>`;
}

async function _openDrawer(slug) {
  const host = $('skl-drawer-host');
  if (!host) return;
  if (!$('skl-drawer')) {
    host.innerHTML = _drawerHtml();
    $('skl-d-close').onclick = _closeDrawer;
    $('skl-drawer-bd').onclick = _closeDrawer;
    $('skl-d-save').onclick = _save;
    $('skl-d-export').onclick = _export;
    $('skl-d-update').onclick = _update;
    $('skl-d-del').onclick = _delete;
    document.addEventListener('keydown', _drawerEsc);
  }
  let s = { name: '', description: '', when_to_use: '', body: '', source: '' };
  if (slug) {
    try { s = await _api(`/api/skills/${encodeURIComponent(slug)}`); }
    catch { toast('failed to open skill', 'error'); return; }
  }
  _cur = slug || null;
  $('skl-d-heading').textContent = slug ? 'edit skill' : 'new skill';
  $('skl-d-name').value = s.name || '';
  $('skl-d-desc').value = s.description || '';
  $('skl-d-when').value = s.when_to_use || '';
  $('skl-d-body').value = s.body || '';
  $('skl-d-status').textContent = '';
  $('skl-d-del').style.display = slug ? '' : 'none';
  $('skl-d-export').style.display = slug ? '' : 'none';
  if (s.source) {
    $('skl-d-update').style.display = ''; $('skl-d-source').style.display = '';
    $('skl-d-source').innerHTML = `git-backed · <a href="${esc(s.source)}" target="_blank" rel="noopener">${esc(s.source)}</a>`;
  } else { $('skl-d-update').style.display = 'none'; $('skl-d-source').style.display = 'none'; }
  $('skl-drawer').classList.add('open');
  $('skl-drawer-bd').classList.add('open');
  document.querySelectorAll('.skl-card').forEach(c => c.classList.toggle('active', c.dataset.slug === slug));
  $('skl-d-name').focus();
}

function _closeDrawer() {
  $('skl-drawer')?.classList.remove('open');
  $('skl-drawer-bd')?.classList.remove('open');
  _cur = null;
  document.querySelectorAll('.skl-card.active').forEach(c => c.classList.remove('active'));
}
function _drawerEsc(e) { if (e.key === 'Escape' && $('skl-drawer')?.classList.contains('open')) _closeDrawer(); }

async function _save() {
  const name = $('skl-d-name').value.trim();
  if (!name) { toast('give the skill a name', 'error'); return; }
  const payload = { name, description: $('skl-d-desc').value.trim(), when_to_use: $('skl-d-when').value.trim(), body: $('skl-d-body').value };
  try {
    const res = _cur
      ? await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    _cur = res.slug;
    $('skl-d-del').style.display = ''; $('skl-d-export').style.display = '';
    $('skl-d-heading').textContent = 'edit skill';
    $('skl-d-status').textContent = 'saved';
    setTimeout(() => { if ($('skl-d-status')) $('skl-d-status').textContent = ''; }, 1500);
    toast('skill saved', 'success');
    await _refresh();
  } catch (e) { toast('save failed: ' + e.message, 'error'); }
}

async function _delete() {
  if (!_cur) return;
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    _closeDrawer();
    await _refresh();
  } catch { toast('delete failed', 'error'); }
}

function _export() {
  if (!_cur) return;
  const a = document.createElement('a');
  a.href = `/api/skills/${encodeURIComponent(_cur)}/export`;
  a.download = `${_cur}.SKILL.md`;
  document.body.appendChild(a); a.click(); a.remove();
}

async function _update() {
  if (!_cur) return;
  toast('updating from source…');
  try {
    const r = await _api(`/api/skills/${encodeURIComponent(_cur)}/update`, { method: 'POST' });
    toast(r.updated ? 'updated from source' : 'no source to update from', r.updated ? 'success' : '');
    if (r.updated) { _openDrawer(_cur); await _refresh(); }
  } catch (e) { toast('update failed: ' + e.message, 'error'); }
}
```

Remove the now-dead `_editNew` references in `initSkills` (Task 1 already dropped the call).

- [ ] **Step 4: Add drawer CSS**

```css
.skl-drawer-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); opacity: 0;
  pointer-events: none; transition: opacity 0.2s cubic-bezier(0.2,0.7,0.2,1); z-index: 60; }
.skl-drawer-backdrop.open { opacity: 1; pointer-events: auto; }
.skl-drawer { position: fixed; top: 0; right: 0; height: 100%; width: 480px; max-width: 92vw;
  background: var(--bg); border-left: 1px solid var(--faint); z-index: 61; display: flex; flex-direction: column;
  transform: translateX(100%); transition: transform 0.22s cubic-bezier(0.2,0.7,0.2,1); }
.skl-drawer.open { transform: translateX(0); }
.skl-drawer-head { display: flex; align-items: center; justify-content: space-between;
  padding: 0.8rem 1rem; border-bottom: 1px solid var(--faint); font-size: 0.84rem; color: var(--text); }
.skl-drawer-x { background: none; border: 0; color: var(--muted); cursor: pointer; font-size: 0.9rem; }
.skl-drawer-x:hover { color: var(--text); }
.skl-drawer-body { padding: 1rem; overflow-y: auto; display: flex; flex-direction: column; gap: 0.7rem; }
.skl-drawer-acts { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.3rem; }
```

- [ ] **Step 5: Run the test, verify it passes**

Expected: PASS including `drawer_opens`, `drawer_name_filled`, `drawer_esc_closes`,
`new_drawer_empty`. `node --check static/js/skills.js`.

- [ ] **Step 6: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: editor moves into a slide-over drawer"
```

---

### Task 4: Library mode

Implements `_toggleLibrary`: switches `_state.mode` to `library`, renders catalog cards
with `+ add` / `✓ added`, the same rail filters the catalog, and `add all` installs the
remaining. Returning to a category or `all` while in library mode stays in library; an
explicit toggle of `⊕ library` returns to installed.

**Files:**
- Modify: `static/js/skills.js` (implement `_toggleLibrary`; extend `_card` for library mode; `_install` already exists from Task 1 and already refreshes via `_refresh`)
- Modify: `static/style.css` (add button + added state)
- Test: `tests/pw_skills_redesign.py`

**Interfaces:**
- Consumes: `_state`, `_refresh`, `_render`, `_api`, `toast`, `_card`, `_install` (already defined)
- Produces: `function _toggleLibrary()`

- [ ] **Step 1: Add failing assertions**

```python
        # enter library: cards show +add buttons, rail label flips to 'library'
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(500)
        r["library_active"] = pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.classList.contains('active')")
        r["library_has_add"] = pg.eval_on_selector_all("#skl-grid .skl-add", "els => els.length") > 0 \
            or pg.eval_on_selector_all("#skl-grid .skl-added", "els => els.length") > 0
        # adding a not-installed skill flips it to added
        add_before = pg.eval_on_selector_all("#skl-grid .skl-add", "els => els.length")
        if add_before:
            pg.eval_on_selector("#skl-grid .skl-add", "el => el.click()")
            pg.wait_for_timeout(700)
            add_after = pg.eval_on_selector_all("#skl-grid .skl-add", "els => els.length")
            r["add_installs"] = add_after == add_before - 1
        else:
            r["add_installs"] = True  # everything already installed in this seed
        # back to installed
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(400)
        r["library_toggle_back"] = not pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.classList.contains('active')")
```

- [ ] **Step 2: Run the test, verify it fails**

Expected: `library_active`/`library_has_add` FAIL (`_toggleLibrary` is a stub).

- [ ] **Step 3: Implement library mode**

Replace the Task 1 stub `function _toggleLibrary() {}` with:

```javascript
function _toggleLibrary() {
  _state.mode = _state.mode === 'library' ? 'installed' : 'library';
  _state.cat = 'all';
  _state.q = '';
  if ($('skl-search')) $('skl-search').value = '';
  _refresh();
}
```

`_install` already exists (kept from Task 1, refreshing via `_refresh`); confirm it reads:

```javascript
async function _install(slugs) {
  if (!slugs.length) return;
  try {
    const r = await _api('/api/skills/install', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ slugs }) });
    toast(`added ${r.installed} skill${r.installed === 1 ? '' : 's'}`, 'success');
    await _refresh();
  } catch { toast('install failed', 'error'); }
}
```

Extend `_card` so library cards show add/added instead of pin/delete. Replace the acts
block in `_card`:

```javascript
  const acts = _state.mode === 'library'
    ? (s.installed
        ? '<span class="skl-added" title="installed">✓ added</span>'
        : `<button class="skl-add" data-act="add" data-slug="${esc(s.slug)}">+ add</button>`)
    : `<div class="skl-card-acts">
         <button class="skl-pin${s.pinned ? ' on' : ''}" data-act="pin" title="${s.pinned ? 'unpin' : 'pin to top'}">${s.pinned ? '★' : '☆'}</button>
         <button class="skl-del-q" data-act="del" title="delete">🗑</button>
       </div>`;
```

and put `${acts}` after the desc line in the returned card template. Library cards are not
clickable to edit (they're not installed), so in `_bindCards` add:

```javascript
      if (act === 'add') { e.stopPropagation(); _install([c.dataset.slug]); return; }
      if (_state.mode === 'library') return;   // library cards: only the add button acts
```

(place these two lines at the top of the `c.onclick` handler body).

Add an `add all` control to the grid header in library mode — prepend inside `_renderGrid`
when `_state.mode === 'library'`:

```javascript
  let head = '';
  if (_state.mode === 'library') {
    const remaining = _data.filter(c => !c.installed).length;
    head = `<div class="skl-lib-bar">library · ${_data.length}${remaining ? ` · <button class="btn skl-addall">add all (${remaining})</button>` : ' · all added ✓'}</div>`;
  }
  grid.innerHTML = head + sorted.map(_card).join('');
  if (_state.mode === 'library') grid.querySelector('.skl-addall')?.addEventListener('click', () => _install(_data.filter(c => !c.installed).map(c => c.slug)));
```

(the `.skl-lib-bar` spans the grid — give it `grid-column: 1 / -1`.)

Finally, update the existing `_importGithub` and `_uploadFiles` (skills.js ~198–221):
their trailing `_loadList('...')` calls must become `_refresh()`.

- [ ] **Step 4: Add library CSS**

```css
.skl-lib-bar { grid-column: 1 / -1; font-size: 0.7rem; color: var(--muted); padding: 0 0 0.2rem; }
.skl-lib-bar .btn { font-size: 0.64rem; padding: 0.12rem 0.5rem; margin-left: 0.3rem; }
.skl-add { background: none; border: 1px solid var(--accent); color: var(--accent); border-radius: 3px;
  font: inherit; font-size: 0.66rem; padding: 0.1rem 0.45rem; cursor: pointer; position: absolute; top: 0.4rem; right: 0.4rem; }
.skl-add:hover { background: color-mix(in srgb, var(--accent) 14%, transparent); }
.skl-added { position: absolute; top: 0.45rem; right: 0.5rem; font-size: 0.62rem; color: var(--signal, #4ade80); }
```

- [ ] **Step 5: Run the test, verify it passes**

Expected: PASS all (run against a fresh `.tmp_skl_redesign` so the catalog has
not-installed items; note: `seed_library` installs everything on first boot, so for the
`add_installs` row to exercise a real add, delete one skill first or accept the
"already installed" branch). `node --check static/js/skills.js`.

- [ ] **Step 6: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: library as a mode of the same surface"
```

---

### Task 5: Search

Search is already wired in Task 1 (`_state.q` + `_visible()` filter + the `?q=` fetch for
installed mode). This task verifies it and makes search show a flat result set with a
"results" rail state, and confirms it works in both modes.

**Files:**
- Modify: `static/js/skills.js` (`_render`/`_renderRail` — show a "results (N)" affordance when `q` is set; `_visible` already filters)
- Test: `tests/pw_skills_redesign.py`

**Interfaces:**
- Consumes: `_state`, `_visible`, `_renderRail`, `_renderGrid`

- [ ] **Step 1: Add failing assertion**

```python
        # search narrows the grid
        pg.eval_on_selector("#skl-search", "el => { el.value=''; }")
        pg.eval_on_selector(".skl-rail-cat[data-cat='all']", "el => el.click()")
        pg.wait_for_timeout(200)
        all_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        pg.fill("#skl-search", "summar")
        pg.wait_for_timeout(400)
        srch_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        r["search_narrows"] = srch_n < all_n and srch_n >= 1
        pg.fill("#skl-search", "")
        pg.wait_for_timeout(400)
```

- [ ] **Step 2: Run the test, verify the search row's behavior**

If Task 1's `_visible` + `?q=` already make this pass, note it; if `search_narrows` FAILS
(e.g. installed mode refetches with `?q=` but `_visible` double-filters fine), debug.
Expected before the refinement: likely PASS for installed mode. Proceed to make the rail
reflect search.

- [ ] **Step 3: Reflect search in the rail**

In `_render`, when `_state.q` is set, force the grid to show all matches regardless of
`cat` and mark the rail. Update `_render`:

```javascript
function _render() {
  const counts = _catCounts(_data);
  _renderRail(counts);
  _renderGrid(_visible());
}
```

and in `_renderRail`, when `_state.q`, add a non-clickable results row at top:

```javascript
  let html = '';
  if (_state.q) html += `<div class="skl-rail-results">results · ${_visible().length}</div>`;
```

(`_visible()` is cheap; called once more here.) Add minimal CSS:

```css
.skl-rail-results { font-size: 0.66rem; color: var(--accent); padding: 0.28rem 0.5rem; }
```

When searching, `_visible()` ignores `cat` only if you also relax the cat filter. Update
`_visible` so a non-empty `q` ignores the category (search is global):

```javascript
function _visible() {
  const ql = _state.q.toLowerCase();
  return _data.filter(s => {
    if (ql) return (`${s.name} ${s.description} ${s.when_to_use || ''}`).toLowerCase().includes(ql);
    if (_state.cat === 'pinned') return !!s.pinned;
    if (_state.cat !== 'all') return _catOf(s) === _state.cat;
    return true;
  });
}
```

- [ ] **Step 4: Run the test, verify it passes**

Expected: PASS `search_narrows`. `node --check static/js/skills.js`.

- [ ] **Step 5: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: global search across name/desc/when-to-use"
```

---

### Task 6: Responsive, dead-CSS cleanup, SW bump, full sweep

Makes the rail collapse to a chip bar and the drawer go full-screen on narrow viewports,
removes the now-unused old skills CSS, bumps the cache version, and runs the whole test.

**Files:**
- Modify: `static/style.css` (media query; delete `.skills-wrap/.skills-side/.skills-main/.skl-list/.skl-row*/.skl-import-row/.skl-lib-head/.skl-lib-row/.skl-group*` rules that the rewrite no longer uses — verify with grep first)
- Modify: `static/sw.js` (`VERSION` v89→v90, `STAMP` 115→116), `static/index.html` (`_v` 115→116, `style.css?v=` 115→116)
- Test: `tests/pw_skills_redesign.py` (add a narrow-viewport check)

**Interfaces:** none new.

- [ ] **Step 1: Add a narrow-viewport assertion**

```python
        # narrow viewport: rail becomes a horizontal chip bar (cards still render)
        pg.set_viewport_size({"width": 560, "height": 900})
        pg.wait_for_timeout(300)
        r["mobile_rail_is_row"] = pg.eval_on_selector(
            "#skl-rail", "el => getComputedStyle(el).flexDirection === 'row'")
        r["mobile_cards_render"] = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length") > 0
```

- [ ] **Step 2: Run the test, verify the new rows fail**

Expected: `mobile_rail_is_row` FAIL (rail is column at all widths).

- [ ] **Step 3: Add the media query + retire old CSS**

Append:

```css
@media (max-width: 720px) {
  .skl-body { flex-direction: column; }
  .skl-rail { width: 100%; flex-direction: row; flex-wrap: nowrap; overflow-x: auto; gap: 0.3rem; padding-bottom: 0.3rem; }
  .skl-rail-foot { flex-direction: row; margin-top: 0; padding-top: 0; border-top: 0; border-left: 1px solid var(--faint); padding-left: 0.4rem; }
  .skl-rail-cat { border-left: 0; border-bottom: 2px solid transparent; white-space: nowrap; }
  .skl-rail-cat.active { border-left: 0; border-bottom-color: var(--accent); }
  .skl-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .skl-drawer { width: 100%; max-width: 100%; }
}
```

Then grep to confirm the old classes are unreferenced and delete their rules:

Run: `grep -rn "skills-wrap\|skills-side\|skills-main\|skl-list\|skl-row\|skl-group\|skl-import-row\|skl-lib-head\|skl-lib-row" static/js static/index.html`
Expected: no JS/HTML references (all gone after the rewrite). Delete the matching CSS
rules in `static/style.css` (the block around the old 2964–3005 lines and the `.skl-group*`
lines added earlier).

- [ ] **Step 4: Bump the cache version**

- `static/sw.js`: `const VERSION = 'v90';` (comment: `skills ui redesign`), `const STAMP = '116';`
- `static/index.html`: `const _v = '116';` and `<link rel="stylesheet" href="/static/style.css?v=116">`

- [ ] **Step 5: Run the full test, verify all pass**

Boot fresh harness, `python tests/pw_skills_redesign.py 8151`. Expected: every row PASS,
`no_console_errors` PASS. `node --check static/js/skills.js` and `node --check static/sw.js`.

- [ ] **Step 6: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css static/sw.js static/index.html tests/pw_skills_redesign.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: responsive rail + drawer, drop old list css, bump cache"
```

---

## Notes for the implementer
- Restart any running server to see changes only matters for backend; this is all static
  files, so a browser hard-reload (or the SW bump in Task 6) suffices.
- The seed installs the whole library on first boot, so on a fresh `.tmp_skl_redesign` the
  library view may show everything as `✓ added`. To exercise `+ add` in Task 4, delete one
  installed skill via the UI (or `rm -rf data/skills/<slug>` is NOT valid since SKILLS_DIR
  is the real `data/skills` — instead delete through the running app) before re-checking.
- Keep `_catOf`, `_CAT_LABEL`, `_CAT_ORDER` exactly as they are — they already match the
  backend category stems (verified).
