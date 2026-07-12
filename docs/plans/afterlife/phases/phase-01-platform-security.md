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
- [x] Add scoped, revocable API tokens.
  - New and migrated tokens default to read-only. Explicit scopes cover writes, models, agent runs,
    Passwords, connections, and administration; malformed scope records fail closed.
  - The one-time token value, scope selector, visible scope list, last-use time, and revocation remain
    available in Settings.
  - Fresh evidence: 20 focused token/migration/UI checks and the complete 26-history recovery matrix
    pass with migration 19.
  - Desktop 1280×800 and mobile 390×844 browser checks pass with keyboard focus, reduced motion,
    no overflow, a real scoped-token creation, and zero console/server errors. All 87 JavaScript tests
    pass after malformed Gallery envelopes were restored to the existing error contract.
- [x] Add recent-owner-auth checks.
  - Password login opens a ten-minute confirmation window. A throttled `/api/auth/reauth` refreshes
    it without creating another session, and admin bearer tokens cannot replace owner confirmation.
  - Backup/key export, restore staging/cancellation, token changes, connector changes, and MCP service
    changes require recent confirmation when authentication is enabled. Settings uses a real masked
    password dialog and retries the intended action once after success.
- [x] Add stable API error codes and rate limits for sensitive operations.
  - Security failures keep the existing human-readable `detail` and add stable codes such as
    `invalid_token`, `token_scope_denied`, `recent_auth_required`, and `rate_limited`.
  - A thread-safe, bounded sliding-window limiter protects each authenticated owner action per client
    and route. Rate-limit responses include `Retry-After`; login and reauthentication keep their
    stricter password-failure throttle.

### Secrets and observability

- [x] Encrypt connector and MCP credentials at rest, with rotation and migration.
  - Machine-local AES-GCM encryption now uses field-bound ciphertext and a versioned keyring.
    Existing plaintext and `enc1` model, mail, webhook, push, connection, settings, CalDAV,
    CardDAV, and MCP values migrate without losing data.
  - MCP environment values and HTTP headers are configured per server, masked in API responses,
    and encrypted on disk. Local MCP processes inherit only a small reviewed system environment;
    provider keys are never copied from Alles's ambient environment.
  - Owner-confirmed rotation keeps the previous key until every known credential is re-encrypted,
    then retires unused keys. Backups reject encrypted credentials when `secret.key` is missing.
  - Fresh evidence: all 3,683 non-matrix Python checks, all 90 JavaScript checks,
    desktop/mobile browser checks, and the complete 27-history migration matrix pass through
    migration 20.
- [x] Add structured redacted logs, health data, and audit records.
  - Process logs are JSON lines with an allowlist of structured fields. Common bearer tokens,
    provider keys, named secrets, URL credentials, query values, and SQL parameter blocks are
    masked before output.
  - Authenticated System endpoints expose structured logs, database/process/scheduler health,
    job lag and failure state, and a durable audit trail. Old unstructured log lines are never
    returned by the API.
  - State-changing API requests create content-free audit records with a route template, actor
    kind, result, and request ID. Request bodies, response bodies, prompts, vault data, and raw
    unmatched paths are not stored.
  - Fresh evidence: all 3,690 non-matrix Python checks pass in 868.574 seconds with four expected
    skips. All 28 recovery histories pass through migration 21 in 823.928 seconds, and the final
    38 focused observability, recovery, scheduler, event, migration, and route checks also pass.
- [x] Add a reviewed service-manager abstraction for Alles-owned services only.
  - launchd, systemd-user, and Compose use fixed argument lists with no shell strings. Manager
    subprocesses receive only a small reviewed environment and never inherit provider keys.
  - Private registry and service-root markers must match. The root, manager-specific identifier,
    service definition path, and definition hash are rechecked immediately before every status or
    control operation. Changed, missing, mismatched, or symlinked markers fail closed.
  - Read-only service status separates valid ownership from manager availability. Start, stop, and
    restart are the only controls; unmanaged processes, containers, and host controls are absent.
  - Controls require recent owner authentication, a typed action, a stable error code, and a
    dedicated audit record.
  - Fresh evidence: all 51 focused service-manager, System API, route, reauthentication, and scoped
    token checks pass in 18.937 seconds.

### Models, memory, and language

- [x] Add model roles, a resolver, provider adapters, and catalog reconciliation.
  - [x] Add OpenAI-compatible, Anthropic, Gemini, Ollama, and manual catalog adapters without a
    shipped guessed model list.
  - [x] Reconcile live, stale, unavailable, and manual catalogs independently per endpoint while
    preserving the last good catalog after a failed refresh.
  - [x] Add the three roles and shared resolver, then expose the effective choices in Settings.
  - Aide Chat, Andromeda, and Jarvis use one precedence path. Broken saved choices fail visibly;
    Andromeda's unconfigured fallback is local-first, and configured fallback stays inside the same
    privacy and cost class.
  - Settings exposes exact role choices, effective local/remote state, endpoint adapters, refresh
    state, manual model editing, and missing selections. Desktop and phone browser checks pass with
    no horizontal overflow, keyboard focus, reduced-motion coverage, and no console errors.
  - Fresh evidence: 122 focused resolver, catalog, chat/persona, research, Jarvis/proactive,
    Settings, routing, and route-contract checks pass, together with all 91 JavaScript checks.
- [x] Add memory provenance, policy controls, and real incognito isolation.
  - Ask is the default. Model-derived facts wait for owner review, Auto activates only direct
    low-risk preferences, and Off blocks model memory reads and writes.
  - Memory records show their source, trust, global or project scope, timestamps, and which chats
    used them. The owner can remember with undo, review, search, edit, move, pin, forget, export,
    pause, or clear them.
  - Incognito sessions and attachments live only in short-lived RAM. They never enter SQLite,
    files, the sidebar, browser URL history, or saved drafts; they read no long-term memory, reject
    background work, preserve temporary multi-turn context, and are deleted when the owner exits.
  - Desktop and 390×844 browser checks cover policy switching, remember/undo/edit, provenance,
    responsive layout, and console errors with no horizontal overflow.
  - Fresh evidence: 93 focused memory, incognito, chat, session, image, user-model, migration,
    routing, and compatibility checks pass, together with all 95 JavaScript checks. All 30
    supported database histories also pass the staged restore and repeat-migration gate.
- [ ] Spike provider authentication before choosing supported flows.
- [ ] Add the localization foundation without translating unfinished UI.

### Safe document and file primitives

- [ ] Add expected-hash Markdown writes, atomic replacement, and trash recovery.
- [ ] Confine file operations to approved roots.
- [ ] Hash public-share passwords and rate-limit access attempts.

## 1B — Server foundation

- [x] Add read-only Overview, System, Services, Storage, Network, and Logs data.
  - Existing host, disk, and network stats now sit beside process/scheduler health, private logs,
    audit history, and owned-service status under authenticated System routes.
- [x] Separate Alles-owned services from external services.
  - Only matching dual-marker records are owned. Invalid, changed, unavailable, and unregistered
    services receive no lifecycle actions.
- [x] Require recent owner authentication and typed actions for destructive controls.
- [x] Keep arbitrary shell, host shutdown, firewall, and unmanaged process controls out of Server.

## 1C — backup destinations

- [ ] Re-validate the encrypted local destination against the disaster-recovery gate.
- [ ] Add encrypted WebDAV credentials and pass the same recovery gate.
- [ ] Add encrypted S3-compatible credentials and pass the same recovery gate.
- [ ] Spike Kopia only after the existing portable restore path remains proven.

## Current slice

The current completed groups cover startup access policy, scoped owner/API access, stable security
errors, rate limits, encrypted connector credentials, private observability, owned-service controls,
and the live model-catalog backend. They do not install or configure a reverse proxy or companion
service for the owner.

Fresh evidence: 12 focused startup-policy tests pass. Broader verification is recorded with the commit.
The CORS slice adds 5 parser cases plus live unknown-origin request and preflight checks.
The public-host slice adds complete public app boot coverage plus HTTP, host, subdomain, IPv6, proxy,
domain, and configured-origin cases.
