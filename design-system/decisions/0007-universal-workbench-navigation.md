# Decision 0007: universal workbench navigation state

Decision

Choice: Every canonical specialist workbench uses the same accessible sidebar toggle and one shared
persisted expanded or collapsed preference. The app identity and Home action remain available in the
full-width header when the navigation rail is hidden.

Reason: A fixed rail without a toggle wastes working space and makes the nine consolidated apps behave
like unrelated products. One setting makes navigation predictable across Plan, Inbox, Docs, Files,
Library, Health, Finance, Vault, and Server.

Alternatives considered: Independent state per app, a permanently fixed rail, or hiding the toggle on
small screens. Per-app state is surprising, a fixed rail cannot yield space, and a missing mobile toggle
breaks the universal contract.

Consequences: New canonical workbenches must use `data-specialist-sidebar-toggle`, expose accurate
`aria-expanded` and `aria-controls` state, preserve the 44px target, and reuse the shared storage key.
