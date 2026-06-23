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
        if key in n:
            return cat
    return ""


def overlaps(subs):
    """groups of 2+ ACTIVE subs sharing a redundant category."""
    by_cat = {}
    for s in subs:
        if not s.active:
            continue
        cat = _service_cat(s.name)
        if cat:
            by_cat.setdefault(cat, []).append(s)
    out = []
    for cat, grp in by_cat.items():
        if len(grp) > 1:
            out.append(
                {
                    "category": cat,
                    "subs": [{"id": s.id, "name": s.name, "price": s.price} for s in grp],
                    "monthly_total": round(sum(s.price or 0.0 for s in grp), 2),
                }
            )
    return sorted(out, key=lambda g: -g["monthly_total"])
