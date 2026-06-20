# 5e audit — mail: labels & push

No labels / categorize / IDLE exists. CachedMessage has no labels column. Live :8847: /by-label,
/category, /labels all 404. Labels + the Primary/Social/Promotions heuristic are cache-side and
fully testable; IMAP IDLE is best-effort (needs a live server) so only the heuristic + a live-poll
flag are tested. Plan: docs/plans/5e.md.
