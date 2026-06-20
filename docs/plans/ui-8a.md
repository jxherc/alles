# ui-8a — vault chip + toolbar order

The secrets toolbar mixed emoji (✈ ⚙ 🛡 🔓 ＋) and put the settings gear mid-row. Cleaned it up.

- **Settings rightmost** (`static/index.html`): `#vault-manage-btn` moved to the end of the toolbar
  (after lock), relabelled "settings".
- **Unified icons** (`static/js/vault.js` `initVault` + `_loadVaults`): travel → `plane`, settings →
  `gear`, biometric → `fingerprint`, watchtower → `shield`, bio-unlock → `fingerprint`; manage-panel
  "✈ safe" → `plane`, form "⚙ gen" → `refresh`. Static labels stripped of emoji; icons injected via
  `window.icon`/`_si`.
- **Switcher as a chip** (`_renderSwitcher`): `.vault-switcher` chip styling; travel-safe vaults show a
  plane via the dropdown's per-option `_iconHtml` map instead of a ' ✈' text suffix.

Tests: `tests/test_vault_toolbar.py` (6 source-contract) + `docs/evidence/ui-8a/verify.py` (unlocks the
vault: settings is the rightmost button, every toolbar control renders an svg icon, switcher is a chip,
no emoji, 0 console errors).
