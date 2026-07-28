# Phase 8 Actual Budget core spike

- **Status:** architecture and refreshed production live gates passed
- **Date:** 2026-07-18
- **Pinned proof version:** `@actual-app/api`, `@actual-app/cli`, and
  `@actual-app/sync-server` 26.7.0
- **Runtime used:** Node 26.5.0; the official packages require Node 20 or 22 and newer

## Decision

Actual can remain the intended Finance core. The official Node API and official sync-server package
provide the required account, transaction, payee, category, budget, schedule, sync, and bank-sync
surfaces. A local bridge can own one loaded budget at a time, use integer minor units, and shut down
cleanly. The managed server can bind to loopback and keep all of its files under an Alles-owned data
directory.

The production boundary now uses this exact lock and official API. Alles owns the loopback service,
private bootstrap credential, serialized bridge, additive migration, parity report, canonical write
switch, cold backup/restore, exact app-plus-manifest rollback, and unchanged read-only legacy ledger.

## Official constraints

- Actual exposes an official Node package, not a REST API. Alles therefore needs a bounded local Node
  bridge rather than Python requests to an undocumented server endpoint.
- The client works on a local cached budget and syncs it to the server. The server is not a queryable
  canonical SQL ledger by itself.
- Actual amounts are integers in minor units. Existing Alles floats must be converted deterministically
  and checked for unsupported precision before cutover.
- `importTransactions` reconciles duplicates and honors `imported_id`; `addTransactions` does not.
- Bank sync requires `actual-server`. Provider tokens on that server are not covered by Actual's
  end-to-end budget encryption.
- The public 26.7.0 API exports no `exportBudget` function despite an older reference entry. Backup and
  restore must therefore use the managed server/cache files while stopped, with an independently
  verified Alles migration export. No undocumented Actual internals are part of the bridge contract.

Official references:

- [Actual Node API guide](https://actualbudget.org/docs/api/)
- [Actual API reference](https://actualbudget.org/docs/api/reference/)
- [Actual server CLI](https://actualbudget.org/docs/install/cli-tool/)
- [Actual server configuration](https://actualbudget.org/docs/config/)
- [Actual bank sync](https://actualbudget.org/docs/advanced/bank-sync/)

## Synthetic proof

The spike installed the pinned packages in `/tmp`, not in the repository or owner data. It started the
official server on `127.0.0.1:8973` with a throwaway data directory and confirmed `GET /health` returned
`{"status":"UP"}`.

Through the official API it then:

1. created an `alles-stage8-spike` budget;
2. created a `CIBC chequing` account with an opening balance of 123,456 minor units;
3. imported one -1,234 transaction with stable identity `cibc:demo:001`;
4. imported the exact same source row a second time;
5. observed one row added on the first pass, zero on the second, and a 122,222 balance;
6. synchronized the budget to the managed server.

The server was stopped. Its four managed files were copied with matching SHA-256 hashes to a fresh
throwaway restore root. A second server started on `127.0.0.1:8974`, and a fresh API cache downloaded
the budget by its group/sync ID. The restored client returned the same account ID, opening transaction,
imported transaction ID, imported source identity, note, and 122,222 balance.

The spike also found an important naming detail: the 26.7.0 API's `downloadBudget` resolves the public
budget `groupId` as the sync ID, not the `cloudFileId`. The production bridge must test and record this
against every pinned upgrade.

## Production gate implementation

- [x] package lock, license inventory, supported-runtime installation, and managed update/rollback;
- [x] one serialized bridge process with timeouts, structured errors, lifecycle ownership, and secret
  redaction;
- [x] exact mapping for accounts, transactions, transfer pairs, payees, categories, budget assignments,
  schedules, and subscriptions links;
- [x] additive original/base currency evidence and stable sidecar links;
- [x] refreshed synthetic and upgraded-ledger count, balance, and aggregate live parity;
- [x] failed post-bridge staging validation records the exact candidate identity, deletes it through
  the official API, verifies absence, and blocks/restages only after a failed cleanup is retried;
- [x] stopped-server backup plus staged restore and read-back;
- [x] one staged write cutover, no live dual write, and unchanged read-only Alles rows for one stable
  release;
- [x] rollback to the unchanged Alles ledger on any failed gate.
