# color with meaning

## context

After decision 0019 made every ordinary selected state neutral, the owner found the product too
colorless. The reference was Google search in dark mode: "google is great because it has color —
the blue just shows stuff that are links." What works there is that each color answers a question.
Blue means "this opens something". The spark and the highlighted phrase mean "ai wrote this". A site's
own favicon tells you whose page it is. Everything else stays calm grey.

## decision

Color tells you what a thing is or does. It's never decoration. Grey stays the base, and 0019 still
holds: an ordinary selected or on state is neutral.

| token | dark | light | means |
|---|---|---|---|
| `--link` | `#8ab4f8` | `#1a0dab` | opens a page: result titles, links in written content |
| `--link-visited` | `#c58af9` | `#681da8` | a link already opened |
| `--ai` | the accent | the accent | ai wrote or is doing this: spark, highlighted answer, live run |
| `--info` | link | link | a neutral notice |
| `--success` / `--warning` / `--danger` | green / signal / error | same | state, as before |
| `--cat-blue` … `--cat-green` | 6 hues | 6 hues | tell data apart |

`--k-link`, `--k-link-visited`, `--k-ai`, `--k-info` and `--k-warning` mirror them in the KOKUEN
runtime. `--success`, `--warning` and `--danger` are aliases of the old `--green`, `--signal` and
`--error`. Before this, a few rules pointed at `--danger`, `--warning` or `--k-warning`, which didn't
exist: journal and feed load errors weren't red, and Plan's high-priority dot had no color.

Every link and categorical value has at least 4.5:1 contrast against the page, panel and raised
surfaces in its theme (`tests/js/semantic_color.test.mjs`). `--ai` follows the owner's accent, so
a theme preset changes it. It's used for marks and tinted highlights, not body text.

Visited purple and the ai accent are both purplish, but they never sit on the same element. One
is a text color on a link and the other is a mark or a tint behind words.

### where it shows

- **Andromeda**: result titles, news titles, source cards, citations and "did you mean" are link
  blue, and visited purple once opened. Each site's favicon shows in its real colors on a light disc,
  the way Google does it, so a black mark still reads on the dark theme. This replaces 0025's "no
  favicon tiles": the disc carries the site's identity, which the grey initials didn't. The ai overview
  gets a spark in `--ai`. The decisive words of the answer (the bold phrase the prompt asks for) get
  an `--ai` tint, as the key-answer marker already did.
- **Andromeda tools**: weather marks per sky (amber sun, blue rain, pale snow, grey cloud and fog),
  with the rain chance in `--info`. F1 standings and results show each team's broadcast color as a
  thin bar. Teams without a known color keep the space but show no bar. The periodic table keeps its
  family tints.
- **Written content**: links in chat answers, docs previews, embeds, the coding assistant,
  artifacts, compare, journal reflections, the reader's fallback link, news digests, skill sources,
  contact map links and mail bodies are link blue. Mail renders in its own white page, so it uses the
  light values.
- **AI actions**: the sparkle on "suggest" (mail), "reflect" (journal) and "smart" (photos) is
  `--ai`; the label stays grey. Aide's live run dot, running status and live thinking rail use `--ai`.
- **Money**: each category hashes to one of the six hues (`categoryHue` in `static/js/color.js`).
  It shows as the bar in "spending by category", the spending-cap bar and a dot before the category
  in transactions and caps. An over-cap bar still turns danger red.
- **Toasts**: `info` toasts use `--info`.

## not changed

- 0019's neutral selection, KOKUEN's neutral focus, and every switch track.
- The calendar's twelve event colors are stored per event by name, so they stay as they are.
  Habit colors are stored as hex per habit. The server monitor keeps its own ramps (0010).
- Model provider logos keep their brand colors.
- No gradients, glows, colored boxes or purple-filled chips were added.

## verification

Before and after screenshots of Andromeda (all results, weather, f1, periodic table) on desktop
and phone in both themes, on an isolated server with mocked search. Contrast is measured per token
against page, panel and raised in each theme.
