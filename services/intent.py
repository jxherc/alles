"""1f - intent prediction. fuse the current signals (1-now) + the latest composer text into
1-2 likely next-step suggestions aide can surface, so it anticipates instead of only reacting.
deterministic heuristics - no extra model call.
"""

_MONEY_KW = ("budget", "spend", "spent", "money", "expense", "expenses", "cost", "groceries")
_TRAVEL_KW = ("trip", "travel", "flight", "hotel", "vacation", "holiday")
_TRAVEL_EVENT_KW = ("trip", "flight", "travel", "vacation", "airport", "boarding")


def predict_suggestions(db, *, message="", session=None, limit=2):
    from services import signals

    sigs = signals.gather(db)
    by_cat = {}
    for sg in sigs:
        by_cat.setdefault(sg["category"], []).append(sg)

    cands = []  # (priority, suggestion)

    def _u(cat):
        return max((s["urgency"] for s in by_cat.get(cat, [])), default=0)

    if by_cat.get("task"):
        cands.append(
            (_u("task"), {"label": "review your overdue tasks", "link": "tasks", "kind": "task"})
        )
    if by_cat.get("sub"):
        cands.append(
            (_u("sub"), {"label": "check upcoming renewals", "link": "subs", "kind": "sub"})
        )
    events = by_cat.get("event", []) + by_cat.get("day_event", [])
    if events:
        cands.append(
            (
                max(s["urgency"] for s in events),
                {"label": "see your schedule", "link": "calendar", "kind": "event"},
            )
        )
        for s in events:
            blob = (str(s.get("title", "")) + " " + str(s.get("detail", ""))).lower()
            if any(k in blob for k in _TRAVEL_EVENT_KW):
                cands.append(
                    (82, {"label": f"plan for {s['title']}", "link": "calendar", "kind": "travel"})
                )
                break

    m = (message or "").lower()
    if any(k in m for k in _MONEY_KW):
        cands.append(
            (90, {"label": "show this month's spending", "link": "money", "kind": "money"})
        )
    if any(k in m for k in _TRAVEL_KW):
        cands.append((85, {"label": "plan your trip", "link": "calendar", "kind": "travel"}))

    seen, out = set(), []
    for _, c in sorted(cands, key=lambda x: -x[0]):
        if c["label"] in seen:
            continue
        seen.add(c["label"])
        out.append(c)
        if len(out) >= limit:
            break
    return out
