# Afterlife Phase 1 — platform and security foundation

- **Status:** delivered
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
    waits for active credential writes, then retires unused keys. Backups authenticate encrypted
    credentials against the exact keyring they include.
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
- [x] Spike provider authentication before choosing supported flows.
  - Current OpenAI and Claude model APIs support API keys or workload identity, not a documented
    third-party consumer account flow. Their consumer subscriptions must not be presented as API quota.
  - Gemini documents OAuth through the owner's Google Cloud project, consent screen, client, and
    scopes. It is a possible later **Connect Google Cloud for Gemini** flow, not consumer-plan login.
  - Phase 1 therefore ships no provider OAuth button or token schema. API keys and local/custom
    endpoints remain available. [`provider-auth-spike.md`](../provider-auth-spike.md) records the
    sources, decision, warning, and proof required before any future provider login ships.
- [x] Add the localization foundation without translating unfinished UI.
  - General Settings stores a reviewed interface language, optional region, and optional IANA time
    zone. Invalid and unreviewed values fail with stable API errors; blank region/time zone follows
    the browser.
  - A shared browser helper provides message lookup, safe English fallback, interpolation, locale and
    text-direction resolution, and date/time formatting. The home clock and scheduled-message notice
    are the first consumers.
  - English remains the only claimed interface language. Later catalogs require their own review;
    unfinished screens are not machine-translated or presented as complete.
  - Fresh evidence: all 17 Settings API checks and all 99 JavaScript checks pass. Desktop keyboard and
    reduced-motion checks plus a 390×844 mobile check confirm save behavior, `en-TW`, `Asia/Taipei`,
    no horizontal overflow, and no console errors using isolated data.

### Safe document and file primitives

- [x] Add expected-hash Markdown writes, atomic replacement, and trash recovery.
  - [x] Vault reads return SHA-256 content hashes. Notes sends the hash it opened, and a stale save
    fails with `document_conflict` instead of overwriting an Obsidian or external edit.
  - [x] Vault Markdown, metadata, template, canvas, style, and asset writes use same-directory temp
    files, flush them, and atomically replace the destination without leaving temp files behind.
  - [x] Docs and Notes deletion moves files into the shared 30-day trash. Docs lists and restores
    deleted vault paths, while an occupied destination fails with `restore_conflict` instead of
    replacing the newer file.
  - Fresh evidence: 63 focused vault, Docs, Notes, route-contract, conflict, atomic-write, delete,
    and restore checks pass, together with all 99 JavaScript checks. Desktop keyboard/reduced-motion
    and 390×844 mobile browser checks restore a real document with no overflow or console errors.
- [x] Confine file operations to approved roots.
  - Agent file reads, listing, globbing, and search stay inside the selected Project plus explicitly
    approved extra folders. Extra folders begin read-only; only the selected Project is writable.
  - Diff previews, checkpoints, edits, patches, and reverts use the same guard, so a blocked write
    cannot quietly copy an outside file into run history. Temporary folders are no longer trusted by
    default.
  - Settings accepts at most 16 existing absolute folders, resolves aliases, rejects the filesystem
    root, and requires recent owner authentication when login is enabled.
  - Files and Vault operations resolve every requested path against their configured root. Traversal
    and symlinks that point outside fail closed.
  - Fresh evidence: 119 focused agent, Settings, Files, Vault, and trash checks pass, plus 196 broader
    agent/Project/session checks and all 99 JavaScript checks. Desktop keyboard/reduced-motion and
    390×844 mobile browser checks save a real approved root with no overflow or console errors.
- [x] Hash public-share passwords and rate-limit access attempts.
  - New protected shares use bcrypt over domain-separated password material. Passwords and hashes
    never appear in share API responses.
  - Migration 24 wraps every existing SHA-256 share hash in bcrypt without needing its plaintext.
    Old links remain usable and move to the current domain-separated format after the first correct
    password. Empty passwords still create open links, and overlong passwords fail before truncation.
  - Expiry values normalize to UTC before storage. Invalid or malformed dates fail closed instead of
    bypassing expiry through text comparison.
  - Passwords are submitted by POST instead of appearing in the URL. A successful unlock creates a
    one-hour, in-memory, HttpOnly, SameSite=Strict grant bound to that share and password version.
    Legacy upgrades use an atomic compare-and-swap, so concurrent password changes win. Revocation,
    expiry, and server restarts fail closed. Protected responses are not browser-cached.
  - Ten unlock attempts per client and share are allowed in five minutes. Further attempts return the
    stable `rate_limited` code and `Retry-After` header.
  - Fresh evidence: 118 focused share, folder, album, session, vault-share, route-contract, hashing,
    legacy-upgrade, cookie, revocation, expiry, and rate-limit checks pass. Desktop/reduced-motion and
    390×844 mobile browser checks open a real protected document with a clean URL, no overflow, and no
    page or console errors.

## 1B — Server foundation

- [x] Add read-only Overview, System, Services, Storage, Network, and Logs data.
  - Existing host, disk, and network stats now sit beside process/scheduler health, private logs,
    audit history, and owned-service status under authenticated System routes.
- [x] Keep server-host identity separate from browser identity.
  - System labels the host as **Server OS** and the current client as **This browser**. The stats API
    derives host identity only from the server runtime, never from request headers.
  - Crossed fixtures cover Darwin and Linux hosts with Windows, macOS, and Linux browser identities.
- [x] Complete the reverse-proxy decision report without changing the host or network.
  - [`proxy-decision.md`](../proxy-decision.md) compares native Caddy with Nginx Proxy Manager across
    HTTPS, streams, forwarded headers, certificates, ownership, ports, updates, backup, removal,
    rollback, native installs, and Compose.
  - Caddy is the proposed future managed default. Existing proxies stay external and read-only, and
    Phase 1 installs nothing or claims no privileged port.
- [x] Complete the AdGuard Home decision report without changing DNS.
  - [`adguard-decision.md`](../adguard-decision.md) checks the original linked video against current
    official guidance and records port 53, router/client DNS, authentication, ownership, updates,
    backup, failure isolation, removal, and rollback.
  - AdGuard remains optional and external. Phase 1 makes no DNS, DHCP, router, firewall, static-address,
    or privileged-port change.
- [x] Separate Alles-owned services from external services.
  - Only matching dual-marker records are owned. Invalid, changed, unavailable, and unregistered
    services receive no lifecycle actions.
- [x] Require recent owner authentication and typed actions for destructive controls.
- [x] Keep arbitrary shell, host shutdown, firewall, and unmanaged process controls out of Server.

## 1C — backup destinations

- [x] Re-validate the encrypted local destination against the disaster-recovery gate.
  - One canonical inventory covers all 12 encrypted database fields, 11 encrypted Settings fields,
    and the CalDAV, CardDAV, WebDAV backup, and S3-compatible credential fields. New backups reject plaintext
    credentials, corrupt or missing keys,
    unavailable key IDs, wrong field binding, changed ciphertext, and linked dependency files.
  - SQLite is snapshotted before DB-backed files are collected. The keyring, Settings, DAV configs,
    push key, recovery key, and Passwords attachment blobs are copied into immutable temporary files;
    backup validation, location policy, and the final archive use those exact copies. The encrypted
    container key must also match the frozen recovery key. Forced key-rotation and late-row races now
    produce a restorable archive instead of mixing two points in time.
  - Historical plaintext archives can still stage and migrate. Credential writes and rotation share a
    short consistency lock, so an in-flight write finishes before the old key is retired. Passwords
    attachment changes and full re-keying use that same lock, keeping the verifier, entry ciphertext,
    and attachment blobs on one password generation.
  - The independent gate creates a real encrypted database connector and a separate encrypted Settings
    key, keeps both out of raw SQLite/settings files, API output, logs, the plaintext ZIP, encrypted
    artifact, and exported recovery key, deletes the source install, then restores and decrypts both
    using only the clean release, backup repository, and separately saved recovery key.
  - Fresh evidence: 152 focused backup, API, cryptography, credential migration/rotation, staged restore,
    source-destruction, update rollback, race, symlink, corruption, and dependency checks pass.
- [x] Add encrypted WebDAV credentials and pass the same recovery gate.
  - The password is sealed and masked. Startup migrates plaintext config before any backup can run;
    key rotation and recovery snapshots include the WebDAV field with its exact purpose.
  - Only HTTPS collections are accepted. Each request passes the network guard, redirects and ambient
    proxies are disabled, responses are bounded, and remote error bodies are never returned.
  - Manual upload uses a unique temporary `PUT`, a no-overwrite `MOVE`, and an exact streamed `GET`
    read-back. Lost MOVE responses are reconciled by the same size and SHA-256 check.
  - Generated backups can be listed, downloaded, verified, and staged through the existing offline
    restore path. Disconnecting removes local credentials without deleting remote artifacts.
  - The disaster-recovery gate deletes the source install, reconnects with separately held WebDAV
    access, and restores every test credential using the separately saved recovery key.
  - Fresh evidence: 152 expanded Python backup, API, migration, rotation, update, and recovery checks
    pass, together with all 104 JavaScript checks. A live isolated browser pass covers the real status
    API, desktop, 390×844 mobile, keyboard file selection, reduced motion, and zero console/page errors.
- [x] Add encrypted S3-compatible credentials and pass the same recovery gate.
  - The access-key ID and secret key are sealed together with an exact field purpose, masked from API
    output, included in startup migration/key rotation, and frozen with the recovery snapshot.
  - The dependency-free client uses HTTPS, SigV4, blocked-address checks, no redirects or ambient
    proxies, bounded XML/responses, and path-style or virtual-hosted addressing against an existing bucket.
  - Manual upload conditionally writes a unique temporary object, conditionally copies it to a unique
    final name, reads the full encrypted object back to verify its size and SHA-256, and removes the
    temporary object. This first version uses single-request copy and caps artifacts at 5 GB.
  - Generated backups can be listed, downloaded atomically to private local staging, verified, and
    passed to the same offline restore flow. Disconnecting removes local credentials only.
  - The independent gate verifies real SigV4 requests, deletes the source install, reconnects using a
    separately held access-key pair, and restores every test credential with the separately saved
    recovery key.
  - Fresh evidence: all 3,874 Python tests pass with 4 skips, all 111 JavaScript tests pass, and the
    isolated live browser gate passes at desktop and 390×844 mobile widths with keyboard file choice,
    reduced motion, masked real API output, and zero console/server errors.
- [x] Spike Kopia only after the existing portable restore path remains proven.
  - Kopia 0.23.1 created an encrypted filesystem repository, rejected the wrong password, restored an
    exact artifact after source/client deletion, and handed it back to the existing staged restore path.
  - The second 12,605,916-byte encrypted backup added 12,607,022 repository bytes (`1.0001×`). Fresh
    outer encryption prevents meaningful cross-backup deduplication at this layer.
  - Alles therefore does not add a Kopia dependency or second recovery format. The portable encrypted
    manifest/staging archive remains the engine for local, WebDAV, and S3-compatible destinations.
  - [`kopia-spike.md`](../kopia-spike.md) records the command, checksum, evidence, limits, decision, and
    proof required before reconsidering it.

## Current slice

The current completed groups cover startup access policy, scoped owner/API access, stable security
errors, rate limits, encrypted connector credentials, private observability, owned-service controls,
live model catalogs and roles, trusted memory, real incognito isolation, provider-auth decisions,
safe Markdown writes, recoverable Vault trash, approved-root file confinement, public-share safety,
the revalidated encrypted local backup destination, and the manual encrypted WebDAV and S3-compatible
backup targets. System now separates server and browser identity, and the proxy, AdGuard, and Kopia
decisions are recorded with their safety and recovery limits.
They do not install or configure a reverse proxy or companion service for the owner, and they do not
expose unsupported provider account login.

Final evidence includes all 3,874 Python tests with 4 expected skips, all 112 JavaScript tests, the real
Kopia spike, and an isolated System browser pass at 1280×800 and 390×844. The browser pass confirms the
correct server OS, separate client identity, keyboard access, reduced motion, no horizontal overflow,
and zero console/page errors. Earlier slice-level evidence remains beside each checklist item.
