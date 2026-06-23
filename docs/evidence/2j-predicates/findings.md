# stage 2j - smart-mailbox predicate language - audit findings (2026-06-23)

## current state
- `parse_search_query` (mail.py:869) only extracts a FLAT spec (from/to/subject/before/after/text), and
  `advanced_search` ANDs every field. there is NO boolean logic: you cannot express
  `(from:x OR subject:y) AND NOT label:z`. saved searches store a name+query but inherit the same flat,
  all-AND semantics, so a "smart mailbox" can't really be smart.
- snooze (snooze/snoozed) + the scheduled/outbox list endpoints already exist - the "Scheduled view" and
  "snooze picker" are frontend surfaces over endpoints that are already there. the missing BACKEND piece
  is the predicate language.
- exercised: searching "from:bob OR from:alice" treats "OR" as a free-text word and returns nothing.

## the gap
- a real boolean predicate language: field:value terms + AND / OR / NOT + parentheses, evaluated over a
  message (cache-answerable fields: from, subject, to, text, label, is:unread|read|flagged|muted).
- an endpoint to run a predicate over an account's cached messages (a true smart mailbox).

## fix
- new `services/mail_predicate.py`: `parse(query)` -> a small AST (recursive descent: or > and(implicit
  too) > not > atom/group); `evaluate(node, msg)` -> bool; `match(query, msgs)` -> filtered list. quoted
  values supported (subject:"team lunch"); operators case-insensitive; empty query matches all.
- endpoint GET /mail/smart-search/{aid}?q=... -> evaluate over the cache (loads cached msg dicts, filters
  in python so labels/flags are answerable).

the parser + evaluator are pure + heavily tested (terms, implicit/explicit AND, OR, NOT, grouping,
is:/label:, quotes, case, empty, list filtering).
