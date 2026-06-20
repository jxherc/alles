# ui-8a — vault toolbar (findings)

## Audit
The boot fix from ui-7e un-gated the secrets view, so it renders + unlocks on the test server now. The
toolbar showed ✈ ⚙ ＋ 🛡 🔓 emoji and the settings gear sat in the middle of the row.

## Fix
Moved settings (gear) to the rightmost slot; unified every toolbar/manage/form glyph to the central icon
set via window.icon; made the vault switcher a chip with a per-option plane icon for travel-safe vaults.

## Verify
`verify.py` unlocks the vault (first unlock sets the master) and confirms via the DOM: settings is the
last toolbar button, travel/biometric/watchtower/settings each render an `<svg class=ic>`, the switcher
carries the chip class, no emoji remain, 0 console errors. (The base view doesn't paint to a screenshot
on this server — the toolbar order is shown in the verify output instead.)
