# Phase 10 real Settings UI QA - 2026-07-21

Scope: the owner-approved real language/region and About & Credits Settings foundation only. This is
not evidence for translated catalogs, the complete credits inventory, offline language typography,
or final release hardening.

Historical checkpoint: the English-only and incomplete-inventory state recorded here was later
superseded on the same date by the final Phase 10 localization and hardening evidence.

## Rendered evidence

The real app ran with a throwaway `ALLES_DATA` root on a non-conflicting port. The Playwright gate in
`tests/pw_phase10_localization_credits_real.py` passed at 1440 x 980 and 390 x 844 with service workers
blocked and reduced motion enabled. Captures were inspected at normal size and original resolution for
the dark localization pane, light Credits pane, and both phone layouts.

The gate proved:

- eight visible canonical language rows with only reviewed English selectable;
- automatic region/timezone defaults and custom listbox overrides;
- custom clock/week radio groups, keyboard navigation, Escape, and focus return;
- persistence through the real API and reload;
- manifest-driven Credits search, category tabs, detail selection, source link, and local xterm text;
- honest no-results, incomplete-coverage, request-failure, and retry states;
- dark and light theme tokens, 200 percent zoom, reduced motion, phone reflow, no horizontal overflow,
  44px phone targets, and a clean console apart from the one intentionally handled 503 resource line.

## Anti-slop law recheck

### Composition and hierarchy

- The work stays inside the approved existing Settings shell. It is not a hero, split hero, SaaS
  landing stack, pricing block, testimonial, CTA slab, footer composition, or fake app-window prop.
- Pane headings are 16px and section headings are 14px. There is no oversized duplicate app name,
  giant wordmark, multi-line display headline, kicker-plus-heading template, or decorative eyebrow.
- The desktop layout is one functional controls column plus one live/detail column. Phone layout is a
  deliberate single column with the live preview first. Corresponding controls share rows and do not
  become a ragged comparison grid.
- Real owner-facing information drives the composition: browser detection, persisted choices,
  language review states, validated dependency metadata, local notice text, and exact coverage gaps.
  There are no fake metrics, customers, logos, quotes, integrations, or decorative illustrations.

### Type, copy, and content boundaries

- No font was added. Existing neutral product type remains the UI voice; monospace is limited to the
  path, versions, and license text where it represents data.
- Copy is short and role-specific. It uses no eyebrow costume, decorative quotation marks, fabricated
  marketing, or AI attribution. The seven unfinished languages say catalog/layout/RTL review rather
  than pretending English fallback is translation.
- User content is not translated or rewritten. Paths and license text keep deliberate left-to-right
  isolation.
- The mistaken visible search label found during capture inspection was fixed to use the existing
  `sr-only` pattern.

### Color, surface, and effects

- The panes use the existing semantic KOKUEN page, panel, raised, hover, text, muted, line, accent,
  focus, and state tokens. Dark and light rendered captures were checked.
- There is no gradient, background glow, radial halo, candy aurora, glass, blur, grain over content,
  bloom, all-around shadow, hard shadow box, fake offset shadow, or cut-off glow.
- There are no icon tiles, logo boxes, gradient initials, tinted metadata pills, accent bars, grid
  backgrounds, countdown boxes, or floating cards.
- Borders separate real list rows, listboxes, and detail surfaces. They are structural rather than
  decorative hairlines. Color remains one continuous Settings surface without colliding accents or
  hard section seams.
- The only circular marks are the meaningful radio-state indicators. They are centered and do not
  contain off-axis text or icons.

### Controls and motion

- The new product choices contain no native select, checkbox, radio, or context menu. Buttons expose
  listbox, option, radiogroup, radio, and tab semantics with roving focus where applicable.
- Region and timezone support Enter/Space, arrows, Home/End, Escape, Tab close, selected state, and
  trigger focus return. Clock/week and Credits tabs support arrow navigation. Unreviewed language rows
  remain unavailable and explain why when activated.
- There is no hover lift/scale, underline-fill, button boop, animated fill, sun/moon toggle, pulsing
  status dot, entrance reveal, opacity-zero content, scroll-gated content, floating loop, or decorative
  parallax. Reduced motion leaves all content visible.
- Loading makes the workbench inert, save state is announced, no-results stays readable, API failure
  exposes retry, and retry restores the real manifest. Controls shown as interactive were exercised.

### Spacing, clipping, responsive behavior, and access

- Text has consistent gutters from the viewport, modal, list, and detail edges. Long paths, versions,
  and license text wrap or scroll inside their owned surface.
- No live control or label is clipped by a notch, fixed-height silhouette, overlap, or section seam.
  The list body intentionally scrolls within the existing Settings viewport.
- The first phone implementation failed because a lower-specificity `:where(...)` media override did
  not beat the desktop grid. The selector was corrected; a second similar target-size override was
  found and corrected. Fresh 390 x 844 evidence confirms one-column layout and 44px targets.
- At 200 percent zoom, the document and Settings content have no horizontal overflow. Desktop and
  phone captures show the preview/detail boundaries, row alignment, and text intact.
- Visible text/background contrast passed the automated 4.5:1 check in the real light pane. Focus,
  selected, unavailable, hover, loading, empty, error, and retry states are represented without glow
  or color-only ambiguity.

## Design-system result

The slice reuses the approved KOKUEN component language and semantic tokens, introduces no new global
visual primitive, adds no dependency or remote asset, and preserves the existing vanilla JavaScript
and CSS architecture. The real surface meets the applicable Product, Principles, Foundations,
Components, Patterns, Content, Accessibility, Responsive, Brand, Output Contract, and QA Checklist
requirements for this foundation.

At this checkpoint those delivery rows remained open. They are now closed by
`phase-10-localization-delivery-2026-07-21.md`, `phase-10-release-hardening-2026-07-21.md`,
`phase-10-aide-architecture-2026-07-21.md`, and `phase-10-final-audit-2026-07-21.md`.
