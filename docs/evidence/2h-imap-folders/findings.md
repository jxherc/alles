# stage 2h - IMAP folder ops (move/copy/soft-delete) - audit findings (2026-06-23)

## current state
- `services/mail.py` had write ops set_seen/set_flag/mark_seen (uid STORE flags) but NO folder move.
- `routes/mail.py:archive` guarded its move with `if hasattr(mailsvc, "move_message")` - a dead branch,
  because `move_message` did not exist. so the archive button only updated the LOCAL cache; the message
  was never moved server-side. exercised: archived a message, confirmed it still sat in the IMAP INBOX.
- no copy, no server-side delete, no generic "move to folder" endpoint for rule-based or manual moves.

## the gap
- a real `move_message(acct, uid, dest, src)` over the live IMAP pool (reusing _imap/_release_imap),
  using UID MOVE where the server supports it and the portable COPY + \\Deleted + EXPUNGE fallback
  otherwise.
- `copy_message` + `delete_message` (soft-delete = flag \\Deleted + expunge).
- wire the archive button to the real move; add a generic /mail/move/{aid} endpoint.

## fix
- `services/mail.py`: `_has_move(M)`, `_do_move(M, uid, dest, src)` (pure given a connection, so it's
  testable against a fake IMAP), `move_message` / `copy_message` / `delete_message` wrappers that pull
  + release a pooled connection.
- `routes/mail.py`: drop the hasattr guard (call move_message directly, still best-effort try/except);
  add POST /mail/move/{aid} (move on server + drop from the source cache view).

tested against a FakeIMAP recording select/uid/expunge calls: MOVE path, COPY-fallback path, source
select, dest targeting, byte/str uid, connection release on success AND on error.
