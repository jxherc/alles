# engineering decisions

## Visible-before-motion runtime invariant

Decision

Choice: entrance motion may change position, but its first frame must keep content fully opaque.
Dynamic overlays may still use explicit hidden/display lifecycle state, but no text, control, empty
state, or workbench may depend on an opacity animation reaching its final frame to become readable.

Reason: a paused, throttled, unsupported, or missed entrance animation must never turn a valid Alles
surface into an empty region. The final rendered audit found legacy Home and shared `rise`/`fade-in`
keyframes that violated the documented KOKUEN rule even though ordinary runs completed the animation.

Alternatives considered: keep opacity-zero entrances with reduced-motion exceptions, rely on JavaScript
to add a ready class, or treat successful screenshots as proof that the animation always completes.

Consequences: entrance keyframes preserve opacity from their first frame; Home and streamed content are
visible without animation; source contracts reject opacity-zero entrances; rendered gates remain the
authority for clipping, overlap, and target geometry.

## Exact offline module generations

Decision

Choice: derive the PWA precache manifest from every exact versioned static import used by the delivered
HTML and JavaScript graph, and advance the service-worker cache identity whenever that graph changes.
Do not make cache lookup ignore URL search parameters.

Reason: the real cold-offline gate proved that caching only queryless file paths leaves versioned ES
module imports unavailable after installation. Ignoring search parameters would make mixed generations
appear equivalent and could execute stale modules against current markup.

Alternatives considered: cache only the entry module, use queryless cache matching, remove all module
versions, or treat a warm browser session as offline proof.

Consequences: `/api/pwa/precache` owns an exact dependency graph, the offline gate must start from a
cold installed profile, and version drift or an uncached import fails visibly instead of silently mixing
application generations.

## Executable interaction logic map

Decision

Choice: keep `features/registry.json` authoritative for shipped function surfaces and annotate every
registered feature with event authority, controls, state transitions, success, failure, recovery,
keyboard, focus, repeat handling, evidence, and external acceptance gaps. Generate both JSON and
readable Markdown from that source plus the shared 14-state KOKUEN contract.

Reason: a prose-only inventory can drift from routes, jobs, commands, Aide tools, and browser controls;
an implementation-only inventory cannot explain mutation authority or recovery. Reconciliation tests
make missing functions, owners, evidence, or states a build failure.

Alternatives considered: a hand-maintained document, browser controls only, route-list generation, or
duplicating the feature registry in a second catalog.

Consequences: all 26 registered features and their complete declared function surfaces must reconcile;
generated artifacts are checked for freshness; real-computer cases that need credentials, devices, or
owner infrastructure remain explicit gaps rather than being claimed from local substitutes.

## Fail-visible specialist recovery

Decision

Choice: keep each specialist's last loaded or independently successful owner data visible when one
read fails, label the workbench with the exact loading, offline, partial, or error state, and provide a
bounded retry. For privileged Finance and Server mutations, retry only the backend's exact
`recent_auth_required` challenge after an explicit owner-password confirmation. Roll optimistic Server
choices back to the previous persisted value and focus when the write fails.

Reason: a failed subrequest must not impersonate an honest empty collection, discard usable context,
or leave a visible choice that the server rejected. Privileged retry must never turn an arbitrary 403
into a password prompt or duplicate a mutation.

Alternatives considered: clear each screen to an empty state, show transient toast-only failures, retry
all 403 responses, or leave optimistic selections active after failed persistence.

Consequences: specialist screens retain useful context and expose an explicit recovery path; exact
recent-owner challenges perform at most one confirmed retry; failed choices restore both value and
keyboard context; tests must distinguish intentional failure responses from unexpected console errors.

## KOKUEN v5 universal runtime

Decision

Choice: rebuild the real application around one shared vanilla JavaScript KOKUEN runtime and one
universal shell control, then migrate existing surfaces in the approved order without moving data
authority or changing the nine-app product model. The shell and universal command consume one registry;
the runtime and `design-system/components/contracts.json` share one 14-state vocabulary; every discrete
product control and interactive row has a 44px target.

Reason: Alles already has mature product behavior and a consolidated information architecture, but its
controls and shell conventions are spread across app-specific implementations. One governed runtime can
make interaction, state, focus, keyboard, and visual contracts consistent without a framework migration.

Alternatives considered: build isolated mockups first, migrate to a frontend framework, let every app
retain private control implementations, or change the product model while restyling it.

Consequences: shared tokens, primitives, shell, and interaction schema must stabilize before independent
app migration. Existing APIs and mutation authorities remain the source of truth. Every migrated surface
must reconcile with the exhaustive interaction map and pass the real rendered application gate. Fixed
or modal primary-space surfaces reserve the 52px universal rail before calculating their left edge, and
a mobile app whose local identity rail is closed exposes one compact identity in its local top bar.

## KOKUEN v3 runtime migration

Decision

Choice: adopt the KOKUEN v3 spacing sequence and portable `--ui-*` aliases in the tracked design system,
while remapping existing runtime token consumers by physical value so the established Alles layouts keep
their 24px and 32px geometry. Make the real application, not a standalone starter, the approval gate.

Reason: KOKUEN v3 adds portable aliases and 48px/64px spacing, but directly renumbering the old runtime
would silently enlarge every existing `--k-space-6` and `--k-space-8` use. The product needs a source-of-
truth migration without an unrelated visual redesign.

Alternatives considered: replace every finished surface with a new theme; retain the stale spacing
numbers; or require a mockup approval before applying the already-established direction.

Consequences: new work may target the portable aliases, old layouts retain their reviewed proportions,
the universal command demonstrates the v3 component contract in production, and rendered interaction
proof remains mandatory before handoff.

## Legitimate model-provider authentication only

Decision

Choice: OpenAI, Claude, Kimi, and DeepSeek are API-key providers; custom/CLIProxyAPI-style routing is an
explicit owner-managed proxy connection; Gemini alone also offers Google's published owner-created
desktop OAuth flow. Store secrets with the existing encrypted type, use PKCE/state and a loopback-only
callback, refresh expiring grants every five minutes, and revoke only after Google confirms it.

Reason: provider web sessions and native-client subscription tokens are not third-party API credentials.
The supported boundary follows current official documentation while keeping the local server usable with
legitimate keys, local models, and compatible proxies.

Alternatives considered: scrape consumer chat sessions; import Claude/Codex/Kimi native-client tokens;
label DeepSeek's free chat as OAuth; or expose generic OAuth buttons without a documented flow.

Consequences: Settings shows exact auth type, provider/project identity, quota warning, health, refresh,
disconnect and revocation guidance. Live provider acceptance remains blocked until disposable owner
credentials are supplied, and a failed external revoke keeps the local grant intact.

## One durable Aide question contract

Decision

Choice: normalize selectable questions once in `services/aide_questions.py` and use that contract for
agent-run state, Jarvis persistence, the KOKUEN browser card, and Discord answers. An answer always wakes
the original in-flight run when it exists instead of starting a duplicate model task.

Reason: foreground, background, reload, and Discord paths must preserve the same one-to-four questions,
two-to-five choices, optional free text, cancellation, audit history, and recovery semantics.

Alternatives considered: keep the legacy single-choice Jarvis schema; implement separate browser and
Discord formats; or relaunch a new agent run after every answer.

Consequences: malformed questions and answers fail before persistence; secrets remain redacted by the
existing tool audit boundary; and final Computer Use acceptance remains separate from implementation.

## Strict generated credits with manual-only refresh

Decision

Choice: keep full dependency refresh strict, and provide `--refresh-manual` only for reviewed manual and
inspiration records while preserving the existing validated package inventory.

Reason: adding required source acknowledgments must not erase or fabricate package license evidence when
an unrelated local dependency is missing authoritative metadata.

Alternatives considered: weaken full refresh; silently drop the failing package; or hand-edit generated
manifests.

Consequences: source and inspiration updates remain reproducible, generated checks reject stale manual
records, and full dependency refresh continues to fail honestly until every package has valid evidence.

## Autonomous interface delivery

Decision

Choice: standalone KOKUEN starters are optional design instruments, not owner-approval gates. Once the
requested direction and constraints are clear, apply interface changes autonomously and require fresh
verification of the real rendered application before handoff.

Reason: the owner explicitly removed the approval pause and asked the completion program to proceed fully
autonomously. A starter may still expose design risks, but it cannot substitute for or delay runtime proof.

Alternatives considered: pause every material interface change for separate starter approval; or skip
design exploration and rendered verification entirely.

Consequences: agents may continue without waiting for approval, while every visible or interactive result
still must pass the project design system, anti-slop review, accessibility checks, and real-surface testing.

## Authoritative feature and verification registry

Decision

Choice: use `features/registry.json` as the one machine-readable product inventory. Map every current
FastAPI endpoint owner, interactive HTML control, CLI command, registered job, automation action, and
Aide tool to exactly one feature. Generate the readable catalog and acceptance matrix from this source,
and keep missing product work explicitly `missing`, `partial`, or `unchecked`.

Reason: route counts and broad test totals cannot prove the owner-authored product program is complete.
The registry creates a stable reconciliation gate and an honest place to attach automated and
real-computer evidence.

Alternatives considered: continue extending the prose-only Phase 0 inventory; infer coverage from route
prefixes; or treat a green repository suite as completion evidence.

Consequences: a new runtime owner or capability fails reconciliation until deliberately mapped. Generated
catalog files cannot be hand-edited. Acceptance stays unchecked until its recorded scenario is actually
exercised.

## Files workbench Home ownership

Decision

Choice: the Phase 12 Files workbench owns the visible universal Home action. The nested legacy Files brand
row remains hidden when mounted, and the real browser gate targets the visible workbench action.

Reason: rendering two Files identities and two Home controls breaks the approved unified workbench grammar.
The former Phase 7 gate was stale after consolidation and clicked the deliberately hidden legacy control.

Alternatives considered: reveal the duplicate legacy brand row; or remove the compatibility listener and
markup immediately.

Consequences: old markup can remain as a compatibility seam, but visual and interaction tests must exercise
the actual delivery surface.

## Phase 12 visible product map

Choice: expose exactly eight specialist workbenches: Plan, Inbox, Docs, Files, Health, Finance,
Vault, and Server. Fold Days into Plan; Library and Journal into Docs; Gallery into Files; and System,
Watch, and Activity into Server while preserving compatibility routes and owner records.

Reason: the current fifteen-entry directory exposes implementation history instead of eight coherent
jobs and forces the owner through unrelated shells.

Alternatives considered: keep ten destinations with Gallery and Journal standalone, or reduce to
seven by hiding Vault inside Settings.

Consequences: launcher and Home pins use canonical workbenches; retired identifiers redirect to exact
sections; each replacement must pass behavior and route parity before duplicate chrome is removed.

## Phase 12 Andromeda verification pipeline

Choice: render one compact cited answer from a fast answer model, then independently verify its claims
with a separately configured background model. Default verification to freshness-sensitive queries;
allow always, manual, or off without delaying normal results.

Reason: search must feel immediate while current, latest, version, release, and date claims receive a
stronger independent check.

Alternatives considered: one slower model for both jobs, normal links before the answer, or an
AI-dominant workspace that hides ordinary results.

Consequences: Andromeda gains separate answer/verifier roles, per-claim verdicts, correction history,
checked-date evidence, and honest partial failure. Unsupported model output still fails server-side
quote, entity, number, date, and version validation.

## Phase 12 Server control policy

Choice: default Server to `owned_only`. Permit optional exact host-service control only through
`${ALLES_DATA}/server-policy.json` in `allowlisted_host` mode. The app exposes a schema-bound editor for
that file only; widening authority requires loopback, device profile, recent owner reauthentication,
and exact confirmation.

Reason: Server should manage the installation without turning a browser session or malformed setting
into arbitrary host command authority.

Alternatives considered: companion monitoring only, a database setting writable from any authenticated
session, or unrestricted host process/service control.

Consequences: invalid or absent policy fails closed; service identifiers are exact and manager-typed;
commands, paths, globs, scripts, wildcard services, and arbitrary files are rejected; saves and actions
are atomic and audited.

## Complete Python release lock

Choice: keep `requirements.txt` as the reviewed direct dependency source, generate a universal exact
`requirements.lock` for the supported CPython macOS/native and Linux/container targets, and install
release artifacts only from that lock.

Reason: direct pins do not lock the transitive runtime and cannot support an exact redistribution
inventory.

Alternatives considered: continue resolving transitive packages at install time, or inventory only
the direct requirements.

Consequences: native install, Docker, CI, README commands, and all generated Python notices use the
complete lock; every supported locked package must have authoritative local license evidence.

## Discord notice delivery

Choice: enqueue prompt-specific Discord notices through the existing provider-neutral Jarvis outbox,
mark Discord as idempotency-capable with a stable enforced nonce, and retain run events as the safe
content and audit record.

Reason: sending before a durable claim can duplicate external messages after overlap or interruption,
and state-only identities suppress later prompts in the same waiting state.

Alternatives considered: an in-memory lock, a second Discord-only delivery table, or recording only
after the network request.

Consequences: claims commit before network I/O, interrupted sends can retry with one stable provider
identity, each prompt has its own notice, and candidate scans stay bounded and batch prompt/audit
lookups.

## Phase 7 storage identity

Choice: identify a file by `location_id + normalized_path` while retaining legacy path columns.

Reason: local, WebDAV, and S3-compatible files need stable identity without breaking old Files URLs
or risking owner metadata during migration.

Alternatives considered: replacing legacy paths immediately, or treating each provider as a separate
app.

Consequences: every metadata and operation path must carry a location identity; old calls resolve to
the default local location.

## Phase 8 Finance authority

Choice: use pinned Actual 26.7.0 as the only canonical transaction ledger after a staged parity and
cold-backup gate; retain exact currency/import evidence and immutable legacy rows in Alles sidecars.

Reason: one ledger avoids drift, while additive evidence and an unchanged fallback make the migration
auditable and reversible.

Alternatives considered: keep dual writable ledgers, replace legacy rows in place, or keep the old
ledger permanently canonical.

Consequences: canonical reads and writes use the official Actual bridge, unsupported legacy analytics
fail closed, old rows remain read-only for at least one stable release, and deletion requires a later
fresh backup plus owner confirmation. A candidate budget that fails post-bridge staging validation is
identified, deleted through the official client, and verified absent; an unconfirmed cleanup blocks
another stage until that same identity is retried.

## Offline and transfer safety

Choice: treat offline bytes as a cache and require destination verification before a move deletes its
source.

Reason: cache is not backup, and a remote copy must never remove the only verified copy.

Alternatives considered: optimistic deletion after upload, or presenting cached bytes as recovery.

Consequences: operations expose honest progress and non-atomic state, and remote failures preserve the
source.

## Phase 9 native distribution

Choice: install immutable release directories with one private venv per release, an owned dispatcher,
an atomic current/previous release pointer, and a verified launchd or systemd-user service. Keep all
personal data outside the versioned runtime.

Reason: dependencies, code, and migrated data must switch and roll back as one reviewed update without
editing a live checkout or modifying system Python.

Alternatives considered: a launcher-only checkout, a shared mutable venv, or an in-place pull.

Consequences: clean tracked installs can stage exact upstream commits; dirty or unverifiable sources
install but have no automatic update authority. Uninstall verifies every program artifact and keeps
data, Vault, and Files by default.

## Phase 9 browser Passwords boundary

Choice: pair a browser with a hashed narrow device secret, then require a separate owner-approved,
five-minute in-memory unlock for exact-site metadata and one selected credential release.

Reason: browser convenience must not recreate the retired permanent vault-token or all-site content
script boundary.

Alternatives considered: a pasted vault token, permanent browser unlock, persistent fill session, or
always-running content script.

Consequences: pairing alone cannot decrypt anything. Browser/server restart, explicit/computer lock,
or revoke removes fill authority; the extension asks for the Alles host and active tab only, injects
frame 0, validates form shape, and never submits.

## Phase 10 localization and credits contracts

Choice: use reviewed local catalogs keyed by `en`, `fr`, `es`, `zh-Hans`, `zh-Hant`, `ja`, `ko`, and
`ar`; keep regional formatting separate; and drive all readable/package credit artifacts from one
machine-checked manifest.

Reason: script-specific Chinese catalogs avoid conflating language with region, local catalogs keep
core UI available offline, and a generated notice set can fail closed when a shipped item is missing
license or provenance data.

Alternatives considered: runtime machine translation, DOM-wide string replacement, region-coded
Chinese as the only language identity, or separately maintained credits lists.

Consequences: English is canonical; no language is complete with missing keys, parser gaps, or failed
rendered evidence. User content is never translated implicitly. The manifest must cover dependencies,
vendored assets, fonts, models, datasets, skills, companions, and adapted code. The later autonomous
interface-delivery decision supersedes the former standalone-starter approval requirement.

## Phase 10 Settings foundation (superseded delivery state)

Choice: expose all eight canonical language rows while enabling only reviewed catalogs; default
region, timezone, clock, and week start to browser-aware automatic values; make the universal week
preference authoritative over the retired Calendar-specific choice; and let Credits render incomplete
validated manifest data with explicit coverage gaps.

Reason: visible review state is more honest than hiding planned languages, automatic environment
values avoid typed setup trivia, duplicate week controls would disagree, and an incomplete inventory
must be useful without being mistaken for a complete release artifact.

Alternatives considered: enabling English fallback as translation, free-text locale fields, retaining
both week controls, or hiding Credits until every notice exists.

Consequences: English is the only selectable language today. Calendar uses the shared clock/week
settings. Credits can ship as an auditable foundation, but release checks and the Phase 10 inventory
rows remain open until versions, licenses, and required local texts are complete. This describes the
approved foundation checkpoint; the delivered state below supersedes its availability and inventory
status.

## Phase 10 delivered localization boundary

Choice: release all eight internally reviewed catalogs for the explicitly named core flows, keep
owner/third-party/legacy/advanced text outside that contract, and make the complete generated manifest
and exact referenced notice set the package gate.

Reason: a bounded, machine-tested translation claim is honest and maintainable, while implicit DOM
translation or claiming every legacy screen would be false. Exact generated notices prevent native and
container releases from drifting from the readable Credits view.

Alternatives considered: delay every language for external certification, label English fallback as
translation, translate arbitrary owner/provider text, or keep credits lists manually synchronized.

Consequences: all eight language choices are available after catalog, parser, offline, and rendered
gates. The repository records internal review without claiming external native-speaker certification.
Release validation fails closed on missing credit metadata or notice files.

## Docs departure recovery

Choice: keep one origin-private synchronous browser recovery copy of the active dirty Markdown draft,
then remove it only after the same revision is durably accepted by the local server or the owner
explicitly resolves the draft.

Reason: unload-time fetches, including keepalive requests above the browser quota, can be cancelled
before the server receives the final edit.

Alternatives considered: rely on a before-unload prompt, start an ordinary fetch during pagehide, or
split a large draft across multiple quota-limited keepalive requests.

Consequences: an immediate close can recover the last local edit; a newer server draft wins by its
timestamp; storage failures remain visible and keep the large-draft departure guard active.

## Fallback statement identity

Choice: identify a no-reference Finance import row by the case-folded filename, exact source-file
digest, and row position, while keeping the independent match fingerprint for overlap review.

Reason: generic filenames and row positions are reused across unrelated or corrected statements, so
filename plus row alone can silently suppress a different transaction.

Alternatives considered: filename plus row, content digest without filename, or treating the fuzzy
transaction match as the import identity.

Consequences: exact replays remain idempotent; a changed source is a new reviewed statement; possible
overlap with an older import is surfaced through the existing match-decision flow.

## Phase 12 product consolidation

Decision

Choice: expose exactly Plan, Inbox, Docs, Files, Library, Health, Finance, Vault, and Server as the
specialist workbenches while preserving old hosts and view identifiers as subsection routes.

Reason: the prior fifteen-app directory split related records and controls across standalone screens,
while the existing data models already support coherent workbenches without moving owner records.

Alternatives considered: keep all legacy apps visible, remove Library, or rewrite the frontend around a
new framework.

Consequences: Apps and Home customization share one nine-item catalog; retired names remain compatible
aliases; the vanilla JavaScript/CSS architecture and mutation authorities remain intact.

## Phase 12 independent search verification

Decision

Choice: let one bounded answer model produce the compact cited answer immediately and let a separately
configured, separately confirmed verifier check claims in the background.

Reason: verification should improve freshness and factual confidence without delaying ordinary web
results or making an unchecked answer appear independently corroborated.

Alternatives considered: one model self-checking in the same response, blocking all results on a verifier,
or replacing web results with the model answer.

Consequences: answers and verifier jobs have independent identities, cancellation, evidence, verdicts,
privacy confirmation, and failure states. Web results remain a separate region and stay useful when either
model is unavailable.

## Phase 12 Server authority

Decision

Choice: default Server to Alles-owned services and allow exact host-service identifiers only through the
schema-bound `${ALLES_DATA}/server-policy.json` editor and recent-owner widening flow.

Reason: a useful management surface does not require an arbitrary shell, arbitrary file editor, wildcard
service control, or remotely widenable policy.

Alternatives considered: unrestricted host administration, a free-form command field, settings-database
only policy, or monitoring without management actions.

Consequences: missing, malformed, linked, unsafe-permission, wrong-owner, or unknown-field policy files
fail closed. The UI may edit only that policy schema, supported actions retain their existing ownership
checks, and Server Overview reuses the original neofetch/btop renderer.

## Managed network companions

Decision

Choice: keep AdGuard Home and Nginx Proxy Manager as separately licensed, pinned Compose companions.
Preparation downloads but never starts them; activation uses exact-interface preflight, ownership proof,
health checks, rollback, and no automatic DNS, router, DHCP, or firewall mutation.

Reason: both products are useful and have stable local APIs, but copying or silently activating them
would create licensing, privilege, outage, and ownership hazards.

Alternatives considered: vendor the applications, manage arbitrary existing stacks, activate during
installation, or provide external admin links only.

Consequences: Alles still works without Docker or available ports. Server provides bounded native
management only when the pinned service and ownership verify. Real listener activation is an isolated-
network acceptance scenario, not a test against owner infrastructure.

## Nginx Proxy Manager credential bootstrap

Decision

Choice: create the first Nginx administrator in its loopback setup wizard, exchange the login password
once for a local API token, and store only that token under Alles authenticated encryption.

Reason: Nginx Proxy Manager 2.15.1 logs `INITIAL_ADMIN_PASSWORD` during legacy automated bootstrap.

Alternatives considered: Docker environment bootstrap, storing the admin password, or omitting native
proxy/certificate management.

Consequences: the password never enters Docker environment, container logs, backups, Aide tools, or
model context. Two-factor login remains in the private upstream wizard.

## Completion task model routing

Decision

Choice: route every registered delivery and real-computer acceptance task through the machine-readable
`features/task-routing.json`. Use only GPT-5.6 Sol and Terra because those are executable in the current
Codex backend. Terra handles ordinary implementation and deterministic verification; Sol handles
quality-critical delivery, security boundaries, recovery, and destructive scenarios. Max effort is a
triggered escalation, never a starting route.

Reason: OpenAI publishes workload and effort guidance but no comparable numeric benchmark table for
Sol, Terra, and Luna. An honest route therefore needs explicit local acceptance metrics and the lowest
effort that clears them instead of invented scores or a blanket flagship-model default.

Alternatives considered: route everything to Sol/xhigh, include unavailable Luna routes, use one global
model and effort, or present official role guidance as if it were an empirical Alles benchmark.

Consequences: all 120 registered tasks resolve to an executable model and effort even after their
acceptance status changes, routing stays in sync with the authoritative registry, and escalation requires
a recorded repeated failure or unresolved safety/recovery ambiguity.
