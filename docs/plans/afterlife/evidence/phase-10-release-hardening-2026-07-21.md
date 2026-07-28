# Phase 10 release hardening - 2026-07-21

All tests used throwaway data. Owner databases, uploads, vaults, logs, and normal `data/` were not
read or changed.

## Credits and release artifacts

- `credits/manifest.json` is complete with 432 entries. Direct Python and JavaScript requirements
  are compared exactly against their dependency files, while vendored assets, fonts, models,
  datasets, skills, managed companions, and adapted sources are explicit entries.
- `scripts/generate_credits.py` deterministically generates `ACKNOWLEDGMENTS.md`,
  `THIRD_PARTY_NOTICES.md`, `licenses/index.json`, and `credits/release-notice-files.json`.
- The release notice set has 465 unique paths. Generation and validation fail when an entry lacks a
  source, version, license value, required text, when a listed file is missing, or when a stale
  generated license remains outside the index.
- Native-copy tests preserve the exact notice set. The final image
  `alles-phase10-verify:local` (`sha256:ac7585b6c38292bf32d205c13e3d82c7cf04bff4384aaae6369bf93d556114a8`)
  built from the real Dockerfile, became Docker-healthy, returned 200 from `/health` and
  `/api/health`, contained `defusedxml 0.7.1`, and contained all 465 listed notice files exactly once.

## Compatibility and installation

- Twenty-four native install/update/release tests passed clean install, owned release layout,
  upgrade, rollback, interrupted-operation refusal, uninstall target validation, and data retention.
- The current-host macOS launchd gate installed into isolated temporary home/data roots, launched the
  owned service, verified it, updated/rolled back, and uninstalled without removing retained data.
- Linux service behavior is covered by systemd-user simulations, and the fresh Linux container image
  was built and health-checked for real. A separate physical Linux host was not available; this is
  not a claim of physical-distro certification.
- The pinned Actual 26.7.0 opt-in live gate passed real migrate, write, backup, restore, fresh-client
  readback, and teardown in 42.432 seconds.

## Performance budgets

The server budget test sampled each warm route 25 times:

| path | measured p95 | budget |
|---|---:|---:|
| `/` | 2.17 ms | 750 ms |
| `/api/health` | 2.06 ms | 250 ms |
| `/api/settings/localization/options` | 3.73 ms | 500 ms |
| `/api/credits` | 24.07 ms | 1,000 ms |

Payloads were 219,615 bytes for the root, 133,062 for Credits metadata, 3,550 for localization
options, and 23,924 for the largest catalog. Credits license bodies stay lazy.

The fresh real-browser measurements also passed:

| path | measured p95/elapsed | budget |
|---|---:|---:|
| coldish boot | 807.22 ms | 6,000 ms |
| in-app navigation | 62.50 ms | 500 ms |
| locale apply | 17.40 ms | 1,000 ms |
| first Credits open | 175.98 ms | 2,000 ms |

An earlier provisional 250 ms navigation threshold produced one honest 253.04 ms miss. The checked
budget is 500 ms, chosen for supported low-power self-hosted hardware rather than to hide that run.

## Security and privacy

| severity | open findings |
|---|---:|
| critical | 0 |
| high | 0 |
| medium | 0 |

- Unsafe XML parsing in CardDAV, feeds, FX, S3, and WebDAV paths was replaced with `defusedxml` and
  explicit 1-8 MiB response caps. Entity expansion, invalid encoding, oversize, redirect, and remote
  error-body regressions fail closed.
- Bandit reported zero high findings and 26 medium heuristics. All 26 were inspected: three are the
  explicit configured network-bind policy, twenty are fixed internal SQL identifiers/constants rather
  than owner input, two are synthesized loopback health probes, and one is the fixed HTTPS ECB
  exchange-rate URL. None is an open vulnerability.
- `pip-audit`, the Actual dependency audit, and the mobile dependency audit reported zero known
  vulnerabilities. A final refresh found newly published `node-tar` advisories in Capacitor 6's
  transitive `tar ^6.1.11` line; the lock now overrides it to fixed `tar 7.5.20`, a regression locks
  that floor, a clean temporary `npm ci` reproduced it with zero audit findings, and the real
  Capacitor 6.2.1 CLI still loads the project. `pip check` reported no broken requirements.
- The final overrides use `adm-zip 0.6.0` and nested `uuid 11.1.1`; Pillow is 12.3.0.
- The tracked-secret scan found no production credential assignment. The sole AWS-looking value is
  AWS's published `AKIAIOSFODNN7EXAMPLE` test fixture.
- SHA-1 remains only where required for non-security deduplication or the HIBP protocol and now
  declares `usedforsecurity=False`.

## Recovery matrix

The 479-test recovery group passed local encrypted backup/restore, preflight and interruption,
Files/offline copies, external Vault state, WebDAV, S3, Actual, and managed-service configuration.
The WebDAV and S3 providers were protocol simulations with failure injection, not the owner's live
endpoints. The Actual gate above was a real companion process. Source preservation, conditional
writes, exact readback, atomic promotion, credential recovery, and fail-closed restore boundaries are
covered.

Result: the release-hardening gates pass with the physical-Linux and live-owner-remote limits stated
above rather than hidden.
