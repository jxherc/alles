# Settings recovery and logical overlays

Date: 2026-09-25

## Decision

Preference saves expose their state in the pane containing the control. A failed
write keeps a retryable form value or restores the confirmed switch value. Save
acknowledgments require a valid server response. Repeated same-page writes follow
submission order; an earlier response cannot replace the latest visible intent.

Appearance can preview immediately. Unconfirmed changes remain explicitly marked
and offer a labeled retry action, including after reload when browser storage is
available. A successful appearance write also updates the existing legacy theme
and accent fields through the same API. No second client write is needed.

Root dialogs reserve the rail's space using logical inline insets. The reservation
moves with the rail in right-to-left layouts. Dialog width and pointer hit testing
must both be checked; absence of horizontal overflow does not prove visibility.

Custom color controls remain labeled and at least 44px in both dimensions. Keyboard
users can reach the trigger, open it with Enter or Space, edit a hex value and leave
with Done or Escape. The picker contains Tab navigation and restores focus to its
trigger when dismissed by keyboard. It uses the existing controls and typography.

## Verification boundary

STAB-055–062 supply the original reproductions. The maintained Settings recovery
gate checks delayed/rejected writes, invalid acknowledgments, exact saved values,
restart, RTL geometry and keyboard controls in owned desktop/phone fixtures.
Integration evidence is recorded in the stabilization ledger. Native Safari,
physical iPhone, assistive technology and full browser zoom acceptance remain
separate requirements.
