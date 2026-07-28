# Task model routing

Checked 2026-07-27. Generated from `features/task-routing.json` and the live
acceptance scenarios in `features/registry.json`. Edit those sources, then run
`python scripts/generate_task_routing.py`. Do not hand-edit this file.

## Benchmark basis

OpenAI documents Sol as the quality-first tier and Terra as the everyday balance of capability and cost. It recommends the lowest reasoning effort that passes representative evaluations and reserves xhigh or max for measured gains on difficult work. No comparable public numeric benchmark table for Sol, Terra, and Luna was found in the official documentation, so this plan does not invent one.

The route is therefore a hypothesis that must be calibrated on representative Alles work.
Keep a cheaper route when it passes the same acceptance gate. Measure: task success, regressions introduced, verification completeness, wall time, input tokens, output tokens, reasoning tokens, cost per successful task.

Sources:

- https://learn.chatgpt.com/docs/models#choosing-sol-terra-and-luna
- https://learn.chatgpt.com/docs/models#pick-a-reasoning-effort
- https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters
- https://developers.openai.com/api/docs/guides/deployment-checklist#choose-a-gpt-56-model

## Routing totals

- registered feature groups: 26
- routed delivery and verification tasks: 120
- `gpt-5.6-sol` / `high`: 25
- `gpt-5.6-sol` / `xhigh`: 26
- `gpt-5.6-terra` / `high`: 54
- `gpt-5.6-terra` / `low`: 3
- `gpt-5.6-terra` / `medium`: 12

`max` is not a starting route. Escalate to `gpt-5.6-sol` / `max` only when one of these
conditions is recorded:

- the primary route fails twice with the same unresolved cause
- a security or recovery invariant remains ambiguous after targeted proof
- a destructive network or lifecycle scenario produces conflicting evidence

## Every registered task

| feature | kind | task | model | effort |
| --- | --- | --- | --- | --- |
| setup-security.owner-setup | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| setup-security.owner-setup | verification | fresh owner setup | `gpt-5.6-terra` | `high` |
| setup-security.owner-setup | verification | recent-owner reauthentication | `gpt-5.6-sol` | `high` |
| setup-security.owner-setup | verification | resume interrupted setup | `gpt-5.6-sol` | `high` |
| home.capture-and-navigation | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `medium` |
| home.capture-and-navigation | verification | capture from Home | `gpt-5.6-terra` | `medium` |
| home.capture-and-navigation | verification | open every workbench | `gpt-5.6-terra` | `medium` |
| home.capture-and-navigation | verification | use Home at phone width | `gpt-5.6-sol` | `high` |
| aide.conversation-and-execution | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| aide.conversation-and-execution | verification | complete an Auto task | `gpt-5.6-terra` | `high` |
| aide.conversation-and-execution | verification | arm Full Access | `gpt-5.6-sol` | `xhigh` |
| aide.conversation-and-execution | verification | inspect a redacted audit | `gpt-5.6-sol` | `high` |
| aide.selectable-questions | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `medium` |
| aide.selectable-questions | verification | answer by pointer | `gpt-5.6-terra` | `high` |
| aide.selectable-questions | verification | answer by keyboard | `gpt-5.6-terra` | `high` |
| aide.selectable-questions | verification | reload and resume | `gpt-5.6-terra` | `high` |
| aide.selectable-questions | verification | answer through Discord | `gpt-5.6-sol` | `high` |
| andromeda.cited-search | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| andromeda.cited-search | verification | search and open citations | `gpt-5.6-terra` | `high` |
| andromeda.cited-search | verification | toggle verification | `gpt-5.6-terra` | `high` |
| andromeda.cited-search | verification | render failed checks honestly | `gpt-5.6-sol` | `high` |
| plan.tasks-calendar | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| plan.tasks-calendar | verification | create and move a task | `gpt-5.6-terra` | `high` |
| plan.tasks-calendar | verification | keyboard board navigation | `gpt-5.6-terra` | `high` |
| plan.tasks-calendar | verification | create and delete an event | `gpt-5.6-terra` | `high` |
| inbox.mail-and-contacts | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| inbox.mail-and-contacts | verification | connect a disposable mailbox | `gpt-5.6-terra` | `high` |
| inbox.mail-and-contacts | verification | send a test message | `gpt-5.6-terra` | `high` |
| inbox.mail-and-contacts | verification | edit a test contact | `gpt-5.6-terra` | `high` |
| docs.documents-and-journal | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| docs.documents-and-journal | verification | edit and recover a document | `gpt-5.6-terra` | `high` |
| docs.documents-and-journal | verification | rename with backlink preservation | `gpt-5.6-terra` | `high` |
| docs.documents-and-journal | verification | migrate and roll back a journal entry | `gpt-5.6-sol` | `high` |
| files-photos.locations-and-media | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| files-photos.locations-and-media | verification | browse Alles and Connected | `gpt-5.6-terra` | `high` |
| files-photos.locations-and-media | verification | copy move and roll back | `gpt-5.6-sol` | `xhigh` |
| files-photos.locations-and-media | verification | open Gallery and return Home | `gpt-5.6-terra` | `high` |
| files-photos.locations-and-media | verification | resolve a vault conflict | `gpt-5.6-sol` | `xhigh` |
| library.reading-and-news | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `high` |
| library.reading-and-news | verification | save and open a page | `gpt-5.6-terra` | `medium` |
| library.reading-and-news | verification | add and update a book | `gpt-5.6-terra` | `medium` |
| library.reading-and-news | verification | deliver a cited news brief | `gpt-5.6-sol` | `high` |
| health.logs-and-habits | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `high` |
| health.logs-and-habits | verification | log a synthetic measurement | `gpt-5.6-terra` | `high` |
| health.logs-and-habits | verification | complete a habit | `gpt-5.6-terra` | `high` |
| health.logs-and-habits | verification | inspect empty and partial summaries | `gpt-5.6-terra` | `high` |
| finance.actual-ledger | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| finance.actual-ledger | verification | reconcile a disposable ledger | `gpt-5.6-sol` | `high` |
| finance.actual-ledger | verification | import statement fixtures | `gpt-5.6-terra` | `high` |
| finance.actual-ledger | verification | undo an import | `gpt-5.6-sol` | `high` |
| finance.bank-connectors | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| finance.bank-connectors | verification | connect Plaid sandbox | `gpt-5.6-terra` | `high` |
| finance.bank-connectors | verification | deduplicate transactions | `gpt-5.6-terra` | `high` |
| finance.bank-connectors | verification | expire and reconnect consent | `gpt-5.6-sol` | `high` |
| finance.bank-connectors | verification | disconnect and revoke | `gpt-5.6-terra` | `high` |
| passwords.vault-and-browser | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| passwords.vault-and-browser | verification | pair the extension | `gpt-5.6-terra` | `high` |
| passwords.vault-and-browser | verification | fill an exact test site | `gpt-5.6-terra` | `high` |
| passwords.vault-and-browser | verification | reject a mismatched origin | `gpt-5.6-sol` | `xhigh` |
| passwords.vault-and-browser | verification | revoke a browser | `gpt-5.6-terra` | `high` |
| server.management | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| server.management | verification | inspect neofetch and btop | `gpt-5.6-terra` | `high` |
| server.management | verification | restart a disposable service | `gpt-5.6-terra` | `high` |
| server.management | verification | reject an unsafe policy edit | `gpt-5.6-sol` | `xhigh` |
| server.management | verification | perform update rollback | `gpt-5.6-sol` | `xhigh` |
| server.adguard-home | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| server.adguard-home | verification | prepare without activation | `gpt-5.6-terra` | `high` |
| server.adguard-home | verification | activate in isolation | `gpt-5.6-sol` | `xhigh` |
| server.adguard-home | verification | inspect query statistics | `gpt-5.6-terra` | `high` |
| server.adguard-home | verification | roll back DNS | `gpt-5.6-sol` | `xhigh` |
| server.nginx-proxy-manager | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| server.nginx-proxy-manager | verification | prepare without Docker | `gpt-5.6-terra` | `high` |
| server.nginx-proxy-manager | verification | activate in isolation | `gpt-5.6-sol` | `xhigh` |
| server.nginx-proxy-manager | verification | create a proxy host | `gpt-5.6-terra` | `high` |
| server.nginx-proxy-manager | verification | roll back service | `gpt-5.6-sol` | `xhigh` |
| integrations.owner-connectors | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| integrations.owner-connectors | verification | pair a Discord owner | `gpt-5.6-terra` | `high` |
| integrations.owner-connectors | verification | connect and revoke MCP | `gpt-5.6-terra` | `high` |
| integrations.owner-connectors | verification | test a signed webhook | `gpt-5.6-sol` | `xhigh` |
| integrations.owner-connectors | verification | disconnect an endpoint | `gpt-5.6-terra` | `high` |
| integrations.model-authentication | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| integrations.model-authentication | verification | connect Gemini OAuth | `gpt-5.6-terra` | `high` |
| integrations.model-authentication | verification | connect and revoke an API key | `gpt-5.6-terra` | `high` |
| integrations.model-authentication | verification | discover CLIProxyAPI models | `gpt-5.6-terra` | `high` |
| integrations.model-authentication | verification | show unsupported OAuth honestly | `gpt-5.6-sol` | `high` |
| automation.schedules-and-actions | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| automation.schedules-and-actions | verification | create and pause a schedule | `gpt-5.6-terra` | `high` |
| automation.schedules-and-actions | verification | resume after restart | `gpt-5.6-terra` | `high` |
| automation.schedules-and-actions | verification | inspect a failed action | `gpt-5.6-terra` | `high` |
| automation.schedules-and-actions | verification | cancel a run | `gpt-5.6-terra` | `high` |
| localization.regional-settings | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `medium` |
| localization.regional-settings | verification | use automatic region | `gpt-5.6-terra` | `medium` |
| localization.regional-settings | verification | override formats | `gpt-5.6-terra` | `medium` |
| localization.regional-settings | verification | switch reviewed languages | `gpt-5.6-terra` | `medium` |
| localization.regional-settings | verification | restart and preserve choices | `gpt-5.6-terra` | `medium` |
| localization.credits | delivery | re-audit and repair implementation | `gpt-5.6-terra` | `medium` |
| localization.credits | verification | search named inspirations | `gpt-5.6-terra` | `low` |
| localization.credits | verification | open a local notice | `gpt-5.6-terra` | `low` |
| localization.credits | verification | show unavailable notice honestly | `gpt-5.6-terra` | `low` |
| accessibility.interface-contract | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| accessibility.interface-contract | verification | complete flows by keyboard | `gpt-5.6-terra` | `high` |
| accessibility.interface-contract | verification | verify dialog focus return | `gpt-5.6-terra` | `high` |
| accessibility.interface-contract | verification | test responsive and zoom states | `gpt-5.6-sol` | `high` |
| accessibility.interface-contract | verification | test reduced motion and themes | `gpt-5.6-terra` | `high` |
| extension-mobile.pwa-and-extension | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `high` |
| extension-mobile.pwa-and-extension | verification | install PWA | `gpt-5.6-terra` | `high` |
| extension-mobile.pwa-and-extension | verification | exercise offline and reconnect | `gpt-5.6-sol` | `high` |
| extension-mobile.pwa-and-extension | verification | pair and revoke extension | `gpt-5.6-terra` | `high` |
| extension-mobile.pwa-and-extension | verification | test mobile package | `gpt-5.6-terra` | `high` |
| backup-recovery.lifecycle | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| backup-recovery.lifecycle | verification | fresh macOS install | `gpt-5.6-terra` | `high` |
| backup-recovery.lifecycle | verification | fresh Linux VM install | `gpt-5.6-terra` | `high` |
| backup-recovery.lifecycle | verification | recover interrupted update | `gpt-5.6-sol` | `xhigh` |
| backup-recovery.lifecycle | verification | uninstall preserving data | `gpt-5.6-terra` | `high` |
| backup-recovery.lifecycle | verification | restore and roll back | `gpt-5.6-sol` | `xhigh` |
| developer-interfaces.api-cli | delivery | re-audit and repair implementation | `gpt-5.6-sol` | `xhigh` |
| developer-interfaces.api-cli | verification | issue and revoke API token | `gpt-5.6-sol` | `high` |
| developer-interfaces.api-cli | verification | call OpenAI-compatible API | `gpt-5.6-sol` | `high` |
| developer-interfaces.api-cli | verification | reject scope escalation | `gpt-5.6-sol` | `xhigh` |
| developer-interfaces.api-cli | verification | run CLI tests | `gpt-5.6-sol` | `high` |
