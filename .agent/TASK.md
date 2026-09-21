# current mission

## goal
Recover the previous conversation, repair confirmed broken or stale Alles UI, verify the real app, publish to the existing `dev-afterlife` branch, and propose a useful direction alongside DeepSeek Harness.

## requirements and boundaries
- Work in `/Users/jxh/Projects/alles`; preserve private owner data and existing edits.
- Keep FastAPI, SQLite, vanilla JavaScript/CSS, KOKUEN controls and the current 3 primary / 9 specialist navigation.
- Use owned temporary data for all mutable tests. The current user explicitly authorized the GitHub push.
- Preserve the existing census/lint edits until verified; retain the pre-existing untracked historical review.

## plan
1. Recover previous task, inspect local/remote history and baseline checks.
2. Reproduce and fix real UI failures; add focused regression coverage.
3. Verify full tests, rendered desktop/mobile, light/dark, keyboard and reduced motion.
4. Update current evidence, review outgoing commits, commit and push only dev-afterlife.
5. Document concrete rework options and distinguish proposed work from shipped fixes.

## completed
- Recovered `kokuen refine and testing`: July rebuild was published at 37242e6; ten later commits were local.
- Repaired legacy foreground colors, placeholders, light inline code, Files metadata and path wrapping,
  light Server values, malformed switch geometry, and Andromeda keyboard focus during switch saves.
- Updated stale test assertions, current-month Finance fixtures, portable lint discovery, census and docs.
- Separated formatter-only changes into ece2cf9, checking identical Python syntax trees.
- Wrote the personal operations inbox recommendation and two alternatives as a proposal, not shipped work.

## verification
- Python suite: 5,581 tests, passing with 7 skips; 22 focused tests pass after tooling repairs.
- JavaScript: 581 passing. Ruff lint and format pass. Canonical audit: 195 explained warnings, zero errors.
- Contrast: 184 surfaces / 2,876 observations in default light/dark themes at desktop and phone widths.
- Literal controls: 92 surfaces / 1,683 controls. Finished surfaces and final shared-switch gates pass.
- Populated Plan, Docs, Files, Library/Health, Finance/Vault/Server, first-run setup/Passwords and
  PWA offline/reconnect browser journeys pass on owned isolated data.
- Final Settings, Andromeda and Files screenshots inspected after fixes. See docs/repair-2026-09-21.md.

## in progress and remaining
- Commit the reviewed repairs and publish the authorized dev-afterlife branch; verify the remote hash.
- Hand off verified repairs, external limitations and the separate rework proposal.

## limitations
- Live provider, mail, bank and owner infrastructure integrations are not yet exercised in this run.
- No claim that historical acceptance notes prove the current tree.

## verification location
Fresh logs and screenshots are in the temporary directory recorded by `/tmp/alles-repair-current`.
