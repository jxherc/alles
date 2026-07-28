# Phase 9 design review - distribution and browser access

## Problem

### 9A

The owner needs a normal macOS or Linux install that can be started, updated, recovered, and removed
without understanding Python environments or risking personal data. Today `alles install` only writes
a launcher, the first-run modal lives mostly in one browser's local storage, and packaged installs
cannot use the Git-only updater.

Successful ending: the launcher and supervised service use one verified versioned release; setup can
resume from another browser; an update either becomes healthy or restores the exact previous release
and data; uninstall removes only owned program files and keeps data.

### 9B

The old extension was correctly retired because it reused a vault-wide unlock token. The replacement
must fill one owner-selected login without giving a browser permanent vault or all-site access.

Successful ending: a named browser is paired in Passwords, remains locked after restart, can be
unlocked explicitly, sees only exact-site login metadata, receives only the selected credential, fills
only the reviewed top-level login form, and stops working immediately when locked or revoked.

## Decisions

### Versioned native runtime

Choice: install immutable release directories under the platform app-data root, one private virtual
environment per release, an atomic `current-release` pointer, and a small owned dispatcher used by the
launcher and user service.

Reason: dependency changes can be staged and rolled back with code. The live release is never edited
in place, and the service does not need a privileged system install.

Rejected: modifying system Python, running the service directly from an arbitrary checkout, or using a
mutable shared virtual environment. Each weakens rollback or ownership proof.

### Server-owned setup state

Choice: persist a versioned setup document after every completed step and keep incomplete form input
in the browser until save. Basics detects the region from the browser locale instead of asking the
owner to type a code; timezone remains visible for review. The server validates every path, locale,
access profile, and protection choice before advancing the durable step.

Reason: progress survives reload and can resume on another authenticated browser without storing raw
passwords or API-key drafts in setup state.

### Explicit Obsidian boundary

Choice: selecting an existing vault only records that path. Companion installation is a separate
explicit action and refuses to overwrite unowned plugin content.

Reason: a connected vault is owner data, not an Alles-managed program directory.

### Paired browser identity plus ephemeral unlock

Choice: store a SHA-256 hash of a random browser secret in SQLite. Pairing authenticates the browser,
but a separate random session token is minted only after Passwords is unlocked and the owner approves.
The session is held in server memory and `chrome.storage.session`, never in persistent extension
storage.

Reason: the browser can remain paired across restarts without remaining able to decrypt Passwords.
Revocation invalidates both the persistent device identity and every in-memory unlock.

Rejected: a pasted vault token, a scoped API token with a `secrets` scope, a permanent browser unlock,
or a session token in `chrome.storage.local`.

### Exact top-level origin

Choice: normalize and compare scheme, IDNA host, and effective port. Remote targets and remote Alles
servers require HTTPS. The extension injects only into frame 0 after `activeTab` is granted and sends
both the reviewed top-level origin and the executing frame origin.

Reason: suffix matching allows lookalikes, scheme-only host matching allows downgrade, and all-frame
injection can fill an unrelated embedded origin.

### Metadata then selected release

Choice: matching returns entry ID, name, and username. Plaintext is decrypted and returned only for
one selected ID that still matches the exact origin in the same unlocked session.

Reason: the popup can present a real choice without releasing every password for a site.

## Flow

### Native install and update

1. Resolve a supported platform layout and prove every destination is either absent or already owned.
2. Copy the source into a private staging release, create its virtual environment, install pinned
   dependencies, compile, and run an isolated health probe.
3. Atomically publish the release and dispatcher, write the service definition and launcher, register
   ownership, start the service, and open resumable setup.
4. For update, repeat staging, stop only the verified service, create an encrypted backup, switch the
   release pointer, start and health-check.
5. On any post-stop failure, restore the previous pointer and exact pre-update data, restart, and keep
   a durable recovery record until accepted or rolled back.
6. Uninstall stops and unregisters only the owned service, removes matching launcher/runtime files,
   and reports the preserved data path.

### Browser pair, unlock, fill, and revoke

1. The extension validates the Alles URL, requests permission for that exact origin, and creates a
   bounded pairing request with a short code and a client-held polling secret.
2. The owner opens Passwords, unlocks the desired vault, verifies the browser name and code, and
   approves or denies the request. Approval returns a narrow persistent browser secret, but the
   browser remains locked and receives no vault or fill session.
3. On a later locked session, the extension creates an unlock request and opens Passwords. Approval
   mints a new one-time browser session token.
4. On the active HTTPS tab, the popup requests exact-origin matches, the owner chooses one, and the
   server releases only that entry.
5. The extension injects into frame 0, rechecks the origin and login-form shape, fills username and
   password, and never submits.
6. Lock clears extension session storage and server memory. Idle/locked computer state does the same.
   Revoke also invalidates the persistent browser secret.

## UI and states

- Setup is one compact five-step blocking dialog with visible step names, a back path, `save and
  continue`, `finish setup`, and `exit setup`. Saved steps show `saved`; failed saves keep the current
  fields and show a local retry.
- Access and Vault placement use KOKUEN radio/switch controls, never native choice widgets. Exact paths
  remain visible before save.
- Obsidian detection is informational. The companion action stays separate and names what it will
  write.
- Passwords settings replaces the retired notice with Connected browsers, an extension download and
  load-unpacked guide, pending pair/unlock approvals, per-row `lock` and `revoke`, and local
  empty/error states.
- Pair/unlock approval is shown only after Passwords is unlocked. The browser name and request expiry
  are visible; approval and cancel are explicit.
- Extension popup states are disconnected, waiting for approval, locked, no matches, matches,
  fill-ready, filled, and recoverable error. No state is hidden behind animation.

## Responsive and accessibility

- Dialog content owns vertical scroll; actions remain reachable without covering fields.
- At 620px and below, action groups stack and every target is at least 44px.
- Dialogs trap and restore focus, Escape cancels when safe, and asynchronous status uses `aria-live`.
- Custom radio groups use arrow-key movement; switches expose `role=switch` and `aria-checked`.
- Extension credentials are real buttons with stable accessible names and keyboard selection.
- Reduced motion removes nonessential transitions; content is visible by default.

## Approval boundary

The owner explicitly directed Phase 9 to proceed without standalone mockups. This review records the
flow and design contract that will be applied directly to the real KOKUEN surfaces.
