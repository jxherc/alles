# 10c — plugins via skills (git-backed, shareable): implementation + regression

## Audit
Skills CRUD + GitHub import + catalog/install already existed. Gaps: imported skills didn't record
their source (no update path), no update, no export.

## Built (strict TDD, ruff + node-check clean — no new lint errors)
- **10c-1 source/update/export** — `_serialize`/`_parse`/`upsert*`/`get_skill`/`list_skills` carry an
  optional `source:`; `import_from_github` stamps each skill's per-file `…/blob/<branch>/<path>` source;
  `export_md`/`export_all`; `update_from_source` re-pulls from the recorded source.
  `GET /api/skills/{slug}/export` (markdown download) + `POST /api/skills/{slug}/update`. 12 unit tests.
- **10c-2 frontend** — git badge on imported rows, Update (git-backed only) + Export actions, source link
  in the editor; existing github-import affordance surfaced. 8 Playwright assertions, 0 console errors.
  Stamps v73 / SW v47.

## Regression
16 subdomains 0 console errors (`docs/evidence/10c/regression/`). Full suite: 1633 tests OK.
