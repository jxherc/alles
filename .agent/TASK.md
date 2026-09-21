# current mission

## goal
Repair the failed GitHub Actions run on dev-afterlife and continue until the full remote run succeeds.
The preceding UI repair and product proposal remain below as context.

## current follow-up
- GitHub run 35584846959 failed three source contracts in tests/test_ui_controls.py. They still
  expect the old switch target to be its track and the knob to move to 16px.
- The earlier full Python run preceded the final switch edits; focused coverage missed this module.
- Plan: reproduce all three failures locally, align the contracts with the approved separated
  44px target / 42px track, verify focused and real-browser behavior, push and await the full CI result.
- Reproduced all three failures locally. Repaired the track selector, active-track background and
  knob endpoint assertions, and added an explicit transparent 44px target contract.
- Verification: all 24 focused UI/design/lint tests pass; Ruff lint/format and the real-browser
  pointer/Space/focus/reduced-motion switch gate pass on owned desktop/phone fixtures.
- Full remote acceptance is the GitHub `tests` check attached to this follow-up commit on dev-afterlife.
  Its completed result is authoritative; the earlier full-suite evidence below predates the switch fix.

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

## publication and handoff
- Repairs committed as b1d4c2f; formatting checkpoint ece2cf9.
- Authorized push to origin/dev-afterlife succeeded. The remote hash was verified as
  b1d4c2ff0170bcbd16574aa6964fb0a2be5d4933 after publication, including the ten previously local commits.
- Implementation and isolated verification are complete for the confirmed defects in this repair.
  External limitations below remain; a future product rework is proposed separately and is not implemented.
- The pre-existing untracked alles-full-review.md was preserved and excluded from publication.

## limitations
- Live provider, mail, bank and owner infrastructure integrations are not yet exercised in this run.
- No claim that historical acceptance notes prove the current tree.

## verification location
Fresh logs and screenshots are in the temporary directory recorded by `/tmp/alles-repair-current`.
