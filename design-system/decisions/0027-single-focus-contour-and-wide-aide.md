# single focus contour and wider Aide workspace

## context

The focused Aide composer drew its structural border and a second outline with
a 2px gap. Toolbar focus also highlighted the whole composer while drawing the
button's own indicator. Shared controls repeated the detached-outline geometry.
The 760px conversation cap left roughly 356px of unused space on each side of
the composer at a 1440px viewport.

## decision

- Focus stays visible. Shared outlines use `--k-focus-offset: -2px` to overlay the
  existing edge instead of adding a detached frame. Existing inward offsets and
  meaningful selected, error, drag, and pane boundaries keep their behavior.
- A bounded text field has one focus owner. The composer, command input, Inbox
  recipient field, and archive search suppress the inner field's outline. Their
  owner exposes text focus; sibling actions retain their own indicator without
  highlighting the whole wrapper.
- Existing single-line Home and Andromeda focus treatments stay intact. Forced
  colors retain an actual outline where shadows cannot serve as an indicator.
- Current Aide uses the available pane width with 24px desktop and 16px phone
  gutters. Messages, the composer, and saved status share the same baseline.
- Ordinary prose blocks and user messages retain a 68ch reading measure. Code,
  tables, and task results may use the wider workspace. This does not change the
  message model, send behavior, scroll ownership, or 44px control targets.
- Coding uses its available detail-pane width and the same gutters. Its 620px
  connection form and Call's centered 680px status surface remain intentionally
  measured; neither is a wide working editor.
- Call has room for its visible label at the existing header action. The label
  is not hidden to make the compact layout fit.
- Below 360px, the header wraps in DOM order: Aide and mode choices first,
  utility actions second. Full labels and 44px targets take precedence over
  squeezing every action into one row; 390px and larger retain one row.

## verification

Source regressions cover shared inset geometry, field/action focus ownership,
the wider workspace, bounded prose, and Call's intrinsic width. Real browser
verification must compare rest, text focus and toolbar focus; check Settings,
Inbox recipients and archive search; and cover desktop, phone, 200% zoom,
themes, forced colors, reduced motion, overflow and keyboard use. Browser data
must remain synthetic; Call checks must not open real media or providers.
