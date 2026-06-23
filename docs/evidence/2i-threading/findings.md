# stage 2i - RFC-5322 threading - audit findings (2026-06-23)

## current state
- threading is SUBJECT-BASED: `mail.threads` buckets by `normalize_subject(...).lower()` (mail.py:855),
  and mute keys off the normalized subject (mail_cache.py:189). so a reply whose subject was edited, or
  a forward ("Fwd: ..."), or two unrelated mails that happen to share a subject, thread WRONG.
- the real threading headers ARE fetched in the single-message path (`fetch_message` returns message_id
  + references, mail.py:506/542) but:
  - the INBOX list fetch only pulls FROM SUBJECT DATE LIST-UNSUBSCRIBE - no Message-ID / In-Reply-To /
    References (mail.py:~287).
  - `CachedMessage` has NO message_id / in_reply_to / references / thread_id columns, so nothing is
    persisted and no reference graph can be built.
- exercised: a 3-message reply chain where msg 3 changed the subject does NOT group under subject
  threading.

## the gap
- capture Message-ID / In-Reply-To / References on the inbox fetch + persist on CachedMessage.
- a pure RFC-5322 threading pass: union-find over message-id <-> (in-reply-to + references) so a chain
  threads regardless of subject edits. assign a stable thread_id.
- compute + store thread_id at cache time.

## fix
- migration m0005: add message_id, in_reply_to, references, thread_id (TEXT) to cached_messages.
- `services/mail.py`: `_ref_ids(s)` (parse <id> tokens) + `thread_messages(msgs)` -> each msg gains a
  stable `thread_id` (canonical = lexicographically-smallest id in its connected component; messages
  with no headers fall back to a uid-keyed singleton thread).
- `fetch_inbox`: add MESSAGE-ID IN-REPLY-TO REFERENCES to the HEADER.FIELDS fetch + row dict.
- `mail_cache.save`: persist the 3 headers + run thread_messages over the batch and store thread_id.

the threading function is pure + fully testable (chain, subject-change, unrelated split, header-less
fallback, references-only, order-independence). persistence verified via save + re-query.
