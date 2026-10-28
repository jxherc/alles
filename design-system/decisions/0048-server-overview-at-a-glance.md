# server overview: the machine at a glance

replaces the btop and neofetch look of the server monitor (the old 0010 palette exception).

## context

the overview copied a terminal monitor: monospace everywhere, meters drawn with `█░` glyphs in
`[ ]`, rainbow heat ramps, three graph boxes that stayed empty for the first minutes, an ascii
os logo and a color strip. the oct 28 visual pass flagged it in every review (code punctuation
as decoration, monospace labels, a spread of hues, empty boxes), and the owner asked for a
redesign that looks good. it also showed macOS's sealed system volumes as six disks, and its
percent for an apfs `/` came from psutil's count of that volume's own files: 18% on a container
that was 88% full.

## decision

- built to two real references, activity monitor and settings › storage: the shared type with
  tabular figures, the shared card, no glyph art.
- first a vitals strip: cpu, memory, storage, network. a value you read at a glance, one line of
  detail, and a two-minute line (storage gets a bar: fullness doesn't move by the second). until
  the window fills, the samples there are span the width, so a fresh page shows a line at once.
- then cores, memory and storage as bars (`role="meter"`), the busiest processes as a real
  table, and this machine and this browser as key and value lists.
- lines are soft text over a line-token baseline; upload is the categorical blue and dashed, so
  it never needs the color. only a value at 90% or more turns to the danger color.
- storage shows one row per container and leaves out `/System/Volumes/*`; fullness is everything
  that isn't free.
- the live mark is a still success-colored dot.

## kept

- the polling, history, outage and recovery states, the ids the gates use (`#box-cpu`,
  `#sys-shell`, `#system-host`), and the managed searxng controls.
