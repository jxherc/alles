# Stabilization

Alles is undergoing a stability pass. Historical acceptance notes and source
inventory are not a current release certificate.

## Coverage

The feature registry supplies required workflows and integration boundaries. The
control census supplies all discovered static and dynamically rendered controls.
The stabilization report combines these with explicit scenario results, retaining
untested and blocked entries. A reference to a test file is not a passing result.

Every finding records a reproduction, expected and actual behavior, severity,
revision, and verification. Design changes are separate from confirmed bugs.
Reports and screenshots use synthetic data and stay in the test artifact directory.

`features/stabilization.json` is the required-workflow ledger. The report adds every
control from `docs/control-census.json`, including shared navigation and Settings.
It requires matching code and acceptance-definition fingerprints. A desktop pass
cannot replace a missing or failing phone result. An interrupted run stays incomplete.

## Repeatable checks

With the repository's Python environment and Playwright Chromium installed:

```sh
python scripts/run_browser_gates.py --suite smoke --output /tmp/alles-smoke-1
python scripts/run_browser_gates.py --suite full --output /tmp/alles-full-1
python scripts/run_browser_gates.py --suite full --output /tmp/alles-full-2
python scripts/stabilization_report.py \
  --results /tmp/alles-full-1/results.json /tmp/alles-full-2/results.json \
  --output /tmp/alles-coverage.json
```

Choose a new output directory for each run. The runner starts and stops only its
own servers, verifies their ownership, and removes only its temporary data. It
does not inherit provider credentials, owner database paths or `.env`. Model caches
are temporary and downloads are disabled; these runs exercise local services and
the keyword-search fallback, not live model integrations.

The maintained full suite currently contains Home capture/navigation, cleanup
regressions, Plan capture/conflict/draft recovery, Docs persistence and delayed-editor
recovery, local Files operations,
Andromeda cancellation/retry with simulated transport, Aide interruption/recovery
with a delayed loopback provider, Health correction/recovery, local Finance
validation/retry/persistence, Library note/reading recovery, Inbox contact/mail draft
recovery, Vault and local encrypted-backup controls, Home reminder timezone boundaries, owner setup and
sign-in recovery, PWA offline/reconnect, browser-storage failure and rejected-write recovery, and
resting surfaces for all twelve apps plus Settings in both themes at desktop and
phone widths. `daily`, `setup`, `assistant`, `specialist`, `surfaces`, and `pwa` select those subsets.
Traces, screenshots, requests, console output and server logs accompany the
results. Historical browser scripts outside this maintained list remain unaudited;
the word `full` does not mean every product workflow has been certified.

GitHub runs Python, JavaScript, Ruff and the browser smoke suite. The workflow's
manual dispatch can select the maintained full suite and retains browser artifacts
for fourteen days. A green workflow does not override blocked ledger entries.

## Checkpoint evidence

The first implementation batch was checked on September 25, 2026, from baseline
`c696c42` with the stabilization changes applied. Both fresh full browser runs passed
all ten maintained gates. Their common source fingerprint is
`e4aa6930981c8422291abb166dd89ecaca09858419f8e1949f7a044a0d0e1ef6`; their acceptance
fingerprint is `311e2e1cfb1ac62a84e8b30ffe854a77d04b2ccab4dcd97957de94db91545438`.

The isolated Python run completed 5,611 tests with no failures and six explicit
skips. JavaScript passed all 587 tests; Ruff check and format check passed. The
Python skips cover the separately enabled official-runtime/performance gates,
two non-Mac contracts on this Mac, and unavailable CLIP/face models. They remain
limitations, not successful checks.

The first checkpoint's ledger contains 28 feature/surface owners, 1,579 inventoried controls
and 115 required workflows: seven passed, 106 untested and two blocked. No control
inherits a pass merely because a workflow visited its screen. These counts describe
the measured coverage, not a stable release. The seven passed workflows are Home
capture, its phone interaction, Plan capture, Docs save/reload, failed-save retry,
concurrent-edit recovery, and local Files operations/recovery.

Native Mac Safari 27.0 checks also exercised fresh setup using temporary paths,
Home capture/reload, navigation, document creation, mixed-language save/reload,
hidden views and blank-draft feedback. This is partial Safari evidence. Real iPhone
Safari acceptance, complete Mac Safari acceptance, live providers and the seven-day
trial are still outstanding.

The next repair batch passed all eleven maintained browser gates twice from fresh
data, all 602 JavaScript tests, 76 focused Python tests and Ruff. Its source
fingerprint is `00438894208d7d36488620258aaf83c5c8965edcc66856ad835444477661c9c8`;
its acceptance fingerprint is
`6b2240c18a7e926c7882ea1ce0aafdad06d2a531771d05ebafa004e7fb890eb4`.
The resulting ledger has 119 workflows: eleven passed, 106 untested and two blocked.
The added proofs cover primary-app reload/history and three explicitly simulated
Andromeda cancellation/retry cases. They do not establish live-provider cancellation.

The [usability observations](stabilization-usability.md) record native Safari draft
recovery and Health correction checks. The complete release gates remain
unsatisfied.

The interruption and Health repair batch passed thirteen maintained gates twice
from fresh fixtures, with source fingerprint
`e714389a810870894142072564bea5b3c899b71f4e567503e1010c37f37bc27d` and acceptance
fingerprint `465514e8fea08ed2d6bdaa271e6f8eeea48328086d01f51490de633863f85624`.
All 609 JavaScript tests and Ruff checks passed. The isolated Python suite ran
5,624 tests without failures, with the same six explicit skips documented above.
That checkpoint tracked 1,581
controls and 130 workflows: 22 passed, 106 untested and two blocked. Added proofs
cover interrupted Aide history, Stop ownership, incognito storage isolation, and
Health correction/validation/recovery. Model responses are explicitly simulated
on loopback. Screenshots of the new interruption and Health recovery states were
inspected manually; native Mac Safari also passed exact Health correction/reload.

Source review raised one privacy-flag finding that was rejected after tracing the
existing request handler and verifying the real incognito browser paths. The route
already supplies the server-owned privacy flag to the runtime. The confirmed
run-file persistence defect has separate regression coverage.

The Finance and offline-storage batch repairs three local-ledger defects: numeric
prefix truncation, duplicate creates after a lost acknowledgment, and collapsed
phone transaction rows. Finance validates the entire decimal input; unsupported grouped
or trailing-text inputs produce an error without a write. Local account,
transaction and transfer creates store a receipt in the same SQLite transaction.
An exact retry reuses that result; changed values conflict. Deleting an entry
removes receipt content and retains a tombstone so late retries cannot recreate it.
The receipt table is additive and existing ledger rows are unchanged. Startup over
an older synthetic database and replay from a SQLite backup were checked.

Offline queueing now reports success only after browser storage commits. If storage
fails, Health keeps the entry editable and displays a save error. A notification
failure after a successful queue commit cannot turn that accepted write into a
misleading failed save. Storage and notification faults are explicitly simulated;
this evidence does not certify real device storage exhaustion or every queued API.

The setup recovery batch places credential and connection errors inside the sign-in
surface and prevents duplicate submissions while a request is pending. Optional
companion installation uses the existing owner-confirmation flow. Escape dismisses
only that confirmation dialog, retaining the underlying Settings draft and focus.
Browser fixtures use real local authentication; companion installation and expired
confirmation timestamps are explicitly controlled test conditions. No host plugin
installation is performed.

Home now supplies its displayed date and timezone when loading reminders. Stored
UTC instants are converted with the timezone rules for that instant, including
daylight-saving changes. Date-only API callers retain the owner or server timezone
fallback. Deterministic boundary checks cover Toronto, Tokyo and an owner timezone
that differs from the browser.

Rejected offline changes now remain in the browser with their failure reason. The
pending indicator opens a review dialog with saved values, a downloadable copy,
explicit retry and individually confirmed discard. Expired sessions can sign in
and retry; conflicts and invalid input do not resend automatically. Queue drains
are serialized to prevent overlapping reconnect/manual requests sending the same
entry concurrently. A manual retry cannot overtake an earlier retained write;
the review explains which earlier change must be resolved first. Real restart/login checks and simulated 409/422/503 responses
cover Health entries; unrelated queued APIs remain in the ledger.

The subsequent Plan audit reproduced six defects: a stale search result
can overwrite a newer saved edit, typing during a pending save can lose text,
board filters leave excluded cards visible, the phone navigation rail covers the
editor, task metadata squeezes long phone titles, and dismissing a dirty editor
discards input. STAB-024 through STAB-029 now have targeted repairs and a maintained
desktop/phone gate. Editors use the currently displayed task collection, prevent
editing during pending writes and require explicit discard of unsaved changes.
Filtered cards obey their hidden state; phone titles and editor fields stay usable.
Nested confirmation, failed-write retry and exact persistence have browser checks.

The Library audit subsequently confirmed failed note saves that report success and
lose input, unrecoverable URL-save failures, missing keyboard activation and book
remove buttons covering title text. STAB-030 through STAB-033 were open at the first
Plan checkpoint; the subsequent Library repair is described below.

The Finance, recovery, setup and reminder checkpoint passed all eighteen maintained
browser gates twice from fresh fixtures. Its source fingerprint is
`0af46ab359fee73387cfbd2b9fe6a1a378d882f7cd66239eaa010fce6e06fec8` and its acceptance fingerprint is
`562efeaab788a49f316a8ccfb38d10b423a535cdfbdcd23436865468d596066f`. Both runs confirmed server shutdown and temporary-data removal.
The isolated Python suite passed 5,641 tests with the same six explicit skips;
JavaScript passed 648 tests. Forty runner/ledger checks, Ruff and source review
also passed after the queue-ordering repair. The census now inventories 1,589
controls; the 143-workflow ledger records 37 passed, 104 untested and two blocked.
At that checkpoint, the six Plan defects were still open. Outstanding workflow,
device and provider acceptance continue to prevent release. These results certify
that checkpoint's maintained workflows only.

The first Plan repair checkpoint passed nineteen maintained gates twice from fresh
fixtures, plus 648 JavaScript tests, 98 focused Python checks and Ruff. Its source
fingerprint is `a0c6b076b18e2ca6836505bf915b47ec3d8d341936010afb77a8a95256b2656f`;
its acceptance fingerprint is
`a87127e2e034369423dade4a7977809d4725f0ce6ad65fcab542d71e069e14f1`.
The ledger now records 45 passed workflows, 104 untested and two blocked. Source
review's two target-size/disabled-state concerns were disproved by existing shared
components and direct browser assertions; no actionable finding remained.

Additional Plan checks then confirmed stale-tab overwrites, late responses replacing
the selected list, and lost drafts on reload/full-document history (STAB-034 through
STAB-036). Their subsequent repair sends changed fields with atomic preconditions,
retains per-tab owner-scoped drafts, and rejects obsolete list responses. Current
integration evidence is recorded below; complete Plan acceptance is still outstanding.

The Library repair retains book notes and URL drafts after rejected writes, rejects
invalid save acknowledgments, restores keyboard article/note/goal actions and
reserves title space for remove controls. A further rendered audit found faded
read-card text below accessible contrast (STAB-037); it now measures at least
5.02:1 in both themes. Delayed initial or search loads also stole URL focus and
lost continued typing (STAB-038). Rendering now preserves the currently edited
field and caret. All six Library findings have verified reproductions and repairs.

The Library checkpoint source fingerprint is
`ab4c43b15be10546e13f8b282940c64a9f6c13f4569894247f1ce37d26920ea0` and acceptance
fingerprint is `5b9632b8ad321ab474d38669adc07afde2f462cc7004e094955b59a74f82b49f`.
One fresh full twenty-gate run passed. A separate run of the same source failed an
existing Docs recovery assertion and a Finance test scroll. The Docs failure exposed
STAB-054: late visual-editor loading overwrote new Source text and recovery copies.
The Finance test unnecessarily reopened an already selected Money view; its helper
now preserves the loaded view before measuring rows. Both original failures remain
in the evidence archive. This checkpoint does not meet the two-clean-full-run gate.
Library's ten desktop/phone checks passed in Chromium and supplementary WebKit
26.5, with browser-specific keyboard and exact error-log expectations. All 648
JavaScript tests, 84 focused Python checks and Ruff passed. The ledger inventories
1,592 controls and 156 workflows: 50 passed, 104 untested and two blocked.

Further owned-data audits recorded eleven Inbox defects (STAB-039–049) and four
Vault/backup UI defects (STAB-050–053). Their repairs retain failed contact and mail
drafts, protect edits made during a pending mail save, restore keyboard row/file
actions and keep phone controls readable. Local backup recovery preserved notes
and decrypted Vault entries; upload failure and expired owner confirmation allow
an exact same-file retry.

The combined recovery checkpoint resolves STAB-034–036 and STAB-039–054. Its fresh
24-gate full Chromium run passed with source fingerprint
`fad8f531be4279ebdf023b5a7bd20aa607ac7b8d34d43d4da63f1ce4a1f8c669` and acceptance
fingerprint `786e21db18e6f58c75afba0443360790c6b788988812c4d75de96df6268ce064`.
All owned servers stopped and temporary data was removed. The isolated Python
suite completed 5,651 tests with no failures and six explicit skips; all 663
JavaScript tests, Ruff and the regenerated census checks passed. Repaired conflict,
draft, Inbox and backup screens were manually inspected. Product source review
found no actionable issues; the new Vault browser test was inspected and run
locally rather than included in external review because its header/cookie code
triggered the review bundle guard.

The inventory contains 1,603 controls and 188 required workflows: 82 passed,
98 untested, six failed and two blocked. The six failures retain the later Calendar
and Settings audit results, covering STAB-055–077. Earlier failed full runs remain
in the evidence archive: route/lint snapshots and Docs test line references required
inventory corrections. Only one complete full run matches the final current source;
the preceding 24-gate pass predates the inventory and test-assertion changes.

Two supplementary Plan WebKit replays passed all eighteen recovery scenarios after
correcting a Chromium-specific keyboard-focus assumption in the test. An earlier
intermittent reload rendering/accessibility failure remains unresolved; diagnostic
instrumentation can affect timing, and these replays do not prove it repaired.
Native Safari still yields thumbnail-sized captures insufficient for visual
acceptance. Complete host-supervisor, native device, provider and seven-day trial
acceptance remains outstanding. This checkpoint is not a stable release.

## Stable layout

The app picker keeps the same destinations. Each app has one working area, a compact
header and local views. Advanced tools remain in their existing contextual menus.
Home capture comes before the overview. Document and file navigation stays available
independently of the views strip. Existing links and saved data retain their meaning.

The layout contract is in [decision 0012](../design-system/decisions/0012-minimal-workspace.md).

| Action | Location |
| --- | --- |
| Switch apps | The existing app picker at the left edge |
| Capture from Home | Above the daily overview |
| Change a specialist app's view | The horizontal views strip below its header |
| Hide or restore that strip | `views` in the app header |
| Capture or filter Plan tasks | Above the agenda |
| Edit a task or protect its unsaved changes | Plan → tasks → its title; Cancel, Escape or outside dismissal asks before discarding changed fields |
| Recover conflicting or interrupted task edits | Plan → tasks → the editor; review both versions, download a draft, or confirm which changes to keep |
| Continue editing if the visual document editor fails | Docs → Edit → Source; the visible loading/error status preserves the current buffer and Save action |
| Browse documents or file locations | Inside Docs or Files; hiding views leaves these controls available |
| Correct a Finance transaction | Finance → money → edit on its row; on phones the account and actions wrap below the payee and amount |
| Recover an offline change | Pending indicator → review; inspect saved values, sign in or retry, save a copy, or confirm discard |
| Edit book notes or a reading goal | Library → books → the note or goal; both are keyboard actions |
| Recover a failed reading save | Library → saved → the retained URL and inline error; retry after resolving the failure |
| Retry a failed contact save | Inbox → contacts → the retained form and its inline error; Save or Add retries the unchanged fields |
| Open mail or drafts by keyboard | Inbox → mail → the subject button; body-only unsaved changes also require discard confirmation |
| Restore a local encrypted backup | Settings → backup & restore → choose backup file; keyboard file actions, password confirmation and same-file retry remain available |
| Correct a Health measurement | Health → logs → edit beside the record; exact value, date, unit and note stay together |

Daily-work layouts are the first implementation batch. Specialist summaries,
assistant workflows, long-list fixtures, all failure states, live integrations and
the complete accessibility/usability matrix remain in the ledger until verified.

## Release conditions

A release requires current workflow and visual evidence, no unresolved task-blocking
or data-loss defects, two clean isolated full runs, Mac Safari and physical iPhone
Safari acceptance, and a seven-day bug-fix-only trial. A passing smoke suite does
not satisfy these conditions. Provider, device, backup and upgrade checks that did
not run remain untested or blocked, with a reason.

During the trial, keep names, navigation and action placement stable. Log the build,
day, workflows used and any issue. A blocking regression restarts the trial after
its fix and retest. Do not infer seven days of usage from elapsed time alone.

Incognito run metadata now shares the conversation’s RAM-only lifetime, including cancellation and expiry. Earlier versions could write private prompt/reply content into agent-run JSON files. This repair prevents new writes; historical owner files were not inspected or deleted.
