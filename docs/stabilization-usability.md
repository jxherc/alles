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

The repaired Plan workflow now keeps current task values after search, protects
drafts during saving and dismissal, hides filtered board cards and gives long
phone titles a readable width. Screenshots of both editor themes, nested discard
confirmation and separate top/bottom scroll positions in a short viewport were
inspected. Browser checks measure 44px targets and verify real saved values.

Native Mac Safari also passed search/clear/edit/reopen, a second-field edit that
preserved the saved date, and Escape/decline/save/reload of an exact mixed-language
note. A fresh owned fixture and final API readback confirmed the values. This is
bounded functional evidence; native screenshot quality still prevents visual
acceptance, and shortened browser viewports do not certify an iPhone keyboard.

## Library audit

Task-based discovery preceded source inspection for overview, books and saved
reading. Local book creation, Goodreads CSV import/deduplication, notes, ratings,
shelf movement, goals and removal were exercised. Synthetic saved articles covered
search, reader opening, archive/unarchive and deletion. Failed note and URL saves,
keyboard-only activation and title/remove overlap exposed STAB-030 through
STAB-033. The integrated repair keeps failed drafts and inline errors visible,
makes note/goal/article actions keyboard reachable and prevents title overlap.
Desktop-dark and phone-light screenshots were manually inspected.

Further inspection found read-card fading reduced summary/metadata contrast to
2.58:1 dark and 2.44:1 light. Removing that fade restores at least 5.02:1 while the
read label remains. A delayed loading check also reproduced lost URL focus and
continued typing in Chromium and WebKit; both now preserve the active field and
caret. Ten maintained Library workflow checks pass in each engine. WebKit uses
Option-Tab and Command-Right for Mac keyboard behavior, and its exact simulated
failure logs differ from Chromium. These checks do not certify a real iPhone.

A bounded native Safari check saved/reloaded a book note, opened an article with
Option-Tab/Enter and returned focus, then saved/reloaded a local fallback URL.
That check predates the final focus/contrast adjustments. Its small screenshot
capture cannot support native visual acceptance; full current Safari coverage
remains open.

The overview repeats reading destinations without a direct add action; the import
format is explained only by a tooltip. These are separate design observations.
Books have no visible search or sort control; the audit does not claim those were
promised features. Failed light-theme fixture setup is explicitly excluded from
visual proof. Live lookup/extraction, full native Safari, physical iPhone and large
imports remain unverified.

## Inbox audit

The subsequent Inbox walkthrough confirmed STAB-039 through STAB-049. Contact
creation/edit failures falsely report success and erase drafts; adding an extra
contact field also replaces other unsaved edits. Mail protects changed subjects
but overlooks body-only changes when closing a draft. Failed list loads resemble
empty accounts, double contact submission creates duplicates, and phone/keyboard
checks expose invisible actions, a clipped Add label, squeezed sender names and
missing row-opening controls. Integrated Chromium checks now reproduce and verify
the repairs in both themes at desktop and phone widths. Failed forms retain their
input and errors; keyboard subject buttons open mail and body-only edits trigger
discard protection. Saved values are checked again after reload.

Ordinary local contacts, vCard import, cached-mail browsing and draft persistence
passed in the isolated audit. The contact create footer remains visible during
detail editing, and the phone composer appears below the list instead of occupying
one working pane. These are separate layout changes. Permanent local draft deletion
lacks the confirmation used by contact deletion; no undo or restore surface was
found. Live mailbox delivery, remote archive/restore, CardDAV, attachments and
provider permissions remain unverified; no external message was sent.

## Calendar audit

Owned-data desktop and phone walkthroughs recorded fifteen further defects,
STAB-063 through STAB-077. Ordinary pointer create/edit/move/delete persisted, but
editing overnight, timezone-aware or recurring events could shift saved dates.
A failed single-occurrence replacement could remove the original occurrence.
Rejected saves also discarded drafts and announced success. Keyboard event access,
editor choices, phone date-picker reachability and hidden phone search had direct
reproductions. These findings remain open while repairs are implemented.

The phone month grid truncates events until their titles are hard to distinguish;
the header uses about 300px before the work area. The existing agenda/day choices
offer alternative views, but their task usability is not fully accepted. Immediate
non-recurring deletion has no visible confirmation or undo. These are separate
design observations. Remote calendars, broader recurrence rules, drag resizing,
large calendars, native Safari and physical iPhone remain unverified.

## Settings audit

Normal preference changes survived reload and an actual owned-server restart.
Deliberately rejected or reordered writes exposed STAB-055 through STAB-059:
ordinary and appearance saves could contradict stored values, while a malformed
regional response could discard the draft. STAB-060 records a timezone preview
that confused the saved override with the browser's detected zone. Arabic phone
Settings was covered by the right-side navigation rail (STAB-061), confirmed by
pointer hit testing despite no horizontal overflow. The custom color control did
not open from the keyboard and was only 34px wide (STAB-062). Repairs are pending.

French, Arabic and Traditional Chinese selection, independent regional overrides,
custom-menu keyboard use and second-context persistence were exercised locally.
This does not certify translation quality or every locale combination. CSS zoom
observations are separate from real browser zoom acceptance; native Safari,
physical iPhone keyboards and assistive technology remain unverified.

Replacing programmed focus in the Settings test with actual Tab traversal exposed
STAB-078: only the selected interface language is tabbable, and the group has no
arrow-key handler. The earlier ability to activate a directly focused language did
not prove keyboard access. Desktop and phone reproductions remain failed while
the group is repaired. Rapid locale changes also stack notifications over the
phone footer; this is retained as a separate notification-layout observation.

## Files recovery audit

A further local/connected-folder walkthrough confirmed STAB-079: a normal
same-name upload replaces the original without a collision decision. Originals
larger than 25 MiB receive no recovery version; exact before/after hashes and empty
version lists proved the loss on desktop and phone. Smaller originals were
versioned, but Details exposed only a count and no restoration action. STAB-080
records phone transfer errors clipped before their actionable reason. Both remain
open while repairs are implemented.

Bulk copy/move, restore collision recovery, unavailable folders, stale search and
permission revocation during a queued operation passed the checked local paths.
Actual keyboard traversal reached upload/selection and filtered rows. Sorting was
not discoverable despite URL parameters supporting it; location labels wrapped
inside words, restored items used opaque trash IDs, and the transfer dialog
required typed destination paths. These are separate usability observations.
Remote providers, Gallery, full zoom and native device acceptance remain open.

## Calendar recovery follow-up

Real picker input exposed STAB-081: the populated end-date field extended beyond
a 390px phone viewport. A stacked phone layout now keeps both dates readable;
before/after screenshots and measured bounds support the repair. Combined-source
verification remains pending.

Calendar's lost-response check deliberately lets a scoped save reach the server,
then drops its acknowledgment. The saved occurrence survives; retry reports a
conflict without a second mutation and retains the draft. Reload is currently
required to inspect the saved result. The existing Plan aggregate notice can also
remain after Calendar's own Retry succeeds; that neighboring state remains under
review. These observations do not establish native Safari acceptance.

## Remaining phone layout work

Manual inspection of the current 390px light-theme surfaces confirmed these design
observations; passing page-overflow checks does not resolve them.

| Surface | Observed friction | Planned direction |
| --- | --- | --- |
| Files | Location, views, mode, indexing and capture controls stack above the file list. | Keep one compact context header and group secondary location/indexing actions. |
| Library | Tabs, material filters, specialist links and open-reading links repeat destinations; the empty state lacks a direct add action. | Put the reading queue and a clear add action first. |
| Health | The overview repeats log/history links and shows several empty summaries. | Make recording a measurement or habit the clear next action. |
| Finance | The optional managed-service installation panel dominates the empty overview; adding an account requires finding Money. | Lead with local accounts and daily entries; retain service setup in a labeled advanced panel. |
| Server | Decorative system art and long machine details dominate the phone opening screen. | Lead with service health and the relevant action; expose details on demand. |

These changes have not been implemented. Functional regression coverage, including
populated and failure states, must accompany each affected layout batch. Server
surface captures include read-only statistics from the test host; the isolated app
database and records are synthetic. Captures belong with test evidence and are not
product content.


## Server administration audit

A fresh owned-data walkthrough reproduced seven issues: monitor outages retain a
live status, service/backup results leave stale visible state, failed backups still
say running, runtime logs omit available timestamps, and policy save feedback
retains missing-file/error state. The owned-only policy also exposes an irrelevant
host-permission confirmation field. These are STAB-087 through STAB-093; repairs
are separate from the Settings/Calendar checkpoint.

The audit used real local authentication, policy validation/save, runtime logs,
encrypted export and restart of its own process. Service lifecycle and remote
backup responses were explicitly simulated. It does not establish live supervisor
or provider acceptance. The monitor gear opens local refresh settings; global
Settings is reached through the existing shell. That navigation distinction is a
usability observation, not a missing feature.

## Gallery task walkthrough

Source-blind discovery followed Home → Files → Gallery, then image import,
viewing, album organization, search, caption editing and Trash recovery. Ten
confirmed defects are STAB-094 through STAB-103. Rejected caption/restore writes
announced success; rejected destination-album creation caused a real removal of
existing membership. Multi-file selection processed only its first item, and
interrupted uploads had no visible recovery. Keyboard opening/focus and long album
menus also failed. Passing ordinary saves did not clear these failure cases.

Removing an image from an album was difficult to discover beneath “add to album”.
At phone width the active album can scroll out of the navigation row while its
header title is hidden. The viewer's seven actions span three rows. These are
separate layout observations; the audit did not invent overlap or unsupported
album deep-link requirements. Ordinary original-image downloads retained their
exact bytes. Screenshots covered desktop/phone, light/dark and emulated touch;
Mac Safari, physical iPhone, large-library and live-provider acceptance remain open.


## Current resting-screen layout review

The integrated phone-light screenshots were manually inspected for all twelve apps
and Settings. These fixtures include empty specialist states; they do not replace
populated workflow acceptance. The remaining layout work is concrete:

- Inbox repeats disconnected-account guidance in separate empty regions.
- Library and Health repeat destinations and include implementation explanations
  before the ordinary task action.
- Finance gives optional companion installation more prominence than local entry.
- Aide has several icon-only header actions; Andromeda does not share the compact
  current-app header used by the daily-work apps.
- Files and Calendar have dense tool rows, while Settings Home places a long outline
  before the actual arrangement controls.

These are design observations, not newly proven data or interaction failures. Keep
all destinations and meaningful status available while applying the approved
single-workspace rules. No changed screenshot was automatically accepted as a
visual baseline, and this inspection does not certify the entire scroll/state matrix.


The follow-up Settings audit confirmed that the active pane always matched its
selected tab. The apparent “about & credits” selection was pointer hover. Actual
keyboard traversal does expose a smaller problem, STAB-104: at 320px and 390px the
selected tab and pane heading both scroll out of view, leaving no visible section
name. Four Shift+Tab presses recover it; no edits are lost. A compact persistent
pane label and distinct active styling are being handled separately.

Ordinary preferences passed reload and a second separately authenticated phone
browser session on the current source. The second context copied no cookies or
browser storage and received a distinct session. The exact context limit, switch,
appearance, French labels, 24-hour format and week-start choice were preserved.
This closes that bounded persistence evidence gap; native device checks remain open.

## Shared navigation and narrow Aide audit, September 26

A task-based walkthrough at 1440px, 390px and 320px reached the app picker with
pointer, emulated touch and keyboard. Escape restored opener focus; Tab wrapped
inside the drawer; scrolling exposed all twelve destinations and Settings. This
is a bounded walkthrough, not independent novice-user research. The icon-only
opener and missing current-app marking are design observations for the consistency
pass, not proven task failures.

Measured default Light/Dark Calendar and Aide control text met 4.5:1 contrast. The
lowest sampled ratio was 4.537488:1 for active Calendar text and the Light Aide
mode's hover state. These measurements do not cover arbitrary custom accents.

A separate confirmed defect (STAB-106) clips Aide's 44px send control at 320px:
only 30.109375px remains visible. Keyboard focus also clips, and the page cannot
scroll sideways to expose it. The audit did not send a provider request; a wider
window or keyboard is the provisional workaround. Its repair requires a real
send/stop regression and narrow rendered checks. Native Safari/iPhone remains
unverified.
