# Decision 0005: neutral focus and restrained active color

Decision

Choice: Use the neutral strong-line role for keyboard focus and reserve Alles purple for meaningful active or selected state.

Reason: A purple outline around an entire field or control is visually loud and makes focus look like product selection. The owner explicitly requires visible neutral focus across KOKUEN surfaces while keeping restrained purple as the active-state identity color.

Alternatives considered: Keep one shared focus/active token, or remove focus outlines. The shared token repeats the rejected purple rectangle, while removing focus would break keyboard access.

Consequences: Finished surfaces resolve `--k-focus` from the strong-line role. Active controls continue to use `--k-accent`. New components must not substitute the active token for focus.
