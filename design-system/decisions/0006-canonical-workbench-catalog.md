# Decision 0006: one canonical workbench catalog

Decision

Choice: Product directories and app-pinning controls use the same nine workbenches in the same product
language: Plan, Inbox, Docs, Files, Library, Health, Finance, Vault, and Server. Retired app names are
compatibility routes, not visible catalog choices.

Reason: Apps and Home customization must not disagree about what an app is. Showing Calendar, Tasks,
Mail, or Money as independent pin choices after consolidating them into workbenches recreates the old
fragmented product and leaves settings controls disconnected from the real destinations.

Alternatives considered: keep separate legacy pin choices, let each surface maintain its own app list, or
remove Home app customization.

Consequences: Apps, Home pins, and Home Settings expose the same nine destinations. Saved legacy values
normalize to their canonical workbench without losing the intended section. New catalog surfaces must
reuse this set or explicitly record a later product decision that changes it.
