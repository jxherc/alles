# conventions

- Keep the FastAPI, SQLite/SQLAlchemy, vanilla JavaScript, and CSS architecture.
- Map every new route owner, interactive control root, CLI command, job, automation action, integration,
  PWA/extension function, and Aide tool in `features/registry.json`. Regenerate the catalog and acceptance
  matrix; never hand-edit the generated documents.
- `unchecked`, `blocked`, and `unavailable` are not passes. Record acceptance only after the named
  automated and real-computer scenarios have current evidence.
- Use a throwaway `ALLES_DATA` for every test that can read or write files.
- Preserve old Files URLs by resolving missing `location_id` to the default local location.
- Treat offline files as cache, not backup.
- Verify a transfer destination before deleting its source.
- Use custom KOKUEN controls. Do not ship native product menus, checkboxes, or radios.
- Keep unreviewed interface catalogs unavailable and visible as incomplete; never label English
  fallback as translation.
- Treat the Credits coverage result as authoritative. A readable partial manifest is not a complete
  release notice set.
- Specialist grouping composes existing records and APIs; navigation alone must never migrate or
  mutate their data.
- After Actual cutover, do not read frozen legacy transaction calculations or dual-write the ledger.
  Adapt a view to Actual or fail it closed until that work exists.
