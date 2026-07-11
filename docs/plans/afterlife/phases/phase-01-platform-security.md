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
  - `public` requires HTTPS, matching domain, trusted-host, and proxy checks.
  - Containers use a separate internal runtime marker; safe host-side publishing remains explicit.
- [x] Limit CORS to configured Alles web origins.
  - Cross-origin access is off by default. Exact HTTP/HTTPS origins can be configured; wildcard,
    credential-bearing, path, query, fragment, and blank entries fail closed.
  - Browser-extension access remains off until a separately reviewed pairing flow exists.
- [x] Add trusted-host and forwarded-proxy validation for public mode.
  - Public startup requires an exact HTTPS origin, an allow-list containing that host, and explicit
    proxy IP addresses/CIDRs. Wildcard hosts, wildcard proxy trust, and everywhere CIDRs fail closed.
  - Cleartext public HTTP and WebSocket traffic is rejected. Only a loopback `/health` request may
    remain cleartext for local container and service checks.
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

The first completed group covers startup access policy, CORS, HTTPS, trusted hosts, and forwarded proxy
trust. It does not install or configure a reverse proxy for the owner.

Fresh evidence: 12 focused startup-policy tests pass. Broader verification is recorded with the commit.
The CORS slice adds 5 parser cases plus live unknown-origin request and preflight checks.
The public-host slice adds complete public app boot coverage plus HTTP, host, subdomain, IPv6, proxy,
domain, and configured-origin cases.
