# Phase 10 Aide capability and architecture reconciliation - 2026-07-21

## Aide capability matrix

The focused Aide capability group passed 154 tests. A checked row means a working tool and test, or
an explicit intentional exclusion. Generic shell/file access is not counted as an app-owned API.

| app | working capability | explicit exclusion or boundary |
|---|---|---|
| Home | Aide summaries feed the existing Home brief/attention paths | no model tool for rearranging Home |
| Plan | list/add/complete Tasks; list/create/delete Calendar events | task update/move is not exposed |
| Docs | read, write, search, and note tools; selected-doc context can be summarized | private selected-doc context fails closed |
| Files / Photos | approved Project file tools operate within their allowed roots | no app-owned Files/Photos organizer tool |
| Finance | read accounts, transactions, budgets, and summaries | no model bank-password access, purchase, import, category, or budget mutation |
| Inbox | list/read/send mail and list/add contacts | sending requires approval; delete/update is excluded |
| Library | books, read-later, watch, habits, and recall tools | bulk tag/organize remains excluded |
| Health | health log and summary tools | hidden by default and in Projects; requires explicit General-context health grant |
| Passwords | none | exact-site fill remains owner-mediated browser flow; model tools are forbidden |
| Server | generic explicitly approved shell boundary only | no app-owned service-control model tool |
| Andromeda | standalone search and save paths work | no Aide handoff tool; intentional product boundary |

The Health correction is security-significant: `health_log` and `health_summary` now require both
General context and the explicit `agent_health_access_granted` setting. The capability is absent by
default rather than merely denied after exposure.

## Architecture and trust reconciliation

Runtime enumeration found 838 routes: 821 `/api` routes, two `/v1` routes, and 15 public/static
routes. The locked digest is
`5eae1bb74681fe66f39fc678386a2021de483a14fb288cedf77126a932ce17ec`.
Phase 10 adds the localization options, Credits list, and lazy Credits text routes. Twenty-nine route,
inventory, and trust-map tests passed.

`specifications.md`, `docs/plans/afterlife/current-trust-map.md`, the route snapshot, mapped-table
inventory, registered jobs, service/process ownership, data roots, connectors, and managed companions
were reconciled to the implementation. Planned behavior is not presented as shipped. The localization
manifest separately records owner/third-party/legacy UI boundaries, and the Credits API returns only
validated manifest metadata plus an explicitly requested local text.

Result: every Aide app row has working proof or an explicit exclusion, and the implementation,
architecture narrative, route digest, trust map, and release docs agree.
