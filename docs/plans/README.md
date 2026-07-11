# Alles plans

**Current stage: [Afterlife](afterlife/README.md)**

This folder contains several generations of plans. Older plans explain how Alles reached its current
state. They do not override the current direction.

## Read this first

1. [Specifications](../../specifications.md) — behavior that exists now.
2. [Afterlife overview](afterlife/README.md) — the current rebuild and why it exists.
3. [Afterlife design](afterlife/design.md) — the full product and architecture direction.
4. [Afterlife phases](afterlife/phases/README.md) — the implementation order.

## The stages

| # | Stage | Rough period | Status | Meaning |
|---|---|---|---|---|
| 1 | [The Skeleton](stages/01-the-skeleton.md) | June 3–18, 2026 | Historical | Aide became Alles and the first app structure was audited |
| 2 | [Flesh and Blood](stages/02-flesh-and-blood.md) | June 19–21, 2026 | Historical | The apps gained much more depth |
| 3 | [The Mirror](stages/03-the-mirror.md) | June 20–23, 2026 | Historical | Alles tried to make every surface look and behave like one product |
| 4 | [The Nervous System](stages/04-the-nervous-system.md) | June 22–28, 2026 | Historical | Migrations, memory, RAG, skills, automation, and intelligence grew |
| 5 | [Purgatory](stages/05-purgatory.md) | June 28–July 10, 2026 | Historical transition | Useful work split across branches and conflicting directions |
| 6 | [Afterlife](afterlife/README.md) | July 11, 2026 onward | **Current** | Keep the useful parts and give Alles one coherent new life |

The dates overlap because development moved quickly and some plan waves ran in parallel. These are
product eras, not releases.

## Rules

- Afterlife is the only active future-direction stage.
- When an older plan conflicts with Afterlife, Afterlife wins.
- `specifications.md` still wins for claims about what is currently shipped.
- `progress.json` is a historical execution ledger, not the current roadmap.
- A completed old task does not mean the whole product area is polished today.
- New plans go under `docs/plans/afterlife/`, not beside the historical files.

## Why the old files remain here

The historical plan files stay at their original paths for now. More than 250 progress, evidence, and
code references point to them. Moving them would break the audit trail without improving the product.
The stage pages above are the organization layer.

## Other planning records

- [Historical UI roadmap](../../ROADMAP.md) — The Mirror.
- [Historical task ledger](../../progress.json) — Flesh and Blood through The Mirror.
- [Personal RAG plan](../superpowers/plans/2026-06-22-personal-rag.md),
  [skill sources plan](../superpowers/plans/2026-06-22-skill-sources.md), and
  [skills UI plan](../superpowers/plans/2026-06-22-skills-ui-redesign.md) — The Nervous System.
- `alles-road-report.md`, `docs/roadmap/`, and `qa-status.md` are local Purgatory records. Some are
  intentionally ignored or untracked, so they may not exist in every clone.
