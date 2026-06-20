# ui-8f — "how to load it" on its own line

Small layout fix: in the vault settings autofill blurb, the "how to load it →" link was inline at the end
of the paragraph. Split the paragraph into a block `.mv-autofill-text` span and put the link
(`.mv-autofill-link`, now with an external-link icon) on its own line beneath it via `display:block` +
`margin-top`.

Tests: `tests/test_vault_autofill_wrap.py` (2 source-contract) + `docs/evidence/ui-8f/verify.py`
(the link's top is below the text's bottom — its own line — 0 console errors).
