# Skill Library Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the skills library source-first — the library lists sources (the built-in catalog + curated GitHub repos), each browseable, with every skill clickable to a read-only preview before adding.

**Architecture:** Backend gets a bundled `skill_sources.json` registry + a `skill_sources.py` service (reusing `skills_github` to fetch/scan repos, with a short in-memory browse cache) exposed via 3 routes. Frontend reworks the library half of `static/js/skills.js` so the rail lists sources and a preview drawer opens on card click; adding reuses the existing `install`/`import-github` endpoints.

**Tech Stack:** FastAPI (python), vanilla ES modules, `httpx` (already used by `skills_github`), Playwright (python sync) for tests.

## Global Constraints

- Commits: author name `jxherc`, email `houjx0103@gmail.com`; message all lowercase; no AI attribution. Use `git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit`.
- Public GitHub only (no tokens), matching `skills_github`. Browse results cached ~600s in memory.
- No "add all" for GitHub sources; per-skill add only. Built-in keeps `install`; GitHub uses `import-github`.
- Adding reuses existing endpoints — no new install path. `POST /api/skills/import-github {url}` and `POST /api/skills/install {slugs}` already exist.
- Route ordering: the new `/sources*` routes MUST be registered BEFORE the existing `@router.get("/{slug}")` (line ~92) or `/sources` gets captured as a slug.
- No em-dashes in any new content/strings (use `-`), per house style.
- `skills.js` changes → bump the cache stamp at the end (`sw.js` VERSION+STAMP, `index.html` `_v` + `style.css?v=`), kept in sync.
- kokuen styling: greyscale, tiny text, 1px borders, `--accent` for active/interactive, `--signal` for `✓ added`, easing `cubic-bezier(0.2,0.7,0.2,1)`.

**Test harness (Tasks 2-4):** boot a server (data dir is shared real `data/skills`, so keep tests non-destructive), SW blocked:
```bash
ALLES_DATA=.tmp_srcv AUTH_ENABLED=false PORT=8153 python app.py > .tmp_srcv.log 2>&1 &
# poll curl http://127.0.0.1:8153/ , then: python tests/<file>.py 8153 , then taskkill the PID
```
Skills view: `http://aide.localhost:8153/` then `window._navigateTo('skills')`. Context MUST use `service_workers="block"`.

---

### Task 1: Backend — sources registry, service, routes

**Files:**
- Create: `services/skill_sources.json`
- Create: `services/skill_sources.py`
- Create: `tests/test_skill_sources.py`
- Modify: `routes/skills.py` (add 3 routes after the `/catalog` route, before `/{slug}`)

**Interfaces:**
- Produces:
  - `skill_sources.list_sources() -> list[dict]` items `{id, name, kind('builtin'|'github'), description, count}`
  - `skill_sources.browse(id) -> dict` — builtin: `{"kind":"builtin","skills":[catalog items]}`; github: `{"kind":"github","repo_url":str,"skills":[{"name","path","import_url"}]}`
  - `skill_sources.preview(id, path) -> {name, description, when_to_use, body, source_url}`
  - `skill_sources._blob_url(owner, repo, branch, path) -> str` (pure, unit-tested)
  - routes: `GET /api/skills/sources`, `GET /api/skills/sources/{sid}/browse`, `GET /api/skills/sources/{sid}/preview?path=`

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_sources.py`:

```python
"""unit-ish checks for skill_sources that need no network."""
import sys
from services import skill_sources as ss

def main():
    r = {}
    srcs = ss.list_sources()
    ids = [s["id"] for s in srcs]
    r["builtin_first"] = bool(srcs) and srcs[0]["id"] == "builtin" and srcs[0]["kind"] == "builtin"
    r["has_github_sources"] = {"anthropic", "superpowers", "composio", "daymade"}.issubset(set(ids))
    r["builtin_has_count"] = srcs[0]["count"] > 0
    # builtin browse needs no network
    b = ss.browse("builtin")
    r["builtin_browse"] = b["kind"] == "builtin" and len(b["skills"]) > 0 and "body" in b["skills"][0]
    # pure url builder
    r["blob_url"] = ss._blob_url("o", "r", "main", "a/b/SKILL.md") == "https://github.com/o/r/blob/main/a/b/SKILL.md"
    # unknown source
    try:
        ss.browse("nope"); r["unknown_raises"] = False
    except ValueError:
        r["unknown_raises"] = True
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python tests/test_skill_sources.py`
Expected: FAIL/ImportError — `services/skill_sources.py` doesn't exist yet.

- [ ] **Step 3: Create the registry**

Create `services/skill_sources.json`:

```json
[
  {"id": "anthropic", "name": "anthropic/skills", "url": "https://github.com/anthropics/skills", "branch": "main", "description": "official anthropic agent skills - documents, mcp, creative, enterprise", "count": 18},
  {"id": "superpowers", "name": "superpowers", "url": "https://github.com/obra/superpowers", "branch": "main", "description": "workflow skills - tdd, debugging, brainstorming, planning, code review", "count": 14},
  {"id": "composio", "name": "composio collection", "url": "https://github.com/ComposioHQ/awesome-claude-skills", "branch": "master", "description": "huge community collection across every domain", "count": 864},
  {"id": "daymade", "name": "daymade marketplace", "url": "https://github.com/daymade/claude-code-skills", "branch": "main", "description": "curated production-ready dev-workflow skills", "count": 64}
]
```

- [ ] **Step 4: Create the service**

Create `services/skill_sources.py`:

```python
"""curated, browseable skill sources for the library. the bundled catalog is the implicit
first source ('builtin', local, always available); the rest are public github repos scanned
for SKILL.md (reusing skills_github). browse results cache briefly so an 800-skill repo is
one tree fetch, not 800."""
import json
import time
from pathlib import Path

from . import skills_github, skills_store

_FILE = Path(__file__).parent / "skill_sources.json"
_TTL = 600
_cache = {}   # id -> (ts, browse dict)


def _registry() -> list[dict]:
    try:
        d = json.loads(_FILE.read_text("utf-8"))
        return [s for s in d if isinstance(s, dict) and s.get("id") and s.get("url")]
    except Exception:
        return []


def list_sources() -> list[dict]:
    from . import skills_catalog
    out = [{"id": "builtin", "name": "built-in", "kind": "builtin",
            "description": "the bundled skill library", "count": len(skills_catalog.items())}]
    for s in _registry():
        out.append({"id": s["id"], "name": s["name"], "kind": "github",
                    "description": s.get("description", ""), "count": s.get("count", 0)})
    return out


def _get(sid):
    if sid == "builtin":
        return {"id": "builtin", "kind": "builtin"}
    for s in _registry():
        if s["id"] == sid:
            return {**s, "kind": "github"}
    return None


def _blob_url(owner, repo, branch, path):
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"


def _pretty(path):
    folder = skills_github._folder(path) or path
    return folder.replace("-", " ").replace("_", " ").strip()


def _owner_repo_branch(src):
    owner, repo, _b, _p, _k = skills_github._parse_url(src["url"])
    branch = src.get("branch") or skills_github._default_branch(owner, repo)
    return owner, repo, branch


def browse(sid) -> dict:
    src = _get(sid)
    if not src:
        raise ValueError("unknown source")
    if src["kind"] == "builtin":
        from . import skills_catalog
        return {"kind": "builtin", "skills": skills_catalog.items()}
    hit = _cache.get(sid)
    if hit and (time.time() - hit[0]) < _TTL:
        return hit[1]
    owner, repo, branch = _owner_repo_branch(src)
    paths = skills_github._skill_paths(owner, repo, branch)
    skills = [{"name": _pretty(p), "path": p, "import_url": _blob_url(owner, repo, branch, p)}
              for p in sorted(paths)]
    data = {"kind": "github", "repo_url": src["url"], "skills": skills}
    _cache[sid] = (time.time(), data)
    return data


def preview(sid, path) -> dict:
    src = _get(sid)
    if not src or src["kind"] != "github":
        raise ValueError("not a github source")
    owner, repo, branch = _owner_repo_branch(src)
    text = skills_github._fetch(owner, repo, branch, path)
    parsed = skills_store._parse(text)
    m = parsed["meta"]
    return {"name": m.get("name", _pretty(path)), "description": m.get("description", ""),
            "when_to_use": m.get("when_to_use", ""), "body": parsed["body"],
            "source_url": _blob_url(owner, repo, branch, path)}
```

- [ ] **Step 5: Add the routes**

In `routes/skills.py`, immediately AFTER the `catalog()` function (line ~29) and BEFORE `class InstallBody`, insert:

```python
@router.get("/sources")
def sources():
    from services import skill_sources
    return skill_sources.list_sources()


@router.get("/sources/{sid}/browse")
def browse_source(sid: str):
    from services import skill_sources
    try:
        data = skill_sources.browse(sid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"couldn't reach this source: {e}")
    if data.get("kind") == "builtin":
        have = {s["slug"] for s in skills_store.list_skills()}
        data["skills"] = [{**it, "installed": it["slug"] in have} for it in data["skills"]]
    return data


@router.get("/sources/{sid}/preview")
def preview_source(sid: str, path: str):
    from services import skill_sources
    try:
        return skill_sources.preview(sid, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"couldn't fetch skill: {e}")
```

- [ ] **Step 6: Run the test + syntax checks, verify pass**

Run: `python tests/test_skill_sources.py` → Expected: all PASS.
Run: `python -m py_compile services/skill_sources.py routes/skills.py` → Expected: clean.
Smoke the live path manually (best-effort, needs network): `python -c "from services import skill_sources as s; b=s.browse('anthropic'); print(b['kind'], len(b['skills']), b['skills'][0])"` → expect kind github, ~18 skills, each with name/path/import_url. If offline, skip.

- [ ] **Step 7: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add services/skill_sources.json services/skill_sources.py routes/skills.py tests/test_skill_sources.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: backend for browseable library sources"
```

---

### Task 2: Frontend — library becomes source-first (rail = sources, grid = selected source)

Reworks the library half of `skills.js`: state gains `source`; the rail lists sources in library mode; the grid shows the selected source's skills. Preview/add wiring lands in Task 3 (here, library cards render but clicking the body is a no-op stub).

**Files:**
- Modify: `static/js/skills.js`
- Modify: `static/style.css` (source-card styles reuse existing `.skl-card`; add `.skl-card-path`)
- Test: `tests/pw_skills_sources.py` (create)

**Interfaces:**
- Consumes: `_api`, `esc`, `$`, `_CAT_LABEL`, `_CAT_ORDER`, `_catOf`, `_catCounts`, `toast`, existing `_install`, `_importGithub`, `_uploadFiles`, `_openDrawer`, `_togglePin`, `_deleteCard`.
- Produces (used by Task 3): module vars `_sources`, `_state.source`; `_browseSource(id)`; `_libCard(s)`, `_srcCard(s)`; `_previewLibrary(card)` (stub here, real in Task 3); `_addFromLibrary(card)`.

- [ ] **Step 1: Write the failing test**

Create `tests/pw_skills_sources.py`:

```python
"""behavioral verify for library skill sources. data/skills is the real shared dir,
so this is read-mostly. github sources are network-live (best-effort)."""
import sys
from playwright.sync_api import sync_playwright

IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8153"
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and not any(x in m.text for x in IGN) else None)
        pg.goto(f"http://aide.localhost:{port}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("body", "() => window._navigateTo('skills')")
        pg.wait_for_selector("#skl-rail", timeout=12000)
        pg.wait_for_timeout(300)

        # enter library -> rail lists sources incl built-in
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(700)
        src_ids = pg.eval_on_selector_all(".skl-rail-cat", "els => els.map(e => e.dataset.src).filter(Boolean)")
        r["rail_lists_sources"] = "builtin" in src_ids and len(src_ids) >= 3
        # built-in grid renders catalog cards
        r["builtin_cards"] = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length") > 5

        # clicking a github source row triggers a browse (cards OR an inline error, both fine)
        gh = [s for s in src_ids if s != "builtin"]
        if gh:
            pg.eval_on_selector(f".skl-rail-cat[data-src='{gh[0]}']", "el => el.click()")
            pg.wait_for_timeout(2500)
            r["github_browse_resolves"] = pg.eval_on_selector(
                "#skl-grid", "el => el.querySelectorAll('.skl-card').length > 0 || el.querySelector('.skl-empty') !== null")
        else:
            r["github_browse_resolves"] = False

        r["no_console_errors"] = len(errs) == 0
        b.close()
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs: print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Boot the harness, run it, verify it fails**

Boot server (port 8153), `python tests/pw_skills_sources.py 8153`.
Expected: FAIL — `.skl-rail-cat[data-src]` rows don't exist yet (library rail still shows categories).

- [ ] **Step 3: Add state + source vars**

In `skills.js`, change the state line to add `source`, and add `_sources`:

```javascript
let _state = { mode: 'installed', cat: 'all', q: '', source: null };
let _data = [];
let _sources = [];
```

- [ ] **Step 4: Rework `_toggleLibrary`, add `_browseSource`, route `_refresh`**

Replace the existing `_toggleLibrary` and `_refresh` with:

```javascript
async function _toggleLibrary() {
  if (_state.mode === 'library') {
    _state.mode = 'installed'; _state.cat = 'all'; _state.q = ''; _state.source = null;
    if ($('skl-search')) $('skl-search').value = '';
    _refresh(); return;
  }
  _state.mode = 'library'; _state.q = '';
  if ($('skl-search')) $('skl-search').value = '';
  try { _sources = await _api('/api/skills/sources'); }
  catch { _sources = [{ id: 'builtin', name: 'built-in', kind: 'builtin', count: 0 }]; }
  _browseSource('builtin');
}

async function _browseSource(id) {
  _state.source = id;
  _renderRail();
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  let data;
  try { data = await _api(`/api/skills/sources/${encodeURIComponent(id)}/browse`); }
  catch { if (grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">couldn\\'t reach this source</div>'; return; }
  _data = data.skills || [];
  _render();
}

async function _refresh() {
  if (_state.mode === 'library') return _browseSource(_state.source || 'builtin');
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  try { _data = await _api('/api/skills' + (_state.q ? `?q=${encodeURIComponent(_state.q)}` : '')); }
  catch { if (grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>'; return; }
  _render();
}
```

- [ ] **Step 5: Make `_render`/`_renderRail` source-aware**

Replace `_render` and `_renderRail` with (note `_render` no longer passes counts; `_renderRail` computes per mode):

```javascript
function _render() {
  _renderRail();
  _renderGrid(_visible());
}

function _renderRail() {
  const rail = $('skl-rail');
  if (!rail) return;
  let html = '';
  if (_state.mode === 'library') {
    for (const s of _sources) {
      const active = s.id === _state.source;
      html += `<button class="skl-rail-cat${active ? ' active' : ''}" data-src="${esc(s.id)}">
          <span class="skl-rail-label">${esc(s.name)}</span><span class="skl-rail-count">${s.count || ''}</span>
        </button>`;
    }
  } else {
    const counts = _catCounts(_data);
    const row = (key, label) => counts[key]
      ? `<button class="skl-rail-cat${_state.cat === key ? ' active' : ''}" data-cat="${key}">
           <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
         </button>` : '';
    if (_state.q) html += `<div class="skl-rail-results">results · ${_visible().length}</div>`;
    if (counts.pinned) html += row('pinned', 'pinned');
    html += row('all', 'all');
    for (const k of _CAT_ORDER) if (k !== 'custom') html += row(k, _CAT_LABEL[k]);
    html += row('custom', 'custom');
  }
  html += `<div class="skl-rail-foot">
      <button class="skl-rail-act${_state.mode === 'library' ? ' active' : ''}" data-act="library">⊕ library</button>
      <button class="skl-rail-act" data-act="github">↳ github</button>
      <button class="skl-rail-act" data-act="upload">↑ upload</button>
    </div>
    <input type="file" id="skl-file" accept=".md,.markdown,.txt" multiple style="display:none">`;
  rail.innerHTML = html;
  const f = $('skl-file'); if (f) f.onchange = _uploadFiles;
}
```

- [ ] **Step 6: Make `_visible` + `_renderGrid` + cards source-aware; update the rail click handler**

Replace `_visible`, `_renderGrid`, and `_bindCards`, and ADD `_libCard`/`_srcCard`/`_addFromLibrary`/`_previewLibrary` with the code below. Leave the existing `_card` as-is — after this change the library renders with `_libCard`/`_srcCard`, so `_card`'s `_state.mode === 'library'` branch simply becomes unreachable dead code (harmless; the existing `_renderGrid` library bar / `skl-addall` code is removed because `_renderGrid` is fully replaced here):

```javascript
function _visible() {
  const ql = _state.q.toLowerCase();
  if (_state.mode === 'library') {
    if (!ql) return _data;
    return _data.filter(s => (`${s.name || ''} ${s.description || ''} ${s.when_to_use || ''}`).toLowerCase().includes(ql));
  }
  return _data.filter(s => {
    if (ql) return (`${s.name} ${s.description} ${s.when_to_use || ''}`).toLowerCase().includes(ql);
    if (_state.cat === 'pinned') return !!s.pinned;
    if (_state.cat !== 'all') return _catOf(s) === _state.cat;
    return true;
  });
}

const _libCard = s => `
  <div class="skl-card" data-slug="${esc(s.slug)}" data-kind="builtin">
    <div class="skl-card-top"><span class="skl-card-name">${esc(s.name)}</span></div>
    <div class="skl-card-desc">${esc(s.description) || ''}</div>
    ${s.installed ? '<span class="skl-added">✓ added</span>' : '<button class="skl-add" data-act="add">+ add</button>'}
  </div>`;

const _srcCard = s => `
  <div class="skl-card" data-path="${esc(s.path)}" data-url="${esc(s.import_url)}" data-kind="github">
    <div class="skl-card-top"><span class="skl-card-name">${esc(s.name)}</span></div>
    <div class="skl-card-desc skl-card-path">${esc(s.path)}</div>
    <button class="skl-add" data-act="add">+ add</button>
  </div>`;

function _renderGrid(list) {
  const grid = $('skl-grid');
  if (!grid) return;
  if (!list.length) { grid.innerHTML = `<div class="skl-empty">${_state.q ? 'no matches' : 'nothing here'}</div>`; return; }
  if (_state.mode === 'library') {
    grid.innerHTML = list.map(_state.source === 'builtin' ? _libCard : _srcCard).join('');
  } else {
    const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
    grid.innerHTML = sorted.map(_card).join('');
  }
  _bindCards(grid);
}

function _bindCards(root) {
  root.querySelectorAll('.skl-card').forEach(c => {
    c.onclick = e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (_state.mode === 'library') {
        if (act === 'add') { e.stopPropagation(); _addFromLibrary(c); return; }
        _previewLibrary(c);
        return;
      }
      if (act === 'pin') { e.stopPropagation(); _togglePin(c.dataset.slug, !e.target.classList.contains('on')); }
      else if (act === 'del') { e.stopPropagation(); _deleteCard(c.dataset.slug); }
      else _openDrawer(c.dataset.slug);
    };
  });
}

async function _addFromLibrary(c) {
  if (c.dataset.kind === 'builtin') { await _install([c.dataset.slug]); return; }
  try {
    await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: c.dataset.url }) });
    toast('added', 'success');
    _browseSource(_state.source);
  } catch { toast('add failed', 'error'); }
}

function _previewLibrary(c) { /* Task 3 */ }
```

Then in `initSkills`, update the rail click handler to handle `data-src`:

```javascript
    $('skl-rail').addEventListener('click', e => {
      const cat = e.target.closest('.skl-rail-cat');
      if (cat) {
        if (cat.dataset.src) { _state.q = ''; if ($('skl-search')) $('skl-search').value = ''; _browseSource(cat.dataset.src); return; }
        _state.cat = cat.dataset.cat; _render(); return;
      }
      const act = e.target.closest('.skl-rail-act')?.dataset.act;
      if (act === 'library') _toggleLibrary();
      else if (act === 'github') _importGithub();
      else if (act === 'upload') $('skl-file')?.click();
    });
```

Also delete the now-unused old `_card` library branch / `_renderGrid` library bar / `_install`-driven `_showLibrary` remnants if any remain (grep `skl-addall`, `skl-lib-bar` — remove their code; CSS for them can stay unused or be removed in Task 4).

- [ ] **Step 7: Add minimal CSS**

Append to `static/style.css`:

```css
.skl-card-path { font-family: var(--mono, monospace); font-size: 0.6rem; opacity: 0.7; }
```

- [ ] **Step 8: Run the test, verify pass**

`node --check static/js/skills.js`; reboot harness; `python tests/pw_skills_sources.py 8153`.
Expected: `rail_lists_sources`, `builtin_cards`, `github_browse_resolves`, `no_console_errors` PASS. (`_previewLibrary` stub is fine — Task 2 doesn't test preview.)

- [ ] **Step 9: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_sources.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: library rail lists sources, grid browses the selected one"
```

---

### Task 3: Frontend — clickable preview drawer + add from preview

Implements `_previewLibrary` and a read-only preview drawer, fixing "can't click into library skills" for both built-in and GitHub sources, and wiring add from the preview.

**Files:**
- Modify: `static/js/skills.js` (`_previewLibrary`, add `_openPreview`; make `_openDrawer` rebuild-safe; share the keydown listener)
- Modify: `static/style.css` (preview drawer bits)
- Test: `tests/pw_skills_sources.py` (add preview assertions)

**Interfaces:**
- Consumes: `_api`, `esc`, `$`, `_state`, `_data`, `_install`, `_browseSource`, `_closeDrawer`, `_drawerEsc`, `toast`.
- Produces: `_openPreview(s, opts)`, real `_previewLibrary(card)`.

- [ ] **Step 1: Add failing assertions**

Append inside `main()` of `tests/pw_skills_sources.py`, before `no_console_errors`:

```python
        # back to built-in, click a card -> preview drawer with a body
        pg.eval_on_selector(".skl-rail-cat[data-src='builtin']", "el => el.click()")
        pg.wait_for_timeout(500)
        pg.eval_on_selector("#skl-grid .skl-card .skl-card-name", "el => el.click()")
        pg.wait_for_timeout(400)
        r["preview_opens"] = pg.eval_on_selector("#skl-drawer", "el => !!el && el.classList.contains('open')")
        r["preview_has_body"] = pg.eval_on_selector("#skl-drawer .skl-pv-body", "el => !!el && el.textContent.trim().length > 0")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        r["preview_esc_closes"] = pg.eval_on_selector("#skl-drawer", "el => !el || !el.classList.contains('open')")
```

- [ ] **Step 2: Run it, verify the new rows fail**

`python tests/pw_skills_sources.py 8153` → `preview_opens` FAIL (`_previewLibrary` is a stub).

- [ ] **Step 3: Make `_openDrawer` rebuild-safe + share the keydown listener**

The preview and editor drawers share `#skl-drawer-host`. Change `_openDrawer` so it ALWAYS rebuilds the host (so a leftover preview can't block it), and have both manage one keydown listener. Replace the top of `_openDrawer` (the `if (!$('skl-drawer')) { ... }` guard block) with an unconditional build:

```javascript
async function _openDrawer(slug) {
  const host = $('skl-drawer-host');
  if (!host) return;
  host.innerHTML = _drawerHtml();
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;
  $('skl-d-save').onclick = _save;
  $('skl-d-export').onclick = _export;
  $('skl-d-update').onclick = _update;
  $('skl-d-del').onclick = _delete;
  document.removeEventListener('keydown', _drawerEsc);
  document.addEventListener('keydown', _drawerEsc);
  // ... the rest of _openDrawer (fetch skill, populate fields, add .open) stays unchanged ...
```

(Everything from `let s = { name: ... }` downward in `_openDrawer` is unchanged.)

- [ ] **Step 4: Implement `_openPreview` + `_previewLibrary`**

Replace the `_previewLibrary` stub with:

```javascript
function _previewLibrary(c) {
  if (c.dataset.kind === 'builtin') {
    const s = _data.find(x => x.slug === c.dataset.slug);
    if (s) _openPreview(s, { builtin: true, slug: s.slug, installed: !!s.installed });
    return;
  }
  _api(`/api/skills/sources/${encodeURIComponent(_state.source)}/preview?path=${encodeURIComponent(c.dataset.path)}`)
    .then(s => _openPreview(s, { builtin: false, url: c.dataset.url }))
    .catch(() => toast("couldn't fetch skill", 'error'));
}

function _openPreview(s, opts) {
  const host = $('skl-drawer-host');
  if (!host) return;
  const addCtl = opts.installed
    ? '<span class="skl-added">✓ added</span>'
    : '<button class="btn primary" id="skl-pv-add">+ add</button>';
  const srcLink = s.source_url ? `<a class="skl-pv-src" href="${esc(s.source_url)}" target="_blank" rel="noopener">view source</a>` : '';
  host.innerHTML = `
    <div class="skl-drawer-backdrop open" id="skl-drawer-bd"></div>
    <aside class="skl-drawer open" id="skl-drawer">
      <div class="skl-drawer-head"><span>${esc(s.name)}</span><button class="skl-drawer-x" id="skl-d-close">✕</button></div>
      <div class="skl-drawer-body">
        ${s.when_to_use ? `<div class="skl-pv-when"><b>when:</b> ${esc(s.when_to_use)}</div>` : ''}
        ${s.description ? `<div class="skl-pv-desc">${esc(s.description)}</div>` : ''}
        <pre class="skl-pv-body">${esc(s.body || '')}</pre>
        <div class="skl-drawer-acts">${addCtl}${srcLink}</div>
      </div>
    </aside>`;
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;
  document.removeEventListener('keydown', _drawerEsc);
  document.addEventListener('keydown', _drawerEsc);
  const add = $('skl-pv-add');
  if (add) add.onclick = async () => {
    add.disabled = true;
    if (opts.builtin) { await _install([opts.slug]); }
    else {
      try { await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: opts.url }) }); toast('added', 'success'); }
      catch { toast('add failed', 'error'); add.disabled = false; return; }
    }
    _closeDrawer();
    _browseSource(_state.source);
  };
}
```

- [ ] **Step 5: Add preview CSS**

Append to `static/style.css`:

```css
.skl-pv-when { font-size: 0.72rem; color: var(--muted); }
.skl-pv-desc { font-size: 0.78rem; color: var(--text); }
.skl-pv-body { white-space: pre-wrap; font-family: var(--mono, monospace); font-size: 0.72rem; color: var(--text); background: var(--panel); border: 1px solid var(--faint); border-radius: 3px; padding: 0.6rem; overflow-x: auto; margin: 0; }
.skl-pv-src { font-size: 0.7rem; color: var(--accent); text-decoration: none; }
.skl-pv-src:hover { text-decoration: underline; }
```

- [ ] **Step 6: Run the test, verify pass**

`node --check static/js/skills.js`; reboot harness; `python tests/pw_skills_sources.py 8153`.
Expected: `preview_opens`, `preview_has_body`, `preview_esc_closes` PASS along with Task 2's rows. Also manually confirm the installed-mode editor drawer still opens (click a card in installed mode) — the rebuild-safe change must not have broken it.

- [ ] **Step 7: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/js/skills.js static/style.css tests/pw_skills_sources.py
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "skills: click a library skill to preview it, add from the preview"
```

---

### Task 4: Cache bump + full sweep

**Files:**
- Modify: `static/sw.js` (`VERSION` v90→v91, `STAMP` 116→117), `static/index.html` (`_v` 116→117, `style.css?v=` 116→117)
- Verify: both playwright suites + the backend test.

**Interfaces:** none.

- [ ] **Step 1: Bump the cache version**

- `static/sw.js`: `const VERSION = 'v91';` (comment: `library sources + skill preview`), `const STAMP = '117';`
- `static/index.html`: `const _v = '117';` and `<link rel="stylesheet" href="/static/style.css?v=117">`

- [ ] **Step 2: Full verification**

Run, against a fresh harness server on 8153:
```bash
python tests/test_skill_sources.py
python tests/pw_skills_sources.py 8153
python tests/pw_skills_redesign.py 8153   # the earlier redesign suite must still pass
node --check static/js/skills.js && node --check static/sw.js
```
Expected: all suites PASS, no console errors.

- [ ] **Step 3: Commit**

```bash
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" add static/sw.js static/index.html
git -c user.name="jxherc" -c user.email="houjx0103@gmail.com" commit -m "sw: bump cache version for library sources + preview"
```

---

## Notes for the implementer
- `data/skills` is the real shared dir (SKILLS_DIR ignores ALLES_DATA); keep tests non-destructive. The built-in source has many NOT-installed skills (the ~180 recently added to the library but not installed), so `+ add` on a built-in card is exercisable; if a test adds one, delete it afterward to restore.
- GitHub browse/preview need network + are subject to the 60/hr unauthenticated rate limit; the ~600s cache and lazy preview keep calls low. Tests treat github as best-effort.
- Keep `_CAT_LABEL`/`_CAT_ORDER`/`_catOf` unchanged.
