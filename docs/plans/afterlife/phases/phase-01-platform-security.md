# Afterlife Phase 1 — platform and security foundation

- **Status:** in progress
- **Parent design:** [`../design.md`](../design.md)
- **Checkbox rule:** `[x]` means implemented and freshly tested, not merely discussed.

Phase 1 is split into small gates. A later gate must not weaken an earlier one.

## 1A — shared safety foundation

### Access and network

- [x] Add startup access profiles.
  - `device` is the default and accepts loopback addresses only.
  - `lan` requires an enabled owner password before the server can bind beyond loopback.
  - `public` stays blocked until HTTPS, trusted-host, and proxy checks are implemented.
  - Containers use a separate internal runtime marker; safe host-side publishing remains explicit.
- [ ] Limit CORS to configured Alles origins and narrow extension flows.
- [ ] Add trusted-host and forwarded-proxy validation for public mode.
- [ ] Add scoped, revocable API tokens and recent-owner-auth checks.
- [ ] Add stable API error codes and rate limits for sensitive operations.

### Secrets and observability

- [ ] Encrypt connector and MCP credentials at rest, with rotation and migration.
- [ ] Add structured redacted logs, health data, and audit records.
- [ ] Add a reviewed service-manager abstraction for Alles-owned services only.

### Models, memory, and language

- [ ] Add model roles, a resolver, provider adapters, and catalog reconciliation.
- [ ] Add memory provenance, policy controls, and real incognito isolation.
- [ ] Spike provider authentication before choosing supported flows.
- [ ] Add the localization foundation without translating unfinished UI.

### Safe document and file primitives

- [ ] Add expected-hash Markdown writes, atomic replacement, and trash recovery.
- [ ] Confine file operations to approved roots.
- [ ] Hash public-share passwords and rate-limit access attempts.

## 1B — Server foundation

- [ ] Add read-only Overview, System, Services, Storage, Network, and Logs data.
- [ ] Separate Alles-owned services from external services.
- [ ] Require recent owner authentication and typed actions for destructive controls.
- [ ] Keep arbitrary shell, host shutdown, firewall, and unmanaged process controls out of Server.

## 1C — backup destinations

- [ ] Re-validate the encrypted local destination against the disaster-recovery gate.
- [ ] Add encrypted WebDAV credentials and pass the same recovery gate.
- [ ] Add encrypted S3-compatible credentials and pass the same recovery gate.
- [ ] Spike Kopia only after the existing portable restore path remains proven.

## Current slice

The first slice is startup access policy only. It does not claim that public hosting is ready.
Public mode must fail closed until the CORS, HTTPS, trusted-host, and proxy slice is delivered.

Fresh evidence: 12 focused startup-policy tests pass. Broader verification is recorded with the commit.
