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
regressions, Plan capture, Docs persistence and recovery, local Files operations,
Andromeda cancellation/retry with simulated transport, Aide interruption/recovery
with a delayed loopback provider, Health correction/recovery,
PWA offline/reconnect, and
resting surfaces for all twelve apps plus Settings in both themes at desktop and
phone widths. `daily`, `assistant`, `specialist`, `surfaces`, and `pwa` select those subsets.
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
The current ledger tracks 1,581
controls and 130 workflows: 22 passed, 106 untested and two blocked. Added proofs
cover interrupted Aide history, Stop ownership, incognito storage isolation, and
Health correction/validation/recovery. Model responses are explicitly simulated
on loopback. Screenshots of the new interruption and Health recovery states were
inspected manually; native Mac Safari also passed exact Health correction/reload.

Source review raised one privacy-flag finding that was rejected after tracing the
existing request handler and verifying the real incognito browser paths. The route
already supplies the server-owned privacy flag to the runtime. The confirmed
run-file persistence defect has separate regression coverage.

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
| Browse documents or file locations | Inside Docs or Files; hiding views leaves these controls available |
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
