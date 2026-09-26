# Usability observations

These observations come from task walkthroughs on the isolated synthetic instance,
using visible controls and native Mac Safari 27.0 accessibility output. They do not
certify the complete visual or device matrix.

| Task | Observed result | Follow-up |
| --- | --- | --- |
| Leave an unsaved document, return, reload and resume it | The exact mixed-language draft survived. Reload clearly separated the saved document from the recoverable local draft. | Keep this recovery path visible. |
| Go from a document to Home, then reload | Before STAB-005, reload reopened Docs because the old URL remained. The repair keeps Home selected and Back restores the original document. | Covered by the navigation regressions. |
| Record a Health measurement | The entry action was available after opening health log. A synthetic 74.25 kg record persisted exactly after reload. The screen rounds it to 74.3 kg. | Preserve exact values when editing; distinguish summary rounding from detailed record values. |
| Correct that Health measurement | The record offered delete, with no visible edit action. Source inspection after the walkthrough confirmed an unused edit API. | STAB-006 repaired: labeled edit action, exact values, persistent save errors, retry and focus return. Chromium desktop/phone and native Safari correction/reload checked. |
| Find the main Health action | The overview shows both health log and open health history, plus repeated summaries. Creating an entry takes a further view change. | Simplify this overview in the specialist layout batch; keep privacy boundaries clear. |

The last row is a design change, separate from the confirmed functional defects.

Health range changes also erased drafts (STAB-011), and malformed numbers were silently shortened (STAB-010). Both have real browser reproductions and regressions. The editor now retains exact values, dates and notes during range loads, rejects malformed input, and keeps failed edits available to retry.

Finance task checks used synthetic manual accounts in Chromium desktop dark and
phone light. Before the repairs, a grouped amount silently became a different
value and phone rows hid their payee/account text. Both now have repeatable
regressions; account, payee, category, amount and actions were inspected on the
populated phone screen. The surrounding Finance summary cards still need the
specialist layout pass. Native Safari also rejected malformed account/transaction amounts, then created
and edited the synthetic expense from 12.34 to 56.78 with exact reload persistence.
This is a bounded native workflow check; the full Safari visual matrix is outstanding.

An offline Health walkthrough deliberately denied browser storage. Before the
repair the entry disappeared with a success notice and no saved copy. The repaired
screen keeps its value and mixed-language note visible with a persistent save error;
restoring storage and retrying saves once after reconnect. This is Chromium evidence,
with explicit simulated storage faults, not physical iPhone acceptance.

## Setup and sign-in recovery

Desktop-dark and phone-light Chromium checks completed fresh setup, interruption, login and owner confirmation with pointer and keyboard input. Wrong-password and unavailable-network errors stay inside the foreground sign-in surface. Login input and action meet 44px targets, and the form stays reachable at 390×420. This constrained viewport supplements, but does not certify, an actual phone keyboard. Screenshots were manually inspected; viewport captures avoid expanding the image to the hidden, uninitialized app beneath sign-in.

Native Mac Safari also rejected a wrong synthetic password, exposed the inline error, accepted a corrected retry and preserved authentication after reload on a fresh owned instance. Its 97×108 capture remains too small for visual acceptance. Full native Safari and physical iPhone coverage remain open.

## Rejected offline changes

Desktop-dark and phone-light screenshots show a persistent pending indicator and a review dialog that states changes are kept in this browser and have not reached the server. Saved Health values, mixed-language notes, failure reason and recovery controls stay readable at 390px; controls meet 44px targets. The actual browser workflow verifies the downloaded copy, cancellation, retry, individual discard confirmation and focus return after the last item is resolved. This evidence covers Chromium, not native Safari or physical phone storage behavior.

## Plan task audit

The desktop and phone task walkthrough reproduced six defects recorded as
STAB-024 through STAB-029. Ordinary editing, search, failed-save retry and board
stage changes persisted correctly, but those successful paths missed stale search
state, edits during an in-flight save and discarded unsaved input. Populated phone
screens also exposed obscured editor fields and excessively narrow task titles.
Board counters changed while excluded cards remained visible.

Task editing lives in Tasks while stage movement lives in the board, adding a view
change to a combined task. The board detail label “record: existing Task” does not
explain a useful action. These are separate design observations. This walkthrough
followed source inspection, so it is not independent source-blind usability
acceptance. Native Safari, light theme, zoom and actual phone keyboard checks for
these Plan paths remain outstanding.
