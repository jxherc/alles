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
    "bg": "#0a0a0a",
    "text": "#e8e6e3",
    "panel": "#0e0e0e",
    "faint": "#2e2e2e",
    "accent": "#818cf8",
}
LIGHT_BASE = {
    "bg": "#f5f4f1",
    "text": "#111111",
    "panel": "#efede9",
    "faint": "#d4d2ce",
    "accent": "#818cf8",
}

FONTS = ("sans", "mono", "serif")
DENSITIES = ("comfortable", "compact", "spacious")
PATTERNS = (
    "none", "dots", "grid", "crosshatch", "scanlines",
    "synapse", "rain", "snow", "embers", "fireflies", "bubbles", "starfield",
    "constellations", "sparkles", "petals", "matrix", "aurora", "waves",
)
COLOR_KEYS = ("bg", "text", "panel", "faint", "accent")


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
            "light" if _luminance(appearance.get("colors", {}).get("bg", "#0a0a0a")) > 0.5 else ""
        )
    accent = appearance.get("colors", {}).get("accent", "")
    return theme, accent


def effective(settings: dict) -> dict:
    """the appearance to serve: the stored object, or one synthesized from legacy fields."""
    obj = settings.get("appearance")
    if isinstance(obj, dict) and obj:
        return normalize(obj)
    return from_legacy(settings.get("theme", ""), settings.get("accent", ""))
