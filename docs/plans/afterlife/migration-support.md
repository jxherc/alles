# Afterlife Phase 0 — migration support policy

- **Status:** implemented and verified
- **Rule:** support is based on proven historical schemas, not a guessed version number.

## Supported inputs

- Beta 0.1.0 at commit `0c61e9d`, with no `schema_migrations` table.
- The late legacy no-history schema at commit `2983f1f`.
- Every canonical migration prefix from version 1 through the current migration head.
- The known Photos fork prefixes from its version 9 through version 13 history.

Unknown migration names, duplicate versions, future versions, missing fork columns, and other mixed
histories are rejected before a migration changes the database.

## Known history repair

One old Photos branch used versions 9–13 for Photos work before the Notes and Mail migrations landed.
Alles recognizes only that exact name sequence and checks the matching Photos columns. It remaps:

| Old version | Old name | Canonical version |
| ---: | --- | ---: |
| 9 | `photo_archive` | 12 |
| 10 | `photo_perf` | 13 |
| 11 | `photo_stack` | 14 |
| 12 | `photo_clip` | 15 |
| 13 | `photo_faces` | 16 |

Canonical Notes versions 9–10 and Mail version 11 then run normally. The repair is transactional and
idempotent. An arbitrary mismatched history is never treated as this fork.

## Notes safety repair

- Beta notes get the later optional `tags`, `items`, and `due` columns before they are copied.
- The legacy `notes` table is dropped only after every row is proven present in Markdown.
- If that proof fails, migration 10 raises and remains pending.
- Databases carrying the older false-success marker are rewound through Notes versions 9–10 and checked
  again.

## Required fixture gate

For every supported input:

1. Build or load the secret-free synthetic database.
2. Put it in a legacy backup with known Vault, Files, and Photos sentinel hashes.
3. Stage the restore without touching live data.
4. Boot and migrate the staged copy twice.
5. Boot it once more after the prepared snapshot is sealed.
6. Require the exact canonical history, current tables/columns, SQLite integrity, stable IDs/counts,
   migrated Notes, Mail fields, Photos fields, and unchanged file hashes.

Frozen SQL fixtures carry their source commit and expected table/column counts. No real user database or
private content is used.

Fresh evidence: all 25 supported histories passed this flow in 128.261 seconds: two released no-history
schemas, every canonical prefix 1–18, and every known Photos-fork prefix 9–13.
