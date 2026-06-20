# ui-8d — Watchtower (findings)

## Audit
The watchtower button rendered the scan panel but clicking it again just re-scanned (no toggle-off), the
button gave no indication it was active, the panel had no explanation of what Watchtower is, and the
sections were a flat list.

## Fix
Made the button a real toggle (`_wtOpen` flag; re-click or "back" returns to the entry list, `.active`
while open, cleared on lock), added a one-line intro + per-section descriptions, and gave the sections a
bordered-card layout. Unified the ✓/← glyphs.

## Verify
`verify.py` opens watchtower (button goes active, intro + 3 described sections render), then clicks the
button again and confirms the panel hides, the button clears its active state, and the entry list returns.
0 console errors.
