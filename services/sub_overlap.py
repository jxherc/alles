"""2f - subscription overlap warnings: flag paying for 2+ services in the same redundant category
(spotify + apple music = both music). distinct from /duplicates (same name/host tracked twice).
"""

import re

# known service -> redundant category. substring match on the normalized name.
SERVICE_CATEGORY = {
    "spotify": "music",
    "apple music": "music",
    "applemusic": "music",
    "tidal": "music",
    "youtube music": "music",
    "deezer": "music",
    "pandora": "music",
    "amazon music": "music",
    "netflix": "video",
    "hulu": "video",
    "disney": "video",
    "hbo": "video",
    "max": "video",
    "paramount": "video",
    "peacock": "video",
    "apple tv": "video",
    "prime video": "video",
    "dropbox": "cloud",
    "google one": "cloud",
    "google drive": "cloud",
    "icloud": "cloud",
    "onedrive": "cloud",
    "box": "cloud",
    "1password": "password",
    "lastpass": "password",
    "dashlane": "password",
    "bitwarden": "password",
    "chatgpt": "ai",
    "openai": "ai",
    "claude": "ai",
    "gemini": "ai",
    "copilot": "ai",
    "perplexity": "ai",
}


def _service_cat(name):
    n = re.sub(r"\s+", " ", (name or "").lower()).strip()
    for key, cat in SERVICE_CATEGORY.items():
        # whole-word match — substring over-matched ("box" inside dropbox, "max" inside anything)
        if re.search(r"\b" + re.escape(key) + r"\b", n):
            return cat
    return ""


_PER_MONTH = {"weekly": 52 / 12, "monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12}


def _own_monthly(sub):
    if sub.cycle == "custom":
        return (sub.price or 0.0) * 30.44 / max(1, sub.cycle_days or 30)
    return (sub.price or 0.0) * _PER_MONTH.get(sub.cycle, 1.0)


def overlaps(subs, monthly=None, currency=""):
    """groups of 2+ ACTIVE subs sharing a redundant category.

    `monthly` maps a sub's id to its monthly cost in `currency` (the totals currency). a sub
    with no rate there is listed but kept out of the group's total, never added in raw. with no
    `monthly` given, a group only gets a total when all its subs share one currency.
    """
    by_cat = {}
    for s in subs:
        if not s.active:
            continue
        cat = _service_cat(s.name)
        if cat:
            by_cat.setdefault(cat, []).append(s)
    out = []
    for cat, grp in by_cat.items():
        if len(grp) < 2:
            continue
        if monthly is None:
            codes = {(s.original_currency_code or s.currency or "").upper() for s in grp}
            same = len(codes) == 1
            total = round(sum(_own_monthly(s) for s in grp), 2) if same else None
            unit = codes.pop() if same else ""
            left = []
        else:
            total = round(sum(monthly[s.id] for s in grp if s.id in monthly), 2)
            unit = currency
            left = [s.id for s in grp if s.id not in monthly]
        out.append(
            {
                "category": cat,
                "subs": [{"id": s.id, "name": s.name, "price": s.price} for s in grp],
                "monthly_total": total,
                "currency": unit,
                "excluded": left,
            }
        )
    return sorted(out, key=lambda g: -(g["monthly_total"] or 0.0))
