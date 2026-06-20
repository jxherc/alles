# 10f — realtime voice (gated): implementation + regression

## Approach
Per ROADMAP, full-duplex voice ships ONLY behind a real-provider gate — no fake shell. The gate opens
when an enabled endpoint exposes a model matching /realtime/ (OpenAI Realtime convention). In production
that appears after configuring an OpenAI endpoint + refreshing models; the UI affordance stays hidden
until then.

## Built (strict TDD, ruff + node-check clean — no new lint errors)
- **10f-1 gate + status + session handoff** — `services/realtime.py` (`find_realtime_endpoint`, `status`)
  + `GET /api/voice/realtime/status` + `POST /api/voice/realtime/session` (503 with reason when gated;
  real `{provider, base_url, model}` descriptor when available). Also added manual `models` entry to
  `PATCH /api/models/endpoint` so a realtime model list can be set without a live probe. 10 unit tests.
- **10f-2 frontend** — a "live voice" composer button hidden unless `/api/voice/realtime/status` reports
  available; it appears once a realtime endpoint is configured and requests a session descriptor on click.
  8 Playwright assertions (hidden-when-gated, appears-when-provider, 503 gated). Stamps v75 / SW v49.

## Regression
16 subdomains 0 console errors (`docs/evidence/10f/regression/`). Full suite: 1682 tests OK.
