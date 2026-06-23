"""4c - smart albums: pure EXIF-date grouping + virtual albums (date range, keyword) over photo
dicts {id, taken_at, keywords}. no DB - routes pass in the rows."""


def _key(taken_at, period):
    t = str(taken_at or "")[:10]
    if len(t) < 7:
        return "unknown"
    return t if period == "day" else t[:7]  # month = YYYY-MM, day = YYYY-MM-DD


def group_by_period(photos, period="month"):
    """bucket photos by taken_at into {YYYY-MM (or -DD): [photo, ...]}; missing date -> 'unknown'."""
    out = {}
    for p in photos or []:
        out.setdefault(_key(p.get("taken_at"), period), []).append(p)
    return out


def in_range(photos, start, end):
    """photos whose taken_at date falls within [start, end] (inclusive, YYYY-MM-DD bounds)."""
    out = []
    for p in photos or []:
        d = str(p.get("taken_at") or "")[:10]
        if d and start <= d <= end:
            out.append(p)
    return out


def by_keyword(photos, kw):
    kw = (kw or "").strip().lower()
    if not kw:
        return list(photos or [])
    out = []
    for p in photos or []:
        kws = {k.strip().lower() for k in (p.get("keywords") or "").split(",") if k.strip()}
        if kw in kws:
            out.append(p)
    return out
