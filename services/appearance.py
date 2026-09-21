"""
appearance — the advanced theme model. stores a single object in settings.json under
`appearance`: base colors, font, density, background pattern + effect, frosted glass,
and saved custom themes. pure normalize/validate here (unit-tested); the route just
persists it and keeps the legacy `theme`/`accent` settings in sync so older code that
reads those still works.
"""

import re

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DARK_BASE = {
    "bg": "#090909",
    "text": "#eceae6",
    "panel": "#0d0d0d",
    "raised": "#171717",
    "hover": "#141414",
    "soft": "#b9b5b0",
    "muted": "#85817c",
    "quiet": "#7d7974",
    "faint": "#292929",
    "lineStrong": "#3a3a3a",
    "accent": "#9298ff",
}
LIGHT_BASE = {
    "bg": "#f4f3f0",
    "text": "#242321",
    "panel": "#eeece8",
    "raised": "#e4e1dc",
    "hover": "#e9e7e2",
    "soft": "#55514c",
    "muted": "#68635e",
    "quiet": "#746e68",
    "faint": "#d5d0c9",
    "lineStrong": "#bbb4ac",
    "accent": "#5960c7",
}

# pre-kokuen-remap default palettes. a stored appearance whose colors still match
# these exactly was never customized, so it upgrades to the new palette instead of
# pinning the old drifted values forever.
_OLD_BASES = (
    (
        "dark",
        {
            "bg": "#0a0a0a",
            "text": "#e8e6e3",
            "panel": "#0e0e0e",
            "faint": "#2e2e2e",
            "accent": "#818cf8",
        },
        DARK_BASE,
    ),
    (
        "light",
        {
            "bg": "#f5f4f1",
            "text": "#111111",
            "panel": "#efede9",
            "faint": "#d4d2ce",
            "accent": "#818cf8",
        },
        LIGHT_BASE,
    ),
)

FONTS = ("sans", "mono", "serif")
DENSITIES = ("comfortable", "compact", "spacious")
PATTERNS = (
    "none",
    "dots",
    "grid",
    "crosshatch",
    "scanlines",
    "synapse",
    "rain",
    "snow",
    "embers",
    "fireflies",
    "bubbles",
    "starfield",
    "constellations",
    "sparkles",
    "petals",
    "matrix",
    "aurora",
    "waves",
)
COLOR_KEYS = (
    "bg",
    "text",
    "panel",
    "raised",
    "hover",
    "soft",
    "muted",
    "quiet",
    "faint",
    "lineStrong",
    "accent",
)


def _is_hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX.match(v))


def _clamp(v, lo, hi, default):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def default_appearance() -> dict:
    return {
        "preset": "dark",
        "colors": dict(DARK_BASE),
        "font": "sans",
        "density": "comfortable",
        "bgPattern": "none",
        "frosted": False,
        "effect": {"color": "", "intensity": 1, "size": 1},
        "customThemes": {},
    }


def normalize(obj) -> dict:
    """fill missing keys with defaults, validate enums, clamp numbers, drop bad hex."""
    d = default_appearance()
    if not isinstance(obj, dict):
        return d

    if isinstance(obj.get("preset"), str) and obj["preset"]:
        d["preset"] = obj["preset"]

    colors = obj.get("colors")
    if isinstance(colors, dict):
        for k in COLOR_KEYS:
            if _is_hex(colors.get(k)):
                d["colors"][k] = colors[k]

    if obj.get("font") in FONTS:
        d["font"] = obj["font"]
    if obj.get("density") in DENSITIES:
        d["density"] = obj["density"]
    if obj.get("bgPattern") in PATTERNS:
        d["bgPattern"] = obj["bgPattern"]
    if "frosted" in obj:
        d["frosted"] = bool(obj["frosted"])

    eff = obj.get("effect")
    if isinstance(eff, dict):
        d["effect"]["color"] = eff["color"] if _is_hex(eff.get("color")) else ""
        d["effect"]["intensity"] = _clamp(eff.get("intensity"), 0, 1, 1)
        d["effect"]["size"] = _clamp(eff.get("size"), 0.2, 3, 1)

    ct = obj.get("customThemes")
    if isinstance(ct, dict):
        d["customThemes"] = ct

    return d


def from_legacy(theme, accent) -> dict:
    """build an appearance object from the old `theme`/`accent` settings."""
    d = default_appearance()
    if theme == "light":
        d["preset"] = "light"
        d["colors"] = dict(LIGHT_BASE)
    if _is_hex(accent):
        d["colors"]["accent"] = accent
    return d


def _luminance(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return 0.0
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def to_legacy(appearance: dict) -> tuple[str, str]:
    """derive (theme, accent) for back-compat with code reading the old settings."""
    preset = appearance.get("preset")
    if preset == "light":
        theme = "light"
    elif preset == "dark":
        theme = ""
    else:  # custom — decide by background brightness
        theme = (
            "light" if _luminance(appearance.get("colors", {}).get("bg", "#090909")) > 0.5 else ""
        )
    accent = appearance.get("colors", {}).get("accent", "")
    return theme, accent


def _upgrade_legacy_default(a: dict) -> dict:
    """stored colors that still equal a pre-remap default preset were never a real
    choice — swap them for the current palette. anything else is user customization."""
    colors = a.get("colors")
    if not isinstance(colors, dict):
        return a
    for preset, old, new in _OLD_BASES:
        if a.get("preset") == preset and all(colors.get(k) == v for k, v in old.items()):
            a = dict(a)
            merged = dict(new)
            merged.update({k: v for k, v in colors.items() if k not in old})
            a["colors"] = merged
            return a
    return a


def effective(settings: dict) -> dict:
    """the appearance to serve: the stored object, or one synthesized from legacy fields."""
    obj = settings.get("appearance")
    if isinstance(obj, dict) and obj:
        return _upgrade_legacy_default(normalize(obj))
    return from_legacy(settings.get("theme", ""), settings.get("accent", ""))
