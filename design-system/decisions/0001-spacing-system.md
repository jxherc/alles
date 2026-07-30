# 0001: six-step spacing system

Status: superseded by 0008

## decision

Use 4, 8, 12, 16, 24, and 32px for relationship spacing. Keep structural heights such as 36px rows, 44px rows, 44px touch targets, and the 52px app bar as separate size tokens.

## reason

The existing app accumulated many unrelated values. Six relationship steps are enough for compact daily UI while making cross-app alignment testable. Structural sizes solve a different problem and should not distort spacing choices.

## consequence

New arbitrary values need a documented system reason. Existing screens migrate only through approved, tested work; this decision is not a license for a broad mechanical rewrite.
