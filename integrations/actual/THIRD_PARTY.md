# Actual bridge third-party inventory

The lockfile pins the official `@actual-app/api`, `@actual-app/cli`, and
`@actual-app/sync-server` packages to 26.7.0. The three published packages are MIT licensed. Their
complete transitive versions, registry integrity hashes, and published license metadata are retained
in `package-lock.json`.

- upstream: https://github.com/actualbudget/actual
- API documentation: https://actualbudget.org/docs/api/
- server documentation: https://actualbudget.org/docs/install/cli-tool/
- reviewed: 2026-07-18

Alles installs this lock into its private managed service directory. It does not run `npx`, float a
version range, or expose the sync server beyond loopback.
