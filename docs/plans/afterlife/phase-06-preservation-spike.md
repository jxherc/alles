# Phase 6 preservation spike

This spike uses only temporary folders created by the test suite. It never opens or writes the
owner's normal vault.

## Current paths

| Area | Current source | What exists now | Phase 6 gap |
| --- | --- | --- | --- |
| Docs | `routes/vault_md.py`, `services/vault_md.py`, `static/js/docs.js` | Markdown tree, read, search, tags, backlinks, create, rename, trash, restore, and an external-change stream | The shipped browser view is a reader, not the approved Visual/Source editor |
| Notes | `services/notes_vault.py` | Real files under `Notes/` with expected-hash writes; partial updates preserve unknown frontmatter, comments, order, line endings, and unrelated body bytes | The approved real Docs UI still needs to expose focused edits and conflicts |
| Journal | `services/journal_vault.py`, `services/journal_migration.py` | Optional daily-note mirror plus an explicit, private, restart-safe migration transaction for non-private and deliberately unlocked entries | The database remains authoritative until the approved Docs cutover; migration controls are not connected to the current UI |
| Watcher | `routes/vault_md.py`, `services/document_safety.py` | Nanosecond signatures and durable local-write markers classify local, external, and draft-conflicting changes across restart | The approved real UI still needs to present these states |
| Write | `services/vault_md.py`, `services/document_safety.py` | Path containment, expected hashes, atomic replacement, private drafts, exact revisions, comparison, and preserved conflict copies | The safety APIs intentionally remain disconnected from the current Docs reader until starter approval |
| Trash | `services/trash.py`, `routes/vault_md.py` | The registry is committed before moving bytes; move failure keeps the source, restore refuses overwrite, and missing trash bytes keep their row | The approved real UI still needs its final trash/recovery states |
| Backup | `routes/backup.py`, `services/backup_recovery.py`, `services/vault_transfer.py` | Restart-safe move/relink plus encrypted local/WebDAV/S3 recovery that captures configured external vaults and remaps them safely on restore | Real Settings controls wait for their own approved starter |

## Corpus

`tests/fixtures/markdown_preservation/` covers:

- nested and custom frontmatter;
- wiki links, heading links, aliases, embeds, and block identifiers;
- callouts, tables with escaped pipes, task lists, footnotes, HTML, comments, math, Mermaid, and
  nested code fences;
- unknown future directives and malformed/unclosed syntax.

The test creates additional throwaway files at runtime for UTF-8 BOM, CRLF line endings, no final
newline, invalid bytes, and a file larger than 2 MB.

## Proven boundary

Fresh command:

```text
python3 -m unittest tests.test_markdown_preservation tests.test_vault_md \
  tests.test_notes_vault tests.test_docs_reader

Ran 51 tests in 2.467s
OK
```

The focused preservation tests prove:

- read then expected-hash write with no edit is byte-for-byte identical for every valid UTF-8
  fixture, including BOM, CRLF, malformed syntax, unknown syntax, and the large file;
- a targeted text replacement changes only the requested bytes and leaves every other file exact;
- a stale save cannot replace a newer external edit;
- invalid UTF-8 is reported as read-only, never shown with replacement characters, and cannot be
  overwritten by write, task toggle, or link rewrite paths.

## Unsupported for editing

Invalid UTF-8 is intentionally unsupported. Alles returns the original hash and a clear error while
leaving the bytes untouched. The owner must convert or restore a UTF-8 copy outside the editor.

This spike proves a lossless full-source round trip. It does **not** approve a rich-text editor that
parses and serializes Markdown. Any Visual mode candidate must keep the exact source as the authority
and pass this same corpus before it can ship.

## Safe document foundation now proven

- stale saves preserve the live external file, local candidate, private draft, and exact conflict
  copies; successful saves create exact-byte revisions;
- rename/link transactions recover after a partial move or partial rewrite, roll back to every original
  byte, and stop instead of overwriting a newer external edit;
- watcher origin markers survive a fresh process and same-size edits are detected with nanosecond
  signatures;
- trash failure injection proves record and move failures keep the only source bytes, while restore
  conflicts preserve both the newer file and the trashed copy;
- vault move and relink preserve hidden Obsidian files, binary files, empty folders, and all hashes;
  they recover after restart, work without renaming the source across filesystems, keep the old vault
  by default, and require a separate exact confirmation before old-location deletion;
- no-space, permission, symlink, external-edit-during-copy, rollback, and encrypted backup/restore
  paths fail closed in throwaway roots;
- configured external vaults are included in encrypted local, WebDAV, and S3 recovery archives. On
  restore they are placed under the new Alles data root, never written back to the old external path.
- partial Notes updates change only explicitly managed fields or requested content. Unknown
  frontmatter, comments, key order, CRLF, trailing items, and unrelated body bytes remain exact;
- Journal migration uses a private stage, exact confirmation for unlocked private content, all-source
  preflight before the first write, expected hashes, restart recognition, and conservative rollback.
  It copies daily notes without silently changing the Journal database source of truth.

Fresh focused evidence includes:

```text
python3 -m unittest tests.test_backup_recovery tests.test_phase0_recovery_gate \
  tests.test_cli_safety tests.test_api_backup tests.test_recovery_crypto \
  tests.test_webdav_backup tests.test_s3_backup tests.test_api_webdav_backup \
  tests.test_api_s3_backup -v

Ran 131 tests in 14.050s
OK
```

## Still required

- clear owner approval of `docs/mockups/afterlife-navigation/docs.html`;
- implementation of that approved direction in the real Docs interface;
- Visual/Source interaction tests against the preservation corpus;
- unified Notes and non-private Journal navigation, approved Journal migration controls, and scoped
  Aide handoff. Legacy Docs, Notes, and Journal redirects are already covered by unit, host, and
  rendered-browser gates;
- real-interface desktop, mobile, keyboard, reduced-motion, offline, loading, empty, conflict, and
  error verification with isolated data.
