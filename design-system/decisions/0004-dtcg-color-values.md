# Decision 0004: schema-valid color values

Decision

Choice: Store primitive colors as DTCG `srgb` color objects with explicit components and alpha.

Reason: The token files declare the DTCG 2025.10 schema, whose color values are structured objects rather than CSS hex strings.

Alternatives considered: Remove the schema declaration or keep project-specific hex values. Both would weaken interoperability and make the declared contract misleading.

Consequences: Consumers must resolve primitive color objects before emitting CSS. Semantic aliases stay unchanged, and contrast tests read the normalized sRGB components directly.
