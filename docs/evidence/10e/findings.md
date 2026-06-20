# 10e — vision + browser: implementation + regression

## Audit
Image vision already worked (uploads → image_url parts). Computer-use (pyautogui pixel-level) existed;
no DOM browser tool. ffmpeg available. No video-frame extraction.

## Built (strict TDD, ruff + node-check clean — no new lint errors)
- **10e-1 video-input understanding** — `services/video_frames.py` (`is_video`, evenly-spaced
  `_sample_times` capped at MAX_FRAMES, `extract_frames` via ffmpeg → `data:image/jpeg` URLs, degrades to
  [] without ffmpeg). `chat.py` turns a `video/*` upload into sampled frames fed to the vision model.
  The composer attach input is unrestricted so video already uploads. 10 unit tests.
- **10e-2 browser-automation tool** — `services/browser_tool.py` (lazily-launched headless Chromium via
  Playwright async API: navigate/read/click/type/current_url/screenshot, one session per agent run) +
  `browse_open/read/click/type/screenshot` agent tools wired into `execute()` + tool defs;
  open/click/type marked mutating. 9 unit tests driving real headless chromium against a temp file:// page.

## Regression
16 subdomains 0 console errors (`docs/evidence/10e/regression/`). Full suite: 1672 tests OK.

## Note
Video *generation* stays out of scope (no self-hostable model). Browser tool is DOM-level, distinct from
the existing pixel computer-use.
