# 0008: align Alles with the KOKUEN v3 contract

Status: accepted

## decision

Adopt the KOKUEN v3 spacing scale of 0, 4, 8, 12, 16, 24, 32, 48, and 64px, expose portable
`--ui-*` semantic aliases from the Alles runtime, and treat standalone HTML starters as optional design
tools rather than approval gates.

Keep the established split DTCG token sources in `design-system/tokens/` instead of duplicating them in
one product-local file. Validate the three files as one alias graph.

## reason

The universal skill now distinguishes card padding, header separation, sections, and major page blocks.
Alles' older numeric runtime names encoded values rather than ordered steps, which made portable KOKUEN
components ambiguous. The repository rules also make the real rendered application the delivery gate,
so a mockup cannot remain a mandatory precondition.

## alternatives considered

- Renumber existing variables without migrating consumers. Rejected because it would silently increase
  many current gaps.
- Keep the six-step product scale. Rejected because it would drift from the shared KOKUEN component
  contract and leave no semantic section or major-block token.
- Copy the generic KOKUEN starter token file into Alles. Rejected because it would duplicate the richer
  product-specific dark/light token sources.

## consequences

Existing `--k-space-6` consumers migrate to `--k-space-5`, and existing `--k-space-8` consumers migrate
to `--k-space-6`, preserving their 24px and 32px geometry. New section and major-block work may use
steps 7 and 8. The prior `space.region` semantic remains as a 32px compatibility alias. Product-specific
page gutters remain documented semantic tokens. Historical Afterlife plans continue to describe the
approval process used at the time; current design-system sources govern new work.
