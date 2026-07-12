# Afterlife Phase 4 verification

- **Date:** July 13, 2026 (Asia/Taipei)
- **Branch:** `dev-afterlife`
- **Result:** delivered through the honest SearXNG-unavailable path
- **Data rule:** every server, browser, migration, backup, and integration run used throwaway
  `ALLES_DATA`; the normal user data folder was not used.

## Main gates

| Gate | Fresh result |
|---|---|
| Full Python | 4,057 passed, 4 skipped, 0 failed; 413.186 s test time, 416.33 s wall time |
| Focused Phase 4 backend | 182 passed, 0 failed; 5.208 s test time, 6.68 s wall time |
| Full JavaScript | 183 passed, 0 failed; 708 ms |
| Browser, auth off | 80/80 assertions passed |
| Browser, auth on | 80/80 assertions passed |
| Route compatibility snapshot | 733 routes; digest `c1333f3c71fe306ff3265eee04815c7118fae65616370fd2caaa299fdb566ad0`; 3/3 focused checks passed |
| Historical migrations | every canonical and photo-fork prefix restored, migrated twice, and booted; 3/3 checks passed in 172.791 s |
| Diff whitespace | `git diff --check` passed |

The focused backend command covered Aide, Andromeda, Jarvis handoff, the candidate SearXNG service,
capabilities, personas, encrypted backup, service ownership, route compatibility, insights, memory
extraction/policy/store, research, and the research endpoint.

## Browser coverage

The same Playwright gate ran at 1280×800 and 390×844 with reduced motion enabled. It covered:

- Chat/Jarvis selection, Automatic tools/Answer only labels, Compare as an action, draft retention,
  explicit endpoint+model handoff, cancel/retry, and durable reload;
- conclusion-first steps, restored Sources/Revert controls, Jump to latest keyboard use, incognito,
  mobile fit, and zero unexpected console/page/server errors;
- normal Andromeda results, `!ai`, independent overview/results controls, citations, saved searches,
  failure recovery with focus return, and Project-preserving deep research;
- honest optional-SearXNG wording, no false install action, an HTTPS external URL example, and the
  loopback address shown in the unavailable state;
- password-disabled access and password-enabled login across the apex, Aide, and Server hosts.

## Search and overview timing

Reference machine: MacBookAir10,1, Apple silicon arm64, 8 GB memory, 8 logical CPUs, macOS 27.0.

The deterministic gate ran 60 iterations with a fixed search fixture and a loopback
OpenAI-compatible HTTP model stub:

| Measurement | Median | p95 | Maximum | Budget | Result |
|---|---:|---:|---:|---:|---|
| ten links ready | 0.043 ms | 0.051 ms | 0.147 ms | 1,500 ms p95 | pass |
| Standard local first verified text | 1.298 ms | 1.682 ms | 80.051 ms | 5,000 ms p95 | pass |

This proves deterministic application overhead, not real model speed. No real small local model was
qualified during this gate.

Separate live-network observations used DuckDuckGo and are not a guarantee:

- Python 3.14 release notes: 5 results in 3,109 ms;
- current FastAPI documentation: 5 results in 2,358 ms;
- latest SQLite release notes: 5 results in 3,904 ms.

## Grounding and privacy proof

Focused tests prove that a supported claim needs an exact quote from its named source and also reject:

- an exact but unrelated quote;
- mismatched numbers, versions, dates, or entities;
- stale or community-only evidence presented as current;
- weak/conflicting evidence when a fresher primary source exists;
- unsafe URLs, bad extraction, malformed model output, timeout, cancellation, and unconfirmed remote
  model use.

Memory Off and incognito tests stop memory search/add tools, prompt injection, extraction,
distillation, personal-insight generation, scheduled insight work, and Jarvis memory access before the
pipeline opens. Provenance shows owner/Project/persona use plus visible memory IDs and scopes.

The encrypted backup test saved an `andromeda_saved_searches` row, exported it inside an encrypted
`.alles-backup`, staged the restore, and recovered the saved search. Migration fixtures cover the new
conversation and saved-search migrations from historical schema prefixes.

## Optional SearXNG result

The reviewed candidate is:

- upstream version `2026.7.12-c19d86faa`;
- image digest `sha256:f433294b46a93564993c4371005341e013d94aa8ea4662d8ee521cd2cccb08e8`;
- license AGPL-3.0;
- bind address `127.0.0.1:8888`;
- private secret file, read-only root filesystem, dropped capabilities, no-new-privileges, bounded
  tmpfs/logs, 128-process limit, 512 MB memory limit, and 1 CPU.

Docker CLI 29.6.0 was installed, but `docker version` could not reach a daemon at
`/var/run/docker.sock`, and no supported alternative runtime was available. Therefore:

- `LIVE_SPIKE_VERIFIED` is false;
- install refuses before writing service data;
- the Server page says **optional SearXNG** and **managed install unavailable**;
- external HTTPS SearXNG and the existing provider chain are the shipped path;
- live startup, real resource use, JSON search, supervised restart, server restart, update, health
  failure, rollback, and uninstall were not claimed.

Unit tests do cover the exact candidate definition, ownership/tamper refusal, typed commands, failed
pull, failed health stop, simulated update rollback, explicit rollback, JSON response validation, and
uninstall-keep-data. These simulated checks are not a live container-runtime spike.

## Lint and dependency record

- Ruff code checks pass on all 35 changed Python files.
- The new and fully owned Phase 4 Python files pass Ruff format. Four older mixed-line-ending files
  touched by Phase 4 (`app.py`, `core/database.py`, `routes/chat.py`, and `routes/personas.py`) still
  trigger whole-file formatting; they were not broadly rewritten.
- Repository-wide Ruff remains an honest pre-existing baseline: 139 code errors and 203 files that
  would be reformatted.
- No Python, JavaScript, font, image, icon, or frontend-framework dependency was added. The optional
  upstream SearXNG container is not vendored; its version, digest, and AGPL-3.0 license are recorded
  above.
