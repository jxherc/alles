# Stage 2 — aide — findings

## Bugs fixed (functional)
- **ui-2a** research & docs-ask silently did nothing on a fresh chat — both bailed on `if(!getActiveId())`.
  Added `sessions.ensureSession()` (mirrors sendMessage's lazy create) and call it in `runResearch` /
  `runDocsQuery`. Behavioral: both now send on a fresh session.
- **ui-2b** a 2nd "ask your docs" answer overwrote the 1st — `ragquery.js` used shared ids
  (`docs-ans`/`docs-src`/`docs-dot`) and `getElementById` returns the first. Now each query holds refs to
  its OWN nodes via `row.querySelector('.rag-*')`. `research.js` had the same shared-id flaw (scoped to
  `.rs-*` now). Behavioral: two questions → two boxes, ANSWER 1 in box 1, ANSWER 2 in box 2.
- **ui-2c** research looked blank while waiting — added a "searching the web…" warming line (cleared on the
  first event), error states clear the spinner, and an empty result shows "no results — try rephrasing".
- **ui-2d** usage only counted on Anthropic — `_parse_openai` returned at `finish_reason`, dropping the
  trailing usage chunk OpenAI-compat/deepseek/groq send afterward. Now it captures usage whenever present
  and keeps reading to `[DONE]`. New tests cover the trailing-chunk + combined-chunk shapes + no double tool
  emit.

## Polish
- **ui-2e** voice waveform → Apple Voice Memos: centered rounded bars scrolling left, recording red
  (#ff453a), live MM:SS timer. Verified with a fake mic device (canvas paints red bars, recording toggles).
- **ui-2f** glowing per-provider brand logos in the model modal, sidebar provider headers, the topbar
  indicator, and the home selector (shared `brandlogo.js`). DeepSeek models renamed: reasoner → "v4 pro",
  chat → "v4 flash". Topbar now shows the glowing brand mark before the model name.

## Verified
- `tests.test_aide_fixes` (8), `tests.test_voice` (8), `tests.test_llm` (34, +3 new) green.
- Behavioral (SW blocked so route mocks apply): `pw_aide_2.py` 7/7, `pw_voice_2e.py` 4/4, `pw_models_2f.py`
  9/9. Screenshots: docs-two-answers, research-report, voice-recording, model-logos. 0 console errors.
- Note: Playwright mocking of `/api/*` requires `service_workers="block"` (the SW re-issues requests).
