# Calendar recovery and date controls

Calendar keeps its existing Plan location, views and event editor. Save failures
stay beside the editable draft, pending saves disable duplicate submission, and
Back requires a decision before discarding changed input. Failed loads expose Retry.
Success requires a valid saved-event response.

Recurring-event scope uses the existing accessible dialog behavior: a labeled
choice, keyboard focus inside the dialog, Escape cancellation and focus return.
Changing one occurrence or the following series uses one backend transaction.
Cancel and rejected writes preserve the original series.

Event options and month entries use labeled buttons with visible focus and at
least 44px targets. Phone search remains available. Start and end date fields
stack at phone widths so the complete values stay readable. The shared date
picker fits within the viewport, keeps keyboard focus inside while open and
returns focus to its opener.

Untouched dates preserve their stored precision and offset. Editing prose must
not change an overnight end date or move the start of a recurring series.
Timezone-aware occurrences retain their local start time and elapsed duration
through daylight-saving changes.

The maintained Calendar gate checks desktop dark and phone light/dark states,
actual keyboard traversal, deliberate failure recovery and persisted values.
Shared countdown and reminder pickers are neighboring workflows. Automated
phone checks do not establish native Safari or physical iPhone acceptance.

A scoped save whose response is lost can require reload to inspect the event
already saved on the server. Its rejected retry retains the draft and must not
create a duplicate or remove an occurrence. This limitation remains visible in
the stabilization evidence.
