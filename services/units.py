"""units: one table for every unit alles converts, and the owner's display choices.

values are stored as entered with their unit and converted only for display and math. andromeda's
converter, habit logs and health all read these tables.
"""

import math

UNITS = {
    # length, in metres
    "mm": ("length", 0.001, "millimetres"),
    "cm": ("length", 0.01, "centimetres"),
    "m": ("length", 1, "metres"),
    "km": ("length", 1000, "kilometres"),
    "in": ("length", 0.0254, "inches"),
    "ft": ("length", 0.3048, "feet"),
    "yd": ("length", 0.9144, "yards"),
    "mi": ("length", 1609.344, "miles"),
    # mass, in grams
    "mg": ("mass", 0.001, "milligrams"),
    "g": ("mass", 1, "grams"),
    "kg": ("mass", 1000, "kilograms"),
    "oz": ("mass", 28.349523125, "ounces"),
    "lb": ("mass", 453.59237, "pounds"),
    "st": ("mass", 6350.29318, "stone"),
    "t": ("mass", 1_000_000, "tonnes"),
    # volume, in litres
    "ml": ("volume", 0.001, "millilitres"),
    "l": ("volume", 1, "litres"),
    "tsp": ("volume", 0.00492892, "teaspoons"),
    "tbsp": ("volume", 0.0147868, "tablespoons"),
    "floz": ("volume", 0.0295735, "fluid ounces"),
    "cup": ("volume", 0.236588, "cups"),
    "glass": ("volume", 0.236588, "glasses"),  # the "8 glasses a day" glass: 8 fl oz
    "qt": ("volume", 0.946353, "quarts"),
    "gal": ("volume", 3.78541, "gallons"),
    # speed, in metres per second
    "kmh": ("speed", 1 / 3.6, "km/h"),
    "mph": ("speed", 0.44704, "mph"),
    "ms": ("speed", 1, "m/s"),
    "kn": ("speed", 0.514444, "knots"),
    # data, in bytes
    "b": ("data", 1, "bytes"),
    "kb": ("data", 1000, "kilobytes"),
    "mb": ("data", 1e6, "megabytes"),
    "gb": ("data", 1e9, "gigabytes"),
    "tb": ("data", 1e12, "terabytes"),
    # time, in seconds
    "s": ("time", 1, "seconds"),
    "min": ("time", 60, "minutes"),
    "h": ("time", 3600, "hours"),
    "day": ("time", 86400, "days"),
    "week": ("time", 604800, "weeks"),
    # temperature is special
    "c": ("temperature", None, "°C"),
    "f": ("temperature", None, "°F"),
    "k": ("temperature", None, "kelvin"),
}
ALIASES = {
    "millimeter": "mm",
    "millimetre": "mm",
    "centimeter": "cm",
    "centimetre": "cm",
    "meter": "m",
    "metre": "m",
    "kilometer": "km",
    "kilometre": "km",
    "inch": "in",
    "inches": "in",
    "foot": "ft",
    "feet": "ft",
    "yard": "yd",
    "mile": "mi",
    "gram": "g",
    "kilogram": "kg",
    "kilo": "kg",
    "ounce": "oz",
    "pound": "lb",
    "lbs": "lb",
    "tonne": "t",
    "ton": "t",
    "milliliter": "ml",
    "millilitre": "ml",
    "liter": "l",
    "litre": "l",
    "teaspoon": "tsp",
    "tablespoon": "tbsp",
    "fl oz": "floz",
    "fluid ounce": "floz",
    "quart": "qt",
    "gallon": "gal",
    "glasses": "glass",
    "pounds": "lb",
    "kgs": "kg",
    "kilos": "kg",
    "km/h": "kmh",
    "kph": "kmh",
    "m/s": "ms",
    "knot": "kn",
    "knots": "kn",
    "byte": "b",
    "kilobyte": "kb",
    "megabyte": "mb",
    "gigabyte": "gb",
    "terabyte": "tb",
    "second": "s",
    "sec": "s",
    "minute": "min",
    "hour": "h",
    "hr": "h",
    "days": "day",
    "weeks": "week",
    "celsius": "c",
    "°c": "c",
    "fahrenheit": "f",
    "°f": "f",
    "kelvin": "k",
}


def find(word: str) -> str | None:
    word = word.strip().lower().rstrip(".")
    for candidate in (word, word.rstrip("s") if len(word) > 3 else word):
        if candidate in UNITS:
            return candidate
        if candidate in ALIASES:
            return ALIASES[candidate]
    return None


def _to_kelvin(value: float, unit: str) -> float:
    return {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[unit]


def _from_kelvin(value: float, unit: str) -> float:
    return {"c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32, "k": value}[unit]


def convert(amount: float, source: str, target: str):
    kind, factor, _ = UNITS[source]
    other_kind, other_factor, _ = UNITS[target]
    if kind != other_kind:
        return None
    if kind == "temperature":
        return _from_kelvin(_to_kelvin(amount, source), target)
    return amount * factor / other_factor


class UnitError(ValueError):
    """a unit the server can't use here; the message reaches the screen."""


def dimension(unit: str) -> str | None:
    found = canonical(unit)
    return UNITS[found][0] if found else None


def canonical(unit, kind: str | None = None) -> str | None:
    """the table's name for a unit, or None. kind "volume" reads a bare "oz" as fluid ounces."""
    word = str(unit or "").strip().lower()
    if not word:
        return None
    if kind == "volume" and word in ("oz", "ozs", "ounce", "ounces"):
        return "floz"
    found = find(word)
    if found and kind and UNITS[found][0] != kind:
        return None
    return found


def change(value: float, source: str, target: str) -> float:
    """value in source units, in target units. refuses units of different kinds."""
    a, b = canonical(source), canonical(target)
    if not a or not b or UNITS[a][0] != UNITS[b][0]:
        raise UnitError("these units can't be converted into each other")
    out = convert(float(value), a, b)
    if out is None or not math.isfinite(out):
        raise UnitError("these units can't be converted into each other")
    return out


def to_feet_inches(cm: float) -> tuple[int, float]:
    inches = round(cm / 2.54, 1)
    feet = int(inches // 12)
    return feet, round(inches - feet * 12, 1)


def from_feet_inches(feet: float, inches: float = 0) -> float:
    return (feet * 12 + inches) * 2.54


# the owner's display choices, one per thing measured. a habit or one exercise can override.
CHOICES = {
    "weight": ("lb", "kg"),
    "height": ("cm", "ft_in"),
    "distance": ("km", "mi"),
    "liquid": ("ml", "floz", "glass"),
    "body": ("cm", "in"),
    "temperature": ("c", "f"),
}
# pounds is the owner's rule (vault workout notes); the rest are metric
DEFAULTS = {
    "weight": "lb",
    "height": "cm",
    "distance": "km",
    "liquid": "ml",
    "body": "cm",
    "temperature": "c",
}
# what each choice measures, for checking an entered unit against it
KIND_OF = {
    "weight": "mass",
    "height": "length",
    "distance": "length",
    "liquid": "volume",
    "body": "length",
    "temperature": "temperature",
}


def preferences(saved) -> dict:
    """the display units in force: saved choices over the defaults; junk reads as the default."""
    saved = saved if isinstance(saved, dict) else {}
    return {key: saved[key] if saved.get(key) in CHOICES[key] else DEFAULTS[key] for key in CHOICES}


def check_preferences(patch) -> dict:
    """a validated change to the display units; unknown keys or choices are refused."""
    if not isinstance(patch, dict):
        raise UnitError("that unit choice doesn't exist")
    out = {}
    for key, value in patch.items():
        if key not in CHOICES or value not in CHOICES[key]:
            raise UnitError("that unit choice doesn't exist")
        out[key] = value
    return out


def for_display(value: float, unit: str, what: str, prefs: dict) -> tuple[float, str]:
    """a stored value in the owner's unit for `what` (weight, distance, ...). ft_in shows inches."""
    target = preferences(prefs)[what]
    target = "in" if target == "ft_in" else target
    return change(value, unit, target), target


# health entries that measure the body, and what their unit has to measure
BODY_KINDS = {"weight": "weight", "height": "height", "measurement": "body"}


def body_unit(kind: str, unit, saved=None) -> str:
    """a health entry's unit by its real name. weight, height and body measurements need a unit
    of the right kind (an empty one takes the owner's choice); body fat is always %. other
    kinds keep their text as written."""
    unit = str(unit or "").strip()
    if kind == "body_fat":
        return "%"
    what = BODY_KINDS.get(kind)
    if not what:
        return unit
    if not unit:
        unit = preferences(saved)[what]
        return "in" if unit == "ft_in" else unit
    found = canonical(unit, KIND_OF[what])
    if not found:
        raise UnitError("that unit doesn't measure this")
    return found
