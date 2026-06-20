# ui-8b — main vault + change password (findings)

## Audit
Vaults each carry their own AES verifier; the `default` vault inherits the legacy master verifier, so it
is effectively the main vault. Entries AND attachments are encrypted with a key derived from the vault's
password — so a real "change password" must re-key both, and there was no way to do it.

## Fix
Exposed a `main` flag (default = main), labelled it in the manage panel with a helper line, added
click-to-rename, and built a change-password endpoint that re-keys entries + attachment blobs atomically
(compute-all-ciphertext, then write). For the main vault this is "change master password".

## Verify
Backend `test_vault_main_rekey.py` proves entries + attachments survive a re-key and the master flips.
Frontend `verify.py` unlocks on a fresh server, opens settings, sees the main badge + help, renames
inline, then changes the master password and confirms the old password 401s and the new one unlocks.
