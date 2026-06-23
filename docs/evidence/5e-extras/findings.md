# stage 5e - gated native / local-ML extras - audit findings (2026-06-23)

## current state
- there is no framework for OPTIONAL capabilities that need platform-specific deps (macOS PyObjC:
  PhotoKit/EventKit/Keychain) or heavy optional ML deps (CLIP visual search, OCR). nothing declares
  them, detects whether they can run here, or gates them behind a setting.

## scope (testable, platform-agnostic core)
the EXTRAS REGISTRY + availability/gating logic - the right foundation that every native/ML extra plugs
into. the actual bindings (PyObjC PhotoKit/EventKit/Keychain, CLIP, OCR) are macOS-only and/or need
optional deps not present on this Windows host, so they are EXPLICITLY DEFERRED (declared in the
registry as unavailable here, not stubbed with fake behavior). this is honest: the gate is real + tested;
the native impls land on a mac with the deps installed.

## fix - new `services/extras.py`
- `EXTRAS` registry: each {key, name, description, platforms (e.g. ('darwin',)), requires (import
  names), setting (opt-in flag)}.
- `available(key)` -> platform matches AND every required module imports.
- `enabled(key, settings)` -> available AND the opt-in setting is on.
- `status(settings)` -> every extra with available/enabled/reason for the UI.
- settings flags (all default False) + route GET /api/extras.

tested: status lists all, available false on wrong platform, available false on missing dep (monkeypatch
importlib), available true when platform+deps ok, enabled requires available+setting, unknown key safe.
