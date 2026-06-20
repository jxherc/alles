# ui-8f — autofill link wrap (findings)

## Audit
The "how to load it →" link trailed the autofill paragraph inline, so it wrapped awkwardly mid-sentence.

## Fix
Wrapped the blurb text in a block `.mv-autofill-text` and made the link a block element on its own line
(`.mv-autofill-link` with `margin-top` + an external-link icon).

## Verify
`verify.py` opens the vault settings and confirms the link's top is at/below the paragraph's bottom (its
own line, not the same line). 0 console errors.
