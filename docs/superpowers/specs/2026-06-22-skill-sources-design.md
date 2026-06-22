# skill library sources — design

## context

After the skills redesign, the library (`⊕ library` in `static/js/skills.js`) shows only the
bundled 431-skill catalog (`/api/skills/catalog`), and library cards are **not clickable** —
you can only `+ add`, never see what a skill actually contains before adding. The app already
has `services/skills_github.py` (`import_from_github`) that scans any repo/folder/file URL for
`SKILL.md` files and imports them, recording a `source` url — but there's no notion of curated,
browseable **sources**.

## goals
- make library skills **clickable** → a read-only preview (name / when-to-use / full body) before adding.
- add a **sources** concept: the library opens with a list of sources; pick one to browse its skills.
- ship a few real, verified-popular sources, browsed **live** from GitHub.

## non-goals
- no auth/private repos (public only, as today).
- no "add all" for GitHub sources (864 skills at once isn't wanted — per-skill add only).
- no new install mechanism — adding reuses the existing `import-github` (github) / `install` (built-in).
- the bundled catalog's category browsing stays an **installed-list** feature; the library is source-first.

## sources (verified to contain importable SKILL.md files)
Bundled in `services/skill_sources.json`:

| id | name | url | branch | ~count |
|----|------|-----|--------|--------|
| anthropic | anthropic/skills | https://github.com/anthropics/skills | main | 18 |
| superpowers | superpowers | https://github.com/obra/superpowers | main | 14 |
| composio | composio collection | https://github.com/ComposioHQ/awesome-claude-skills | master | 864 |
| daymade | daymade marketplace | https://github.com/daymade/claude-code-skills | main | 64 |

`count` is the value verified at design time (shown as approximate). The **built-in** catalog is an
implicit first source (`id: builtin`, local, always available, no network).

## data model
`services/skill_sources.json` — a list of `{id, name, url, branch, description, count}`. Read-only
bundled file (parallels `services/skill_library/`). The built-in source is synthesized in code, not
in the file.

## backend — `services/skill_sources.py` + 3 routes

Reuses `skills_github` helpers (`_default_branch`, `_skill_paths`, `_fetch`) and `skills_store._parse`.

```
list_sources() -> [{id, name, description, kind, count}]
   # kind: 'builtin' | 'github'; built-in first, then the json entries

browse(id) -> dict
   # builtin: {"kind":"builtin", "skills": skills_catalog.items()}  (route adds installed flags)
   # github:  {"kind":"github", "repo_url": url,
   #           "skills": [{"name": <folder, prettified>, "path": <p>,
   #                       "import_url": "https://github.com/<owner>/<repo>/blob/<branch>/<p>"}]}
   # github tree is fetched once via _skill_paths and CACHED in-memory ~600s per id

preview(id, path) -> {name, description, when_to_use, body, source_url}
   # github only: _fetch the raw SKILL.md, parse frontmatter+body; source_url = the blob url
```

Routes (in `routes/skills.py`):
- `GET /api/skills/sources` → `list_sources()`.
- `GET /api/skills/sources/{id}/browse` → for builtin, mark each item `installed`; for github, the cached list. On fetch failure raise 502 (`couldn't reach this source`).
- `GET /api/skills/sources/{id}/preview?path=…` → `preview(id, path)`; 502 on fetch failure.
- **add** reuses existing endpoints: github → `POST /api/skills/import-github {url: import_url}`; built-in → `POST /api/skills/install {slugs:[slug]}`.

Errors: any github call wrapped; a source that 502s shows an inline error in the grid, the rest of
the UI keeps working. Built-in never hits the network.

## frontend — `static/js/skills.js` (library becomes source-first)

State adds `source` (`null` until library entered, then a source id). `_sources` caches the source
list for the rail.

- **`_toggleLibrary`**: enter library mode, fetch `/api/skills/sources` into `_sources`, default
  `source = 'builtin'`, browse it. Toggling off returns to installed.
- **rail** (`_renderRail`): in **installed** mode shows categories (unchanged); in **library** mode
  shows the **source list** (each row = source name + count, active = current), with the foot actions
  (`⊕ library` active → toggles back, `↳ github`, `↑ upload`). Clicking a source row browses it.
- **`_refresh`** (library): `GET /api/skills/sources/{source}/browse`, store rows in `_data`.
- **grid** (`_renderGrid`, library):
  - built-in source: catalog cards (name + description + `add`/`✓ added`), now **clickable → preview**.
  - github source: cards showing the skill name; `add` button; **clickable → preview** (lazy-fetches
    the SKILL.md). client-side search filters the loaded list.
- **preview drawer** (`_openPreview`): reuses `#skl-drawer-host` with a read-only layout — heading,
  when-to-use line, the body rendered as text, a link to the source (github), and an **add** button
  (or `✓ added`). Esc / backdrop / ✕ closes. This is what fixes "can't click into library skills."
- **card click wiring**: in library mode the card body opens the preview; the `add` button still adds
  directly without opening. (installed mode is unchanged: body → editor drawer, pin/delete on hover.)

The existing `↳ github` paste-a-URL import and `↑ upload` stay as-is.

## data flow (add from a github source)
browse → user clicks a card → `preview?path=` fetches the SKILL.md → drawer shows it → **add** posts
the card's `import_url` to `/api/skills/import-github` → installed into `data/skills/` with its
`source` recorded → toast → the card flips to `✓ added` (best-effort: re-mark by re-browsing installed).

## testing — `tests/pw_skills_sources.py` (playwright, SW blocked)
- library opens to a **rail of sources** (≥3 rows incl. `built-in`).
- built-in source: grid renders catalog cards; **clicking a card opens the preview drawer with a
  non-empty body**; Esc closes; `add` installs (use a NOT-installed catalog skill, then clean up by
  deleting it so the test is non-destructive — OR assert the `✓ added` flip only).
- a github source row renders; clicking it issues a browse call. GitHub browse is **network-live**, so
  assert the source row + that a browse either returns cards or shows the inline error — do not assert
  on live repo contents. Skipped cleanly when offline.
- no console errors.

## files touched
- create: `services/skill_sources.py`, `services/skill_sources.json`, `tests/pw_skills_sources.py`
- modify: `routes/skills.py` (3 routes), `static/js/skills.js` (library = sources + preview drawer),
  `static/style.css` (source rows + preview drawer), and the cache stamp (`sw.js` VERSION/STAMP +
  `index.html` `_v`) since `skills.js` changed.

## risks
- GitHub rate limits (unauthenticated, 60/hr/IP): mitigated by the ~600s browse cache and lazy
  per-skill preview. A rate-limit error shows the inline "couldn't reach this source" message.
- The built-in catalog in library mode is now flat (no category filter) — acceptable; category browse
  remains on the installed list, and search covers the library.
