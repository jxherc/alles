"""special answers above andromeda's results: calculator, units, currency, time, weather,
dictionary, translation and the periodic table.

detect() is plain pattern matching and never leaves the machine. resolve() computes the answer
locally, or asks one free public service from the server (never the owner's browser), or, for
translation, the owner's answer model.
"""

from __future__ import annotations

import ast
import asyncio
import html
import math
import operator
import re
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from services.elements import BY_NAME, BY_SYMBOL, CATEGORY_LABELS, ELEMENTS

# ── calculator ──
_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": round,
    "exp": math.exp,
}
_CONSTS = {"pi": math.pi, "e": math.e}
_MATHY = re.compile(r"^[\d\s.+\-*/%^()a-z,×÷]+$")


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(arg) for arg in node.args[:2]])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("not arithmetic")


def calculate(text: str, *, loose: bool = False):
    """a number for plain arithmetic, None for anything else. loose lets a bare number through,
    for the calculator's own keys."""
    expression = text.lower().strip().rstrip("=?").strip()
    percent = re.fullmatch(r"([\d.]+)\s*%\s*of\s*([\d.]+)", expression)
    if percent:
        return float(percent.group(1)) / 100 * float(percent.group(2))
    if not _MATHY.match(expression) or not (
        loose or re.search(r"[\d)]\s*[-+*/%^×÷]|[a-z]+\(|sqrt", expression)
    ):
        return None
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    expression = re.sub(r"(sqrt|sin|cos|tan|log|ln|abs|exp)\s+([\d.]+)", r"\1(\2)", expression)
    try:
        value = _eval(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, complex) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return value


def _number(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.6g}" if abs(value) >= 1e-4 else f"{value:.4g}"


# ── units ──
_UNITS = {
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
_ALIASES = {
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


def _unit(word: str) -> str | None:
    word = word.strip().lower().rstrip(".")
    for candidate in (word, word.rstrip("s") if len(word) > 3 else word):
        if candidate in _UNITS:
            return candidate
        if candidate in _ALIASES:
            return _ALIASES[candidate]
    return None


def _to_kelvin(value: float, unit: str) -> float:
    return {"c": value + 273.15, "f": (value - 32) * 5 / 9 + 273.15, "k": value}[unit]


def _from_kelvin(value: float, unit: str) -> float:
    return {"c": value - 273.15, "f": (value - 273.15) * 9 / 5 + 32, "k": value}[unit]


def convert(amount: float, source: str, target: str):
    kind, factor, _ = _UNITS[source]
    other_kind, other_factor, _ = _UNITS[target]
    if kind != other_kind:
        return None
    if kind == "temperature":
        return _from_kelvin(_to_kelvin(amount, source), target)
    return amount * factor / other_factor


# ── time ──
_CITY_ZONES = {
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "la": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "boston": "America/New_York",
    "miami": "America/New_York",
    "montreal": "America/Toronto",
    "ottawa": "America/Toronto",
    "beijing": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "japan": "Asia/Tokyo",
    "uk": "Europe/London",
    "england": "Europe/London",
    "china": "Asia/Shanghai",
    "korea": "Asia/Seoul",
    "germany": "Europe/Berlin",
    "france": "Europe/Paris",
    "spain": "Europe/Madrid",
    "italy": "Europe/Rome",
    "australia": "Australia/Sydney",
    "dubai": "Asia/Dubai",
    "utc": "UTC",
    "gmt": "UTC",
}
_ZONES_BY_CITY = {
    zone.rsplit("/", 1)[-1].replace("_", " ").lower(): zone
    for zone in available_timezones()
    if "/" in zone and not zone.startswith(("Etc/", "SystemV/"))
}


def zone_for(place: str) -> str | None:
    place = re.sub(r"\s+", " ", place.strip().lower().rstrip("?"))
    return _CITY_ZONES.get(place) or _ZONES_BY_CITY.get(place)


# ── translation ──
# the translator's languages (libretranslate's models), in picker order
from services.andromeda_translate import CODES as _TRANSLATE_CODES  # noqa: E402

LANGUAGES = tuple(sorted(_TRANSLATE_CODES))
_LANGUAGE_WORDS = {name: name for name in LANGUAGES} | {
    "mandarin": "chinese",
    "cantonese": "chinese",
    "farsi": "persian",
}
_LANG = "(" + "|".join(sorted(_LANGUAGE_WORDS, key=len, reverse=True)) + ")"
_CURRENCIES = {
    "usd": "us dollar",
    "eur": "euro",
    "gbp": "british pound",
    "jpy": "japanese yen",
    "cny": "chinese yuan",
    "cad": "canadian dollar",
    "aud": "australian dollar",
    "chf": "swiss franc",
    "hkd": "hong kong dollar",
    "inr": "indian rupee",
    "krw": "south korean won",
    "mxn": "mexican peso",
    "brl": "brazilian real",
    "sek": "swedish krona",
    "nok": "norwegian krone",
    "dkk": "danish krone",
    "nzd": "new zealand dollar",
    "sgd": "singapore dollar",
    "zar": "south african rand",
    "try": "turkish lira",
    "pln": "polish zloty",
    "thb": "thai baht",
    "idr": "indonesian rupiah",
    "huf": "hungarian forint",
    "czk": "czech koruna",
    "ils": "israeli shekel",
    "php": "philippine peso",
    "myr": "malaysian ringgit",
    "ron": "romanian leu",
    "isk": "icelandic krona",
}
_CURRENCY_SIGNS = {"$": "usd", "€": "eur", "£": "gbp", "¥": "jpy", "₹": "inr", "₩": "krw"}
_CURRENCY_NAMES = {
    "dollar": "usd",
    "us dollar": "usd",
    "american dollar": "usd",
    "canadian dollar": "cad",
    "australian dollar": "aud",
    "euro": "eur",
    "pound": "gbp",
    "british pound": "gbp",
    "pound sterling": "gbp",
    "yen": "jpy",
    "yuan": "cny",
    "rmb": "cny",
    "renminbi": "cny",
    "rupee": "inr",
    "won": "krw",
    "franc": "chf",
    "swiss franc": "chf",
    "peso": "mxn",
    "real": "brl",
    "baht": "thb",
    "rand": "zar",
    "zloty": "pln",
    "lira": "try",
    "shekel": "ils",
    "ringgit": "myr",
    "krona": "sek",
}


def _currency(word: str) -> str | None:
    word = str(word or "").strip().lower().rstrip(".")
    if word in _CURRENCIES:
        return word
    for candidate in (word, word[:-1] if word.endswith("s") else word):
        if candidate in _CURRENCY_NAMES:
            return _CURRENCY_NAMES[candidate]
    return None


# a bare "what is it" is a question, not a dictionary lookup
_NOT_WORDS = {
    "it",
    "this",
    "that",
    "up",
    "new",
    "happening",
    "going",
    "today",
    "trending",
    # big questions people ask, not words they need spelled out
    "love",
    "life",
    "god",
    "time",
    "art",
    "truth",
}

# the default pair a converter opens on, by what it converts
_UNIT_DEFAULTS = {
    "length": ("m", "ft"),
    "distance": ("km", "mi"),
    "weight": ("kg", "lb"),
    "mass": ("kg", "lb"),
    "temperature": ("c", "f"),
    "volume": ("l", "gal"),
    "speed": ("kmh", "mph"),
    "data": ("gb", "mb"),
    "time": ("h", "min"),
}
# "kg to" with no target picks the usual other side
_UNIT_PARTNERS = {
    "km": "mi",
    "mi": "km",
    "m": "ft",
    "ft": "m",
    "cm": "in",
    "in": "cm",
    "mm": "in",
    "kg": "lb",
    "lb": "kg",
    "g": "oz",
    "oz": "g",
    "c": "f",
    "f": "c",
    "k": "c",
    "l": "gal",
    "gal": "l",
    "ml": "floz",
    "floz": "ml",
    "kmh": "mph",
    "mph": "kmh",
}

_TOOL_SUFFIX = r"(?: tool| online| app)?"


def _tool(low: str) -> dict | None:
    """a request for a tool by name: the tool opens empty and does nothing on its own."""
    plain = re.sub(r"^(?:open|show(?: me)?|launch|use)\s+(?:an? |the )?", "", low)
    plain = re.sub(r"^(?:online |free |simple )", "", plain)
    if re.fullmatch(rf"(?:calculator|calc|scientific calculator){_TOOL_SUFFIX}", plain):
        return {"kind": "calc", "expression": ""}
    found = re.fullmatch(
        rf"(?:({'|'.join(_UNIT_DEFAULTS)}) )?(?:unit |units |measurement )?(?:converter|conversion|convertor|calculator){_TOOL_SUFFIX}|convert units",
        plain,
    )
    if found and plain not in ("converter", "conversion", "convertor"):
        source, target = _UNIT_DEFAULTS[found[1] or "length"]
        return {"kind": "units", "amount": 1.0, "from": source, "to": target}
    if re.fullmatch(
        rf"(?:currency|money|exchange rate|forex|fx)(?: converter| conversion| calculator| exchange| rates?)?{_TOOL_SUFFIX}",
        plain,
    ):
        return {"kind": "currency", "amount": 1.0, "from": "usd", "to": "eur"}
    if re.fullmatch(rf"(?:google )?(?:translate|translator|translation){_TOOL_SUFFIX}", plain):
        return {"kind": "translate", "text": "", "from": "", "to": "english"}
    if re.fullmatch(
        rf"(?:english )?(?:dictionary|define|definition|thesaurus){_TOOL_SUFFIX}", plain
    ):
        return {"kind": "define", "word": "", "focus": "synonyms" if "thesaurus" in plain else ""}
    if re.fullmatch(rf"(?:spell ?check(?:er)?|spelling(?: check(?:er)?)?){_TOOL_SUFFIX}", plain):
        return {"kind": "spell", "word": ""}
    if re.fullmatch(
        r"(?:an? |the )?(?:interactive |chemistry |chemical )?(?:periodic tables?(?: of(?: the)?"
        r" elements| elements| online)?|periodic chart|ptable|"
        r"(?:the )?table of(?: the)? elements|elements? table|chemical elements)",
        plain,
    ):
        return {"kind": "periodic"}
    if re.fullmatch(
        r"world ?clock|time ?zones?(?: converter| map)?|clock|what time is it|current time|time now|local time",
        plain,
    ):
        return {"kind": "clock"}
    if re.fullmatch(
        r"(?:weather|forecast|weather forecast)(?: today| now| this week| tomorrow)?", plain
    ):
        return {"kind": "weather", "place": ""}
    if re.fullmatch(
        rf"(?:timer|countdown timer|set (?:a )?timer|start (?:a )?timer|kitchen timer){_TOOL_SUFFIX}",
        plain,
    ):
        return {"kind": "timer", "mode": "timer", "seconds": 0, "start": False}
    if re.fullmatch(r"pomodoro(?: timer)?", plain):
        return {"kind": "timer", "mode": "timer", "seconds": 25 * 60, "start": False}
    if re.fullmatch(rf"(?:stopwatch|stop watch|start (?:a )?stopwatch){_TOOL_SUFFIX}", plain):
        return {"kind": "timer", "mode": "stopwatch", "seconds": 0, "start": False}
    if re.fullmatch(rf"(?:dice|dice roller|die roller){_TOOL_SUFFIX}", plain):
        return {"kind": "random", "mode": "dice", "count": 1, "sides": 6, "roll": False}
    if re.fullmatch(
        rf"(?:random number(?: generator)?|rng|number generator|random number picker){_TOOL_SUFFIX}",
        plain,
    ):
        return {"kind": "random", "mode": "number", "min": 1, "max": 10, "roll": False}
    if re.fullmatch(
        rf"(?:colou?r picker|colou?r selector|hex colou?r picker|rgb colou?r picker|colou?r wheel|hex to rgb|rgb to hex){_TOOL_SUFFIX}",
        plain,
    ):
        return {"kind": "color", "value": ""}
    return None


_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?|s|secs?|seconds?)\b")


def _seconds(text: str) -> int:
    total = 0.0
    for amount, unit in _DURATION.findall(text):
        total += float(amount) * (
            3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        )
    return int(total)


def _timer(low: str) -> dict | None:
    found = re.fullmatch(
        r"(?:set (?:a |the )?|start (?:a |the )?)?(?:timer|countdown)(?: for| of)? (.+)|"
        r"(?:set (?:a |the )?|start (?:a |the )?)?(.+?) (?:timer|countdown)",
        low,
    )
    if not found:
        return None
    words = found[1] or found[2]
    if not re.fullmatch(r"(?:(?:\d+(?:\.\d+)?)\s*[a-z]+\s*(?:and\s*)?)+", words):
        return None
    seconds = _seconds(words)
    if 0 < seconds <= 24 * 3600:
        return {"kind": "timer", "mode": "timer", "seconds": seconds, "start": True}
    return None


_DICE_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _random(low: str) -> dict | None:
    if re.fullmatch(r"(?:flip|toss) (?:a |the )?coin|coin (?:flip|toss)|heads or tails", low):
        return {"kind": "random", "mode": "coin", "roll": True}
    found = re.fullmatch(
        r"roll (?:(a|one|two|three|four|five|six|\d{1,2}) )?(?:(\d{0,2})d(\d{1,3})|dice|die|d(\d{1,3}))(?: dice)?",
        low,
    )
    if found:
        count = found[2] or found[1] or "1"
        count = _DICE_WORDS.get(count, None) or int(count or 1)
        sides = int(found[3] or found[4] or 6)
        if 1 <= count <= 10 and 2 <= sides <= 100:
            return {"kind": "random", "mode": "dice", "count": count, "sides": sides, "roll": True}
    found = re.fullmatch(
        r"(?:pick |generate |give me )?(?:a )?random (?:number|integer)(?: between| from)? (-?\d+)(?: and | to |-| - )(-?\d+)|"
        r"pick a number (?:between|from) (-?\d+) (?:and|to) (-?\d+)",
        low,
    )
    if found:
        low_value, high_value = int(found[1] or found[3]), int(found[2] or found[4])
        if low_value > high_value:
            low_value, high_value = high_value, low_value
        if high_value - low_value <= 10**12:
            return {
                "kind": "random",
                "mode": "number",
                "min": low_value,
                "max": high_value,
                "roll": True,
            }
    return None


_HEX = re.compile(r"#?([0-9a-f]{6}|[0-9a-f]{3})")


def _color(low: str) -> dict | None:
    value = re.sub(r"\b(?:colou?r|hex|code)\b", " ", low).strip()
    value = re.sub(r"\s+", " ", value)
    found = _HEX.fullmatch(value)
    # "bad" or "decade" are words: without its # a hex needs "hex", or "color" and six digits
    if found and (value.startswith("#") or "hex" in low or (value != low and len(found[1]) == 6)):
        digits = found[1]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return {"kind": "color", "value": "#" + digits}
    found = re.fullmatch(r"rgb\(?\s*(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})\s*\)?", value)
    if found and all(int(part) <= 255 for part in found.groups()):
        return {
            "kind": "color",
            "value": "#" + "".join(f"{int(part):02x}" for part in found.groups()),
        }
    return None


def _element_query(low: str) -> dict | None:
    facts = {
        "atomic number": "number",
        "proton number": "number",
        "number of protons": "number",
        "atomic mass": "mass",
        "atomic weight": "mass",
        "molar mass": "mass",
        "mass": "mass",
        "symbol": "symbol",
        "chemical symbol": "symbol",
        "element symbol": "symbol",
        "group": "group",
        "period": "period",
        "category": "category",
    }
    fact_words = "(" + "|".join(sorted(facts, key=len, reverse=True)) + ")"
    found = re.fullmatch(rf"(?:what is )?(?:the )?{fact_words} (?:of|for) ([a-z]+)", low)
    if found and found[2] in BY_NAME:
        return {"kind": "element", "number": BY_NAME[found[2]]["number"], "fact": facts[found[1]]}
    found = re.fullmatch(rf"([a-z]+)(?:'s)? {fact_words}", low)
    if found and found[1] in BY_NAME:
        return {"kind": "element", "number": BY_NAME[found[1]]["number"], "fact": facts[found[2]]}
    found = re.fullmatch(
        r"(?:periodic table|element) ([a-z]+)|([a-z]+) (?:periodic table|element)|element (?:number )?(\d{1,3})",
        low,
    )
    if found:
        word = found[1] or found[2]
        if word in BY_NAME:
            return {"kind": "element", "number": BY_NAME[word]["number"], "fact": ""}
        if word in BY_SYMBOL:
            return {"kind": "element", "number": BY_SYMBOL[word]["number"], "fact": ""}
        if found[3] and 1 <= int(found[3]) <= len(ELEMENTS):
            return {"kind": "element", "number": int(found[3]), "fact": ""}
    found = re.fullmatch(r"what element is ([a-z]{1,2}|\d{1,3})", low)
    if found:
        key = found[1]
        if key.isdigit() and 1 <= int(key) <= len(ELEMENTS):
            return {"kind": "element", "number": int(key), "fact": ""}
        if key in BY_SYMBOL:
            return {"kind": "element", "number": BY_SYMBOL[key]["number"], "fact": ""}
    if low in BY_NAME and len(low) > 2:
        return {"kind": "element", "number": BY_NAME[low]["number"], "fact": ""}
    return None


# currency codes that are also everyday words count only next to an amount
_WORDY_CODES = {"try", "php"}


def _money(low: str) -> dict | None:
    value = re.sub(r"^convert ", "", low)
    found = re.fullmatch(
        r"([$€£¥₹₩])?\s*([\d.,]+)?\s*([a-z][a-z ]*?)?\s+(?:to|in|into|=|vs)\s+([a-z][a-z ]*?)(?: exchange rate| rate)?",
        value,
    )
    if found:
        source = _currency(found[3] or "") or _CURRENCY_SIGNS.get(found[1] or "")
        target = _currency(found[4])
        amount = found[2]
        wordy = not amount and not found[1] and {found[3], found[4]} & _WORDY_CODES
    else:
        found = re.fullmatch(r"([a-z]{3})(?:/| )([a-z]{3})(?: exchange rate| rate)?", value)
        if not found:
            return None
        source, target, amount = _currency(found[1]), _currency(found[2]), None
        wordy = {found[1], found[2]} & _WORDY_CODES
    if not (source and target and source != target) or wordy:
        return None
    try:
        number = float((amount or "1").replace(",", ""))
    except ValueError:
        return None
    return {"kind": "currency", "amount": number, "from": source, "to": target}


def _units(low: str) -> dict | None:
    value = re.sub(r"^convert ", "", low)
    found = re.fullmatch(r"(-?[\d.,]+)?\s*([a-z°/ ]+?)\s+(?:to|in|into|as)\s+([a-z°/ ]+)", value)
    if found:
        source, target = _unit(found[2]), _unit(found[3])
        if source and target and source != target and _UNITS[source][0] == _UNITS[target][0]:
            try:
                amount = float((found[1] or "1").replace(",", ""))
            except ValueError:
                return None
            return {"kind": "units", "amount": amount, "from": source, "to": target}
    found = re.fullmatch(r"how many ([a-z°/ ]+?) (?:are )?in (?:an? |one |1 )?([a-z°/ ]+)", value)
    if found:
        target, source = _unit(found[1]), _unit(found[2])
        if source and target and source != target and _UNITS[source][0] == _UNITS[target][0]:
            return {"kind": "units", "amount": 1.0, "from": source, "to": target}
    found = re.fullmatch(r"(-?[\d.,]+)\s*([a-z°/ ]+?)(?: to)?", value)
    if found and low.startswith("convert "):
        source = _unit(found[2])
        if source in _UNIT_PARTNERS:
            return {
                "kind": "units",
                "amount": float(found[1].replace(",", "")),
                "from": source,
                "to": _UNIT_PARTNERS[source],
            }
    return None


def _time(low: str) -> dict | None:
    found = re.fullmatch(
        r"(?:the )?time difference (?:between )?(.+?) (?:and|to|vs) (.+)|(.+?) (?:to|vs) (.+?) time difference",
        low,
    )
    if found:
        one, two = (found[1], found[2]) if found[1] else (found[3], found[4])
        if zone_for(one) and zone_for(two):
            return {
                "kind": "time",
                "place": one.strip(),
                "zone": zone_for(one),
                "other_place": two.strip(),
                "other_zone": zone_for(two),
            }
    for pattern in (
        r"(?:what(?:'s| is) the )?(?:current |local )?time (?:is it )?(?:in|at) (.+?)(?: now| right now)?",
        r"what time is it (?:in|at) (.+)",
        r"(.+?) (?:local )?time(?: now| zone)?",
    ):
        found = re.fullmatch(pattern, low)
        if found and zone_for(found[1]):
            return {"kind": "time", "place": found[1].strip(), "zone": zone_for(found[1])}
    return None


def _weather(low: str) -> dict | None:
    found = (
        re.fullmatch(r"(?:weather forecast|weather|forecast)(?: in| for| at)? (.+)", low)
        or re.fullmatch(r"(?:temperature|temp) (?:in|at) (.+)", low)
        or re.fullmatch(r"(.+?) (?:weather forecast|weather|forecast)", low)
        or re.fullmatch(
            r"(?:is it|will it) (?:raining|rain|snowing|snow|sunny|cold|hot) (?:in|at) (.+)", low
        )
    )
    if not found:
        return None
    place = re.sub(
        r"\b(?:today|tomorrow|this week|now|right now|tonight|this weekend)\b", "", found[1]
    )
    place = re.sub(r"^(?:in|for|at) ", "", re.sub(r"\s+", " ", place).strip())
    if len(place) > 60:
        return None
    return {"kind": "weather", "place": place}


def _word(low: str) -> dict | None:
    found = re.fullmatch(
        r"(?:synonyms? (?:of|for)|other words? for|another word for|thesaurus) ([a-z][a-z' -]{0,40})|([a-z][a-z'-]{0,40}) synonyms?",
        low,
    )
    if found:
        return {"kind": "define", "word": (found[1] or found[2]).strip(), "focus": "synonyms"}
    found = re.fullmatch(
        r"(?:antonyms? (?:of|for)|opposite of) ([a-z][a-z' -]{0,40})|([a-z][a-z'-]{0,40}) antonyms?",
        low,
    )
    if found:
        return {"kind": "define", "word": (found[1] or found[2]).strip(), "focus": "antonyms"}
    found = re.fullmatch(
        r"(?:how (?:do you|to) pronounce|pronounce|pronunciation of) ([a-z][a-z' -]{0,40})|([a-z][a-z'-]{0,40}) pronunciation",
        low,
    )
    if found:
        return {"kind": "define", "word": (found[1] or found[2]).strip(), "focus": "pronunciation"}
    found = re.fullmatch(
        r"(?:how (?:do you|to|do i) spell|spell|spelling of|correct spelling of) ([a-z][a-z' -]{0,40})|([a-z][a-z'-]{0,40}) (?:spelling|spelled)",
        low,
    )
    if found:
        return {"kind": "spell", "word": (found[1] or found[2]).strip()}
    found = (
        re.fullmatch(r"(?:define|definition of|meaning of|dictionary) ([a-z][a-z' -]{0,40})", low)
        or re.fullmatch(r"what does ([a-z][a-z'-]{0,40}) mean", low)
        or re.fullmatch(r"([a-z][a-z'-]{0,40}) (?:meaning|definition|define)", low)
    )
    if found:
        return {"kind": "define", "word": found[1].strip(), "focus": ""}
    return None


def _translate(text: str) -> dict | None:
    """translation. a pair of languages alone opens the tool; it never translates the language name."""
    clean = text.rstrip("?").strip()
    low = clean.lower()
    pair = re.fullmatch(
        rf"(?:translate |translation |google translate )?(?:from )?{_LANG} (?:to|into|->|→|-) {_LANG}(?: translat(?:e|ion|or)| dictionary)?",
        low,
    )
    if pair:
        return {
            "kind": "translate",
            "text": "",
            "from": _LANGUAGE_WORDS[pair[1]],
            "to": _LANGUAGE_WORDS[pair[2]],
        }
    single = re.fullmatch(
        rf"{_LANG} (?:translat(?:e|ion|or)|dictionary)|translate (?:to|into) {_LANG}", low
    )
    if single:
        language = _LANGUAGE_WORDS[single[1] or single[2]]
        if language == "english":
            return {"kind": "translate", "text": "", "from": "", "to": "english"}
        return {"kind": "translate", "text": "", "from": "english", "to": language}
    sourced = re.fullmatch(
        rf"(?:translate |what is |what's |how do you say |how to say |say )?(.+?)(?: |(?<=[^\x00-\x7f]))from {_LANG} (?:to|into|in) {_LANG}",
        clean,
        re.I,
    )
    if sourced:
        phrase = sourced[1].strip(" \"'“”")
        if phrase and len(phrase) <= 500:
            return {
                "kind": "translate",
                "text": phrase,
                "from": _LANGUAGE_WORDS[sourced[2].lower()],
                "to": _LANGUAGE_WORDS[sourced[3].lower()],
            }
    # "中文in english": text in another script needs no space before "in"
    found = re.fullmatch(
        rf"(translate |what is |what's |how do you say |how to say |how do i say |say )?(.+?)(?: |(?<=[^\x00-\x7f]))(?:in|into|to) {_LANG}",
        clean,
        re.I,
    )
    if found:
        phrase = found[2].strip(" \"'“”")
        # without "translate"/"what is" in front, only a short phrase counts, so
        # "flights to france" style searches stay searches
        if (
            phrase
            and phrase.lower() not in _LANGUAGE_WORDS
            and len(phrase) <= 500
            and (found[1] or len(phrase.split()) <= 4)
        ):
            return {
                "kind": "translate",
                "text": phrase,
                "from": "",
                "to": _LANGUAGE_WORDS[found[3].lower()],
            }
    if low.startswith("translate "):
        phrase = clean[len("translate ") :].strip(" \"'“”")
        if phrase:
            return {"kind": "translate", "text": phrase, "from": "", "to": "english"}
    return None


def detect(query: str) -> dict | None:
    """which answer or tool fits this query, if any. pure pattern matching, nothing leaves the machine.

    one rule runs through it: asking for a tool opens the tool, empty; asking with the input answers.
    """
    from services import andromeda_dates, andromeda_f1, andromeda_utilities

    text = re.sub(r"\s+", " ", str(query or "").strip())
    low = text.lower().rstrip("?!. ").strip()
    if not low or len(low) > 300:
        return None
    found = andromeda_utilities.detect(low, text)
    if found:
        return found
    for check in (
        _tool,
        andromeda_f1.detect,
        _element_query,
        _color,
        _timer,
        _random,
        andromeda_dates.detect,
        _money,
        _units,
        _time,
        _weather,
        _word,
    ):
        found = check(low)
        if found:
            return found
    found = _translate(text)
    if found:
        return found
    math_part = re.sub(r"^(?:what is|what's|whats|calculate|calc|compute|solve)\s+", "", low)
    if calculate(math_part) is not None:
        return {"kind": "calc", "expression": math_part}
    # "what is serendipity": one plain word gets the dictionary, an element gets its card
    ask = re.fullmatch(r"(?:what is|what's|whats) (?:an? |the )?([a-z][a-z'-]{1,30})", low)
    if ask and ask[1] not in _NOT_WORDS:
        if ask[1] in BY_NAME:
            return {"kind": "element", "number": BY_NAME[ask[1]]["number"], "fact": ""}
        return {"kind": "define", "word": ask[1], "focus": ""}
    return None


# tools that answer the query on their own: the overview waits for the owner to ask
_ANSWERS_FULLY = {
    "calc",
    "units",
    "currency",
    "time",
    "clock",
    "weather",
    "define",
    "spell",
    "translate",
    "periodic",
    "timer",
    "random",
    "color",
    "date",
    "tip",
    "percent",
    "bmi",
    "loan",
    "base",
    "roman",
    "unix",
    "generate",
    "encode",
    "counter",
    "moon",
    "numfacts",
}


# these run in the browser: the card only needs what the owner asked for
_BROWSER_TOOLS = {
    "timer",
    "random",
    "color",
    "tip",
    "percent",
    "bmi",
    "loan",
    "base",
    "roman",
    "unix",
    "generate",
    "encode",
    "counter",
    "moon",
    "numfacts",
}


_NAV_SITES = set(
    "youtube gmail facebook amazon netflix reddit twitter x instagram github wikipedia google maps "
    "outlook hotmail spotify twitch tiktok linkedin whatsapp discord ebay paypal yahoo bing chatgpt "
    "claude pinterest tumblr imdb".split()
)
_NAV_WORDS = re.compile(r"\b(?:log ?in|sign ?in|download|near me|lyrics|torrent|login)\b", re.I)
_OPERATOR = re.compile(r"\b(?:site|inurl|intitle|filetype|ext|cache|related):", re.I)
_DOMAIN = re.compile(r"^(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", re.I)


def overview_mode(found: dict | None, query: str = "") -> str:
    """when the ai answer runs. it answers on its own by default:

    skip: a tool answers fully (a sum, a conversion, a translation), the overview waits to be
    asked. brief: a short one beside the card. none: site names, links, operators and errands
    get no overview at all. full: every other search."""
    if found:
        return "skip" if found["kind"] in _ANSWERS_FULLY else "brief"
    text = re.sub(r"\s+", " ", str(query or "").strip())
    if not text:
        return "full"
    words = text.lower().split(" ")
    if (
        _OPERATOR.search(text)
        or _DOMAIN.match(text)
        or _NAV_WORDS.search(text)
        or (len(words) <= 2 and all(word in _NAV_SITES for word in words))
    ):
        return "none"
    return "full"


_STEPS = re.compile(
    r"^(?:how (?:do|can|should|would) (?:i|you|we|one) |how to |steps? (?:to|for) |guide to |tutorial |"
    r"ways to (?:fix|install|make|set)|(?:install|set ?up|setup|configure|fix|make|build|cook|bake|replace|reset) )",
    re.I,
)
_COMPARE = re.compile(
    r"\b(?:vs\.?|versus|compared? (?:to|with)|comparison|difference(?:s)? between|better than|which is better)\b",
    re.I,
)
_LIST = re.compile(
    r"^(?:(?:the )?best |top \d*|list of |types of |kinds of |examples of |ideas for |tips for |"
    r"reasons |things to |alternatives to |places to )|\balternatives\b",
    re.I,
)


def overview_shape(query: str) -> str:
    """how the overview should read: a short answer, ordered steps, a comparison or a list."""
    text = str(query or "").strip()
    if _COMPARE.search(text):
        return "compare"
    if _STEPS.search(text):
        return "steps"
    if _LIST.search(text):
        return "list"
    return "answer"


# ── resolving ──
_WEATHER_CODES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "cloudy",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


async def _get_json(url: str):
    from services.net_guard import safe_get_public_async

    # wikimedia asks api clients to say who they are
    headers = {"accept": "application/json", "user-agent": "alles/1.0 (self-hosted search)"}
    response = await safe_get_public_async(
        url, timeout=8, headers=headers, max_redirects=2, max_bytes=400_000
    )
    response.raise_for_status()
    return response.json()


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", markup or ""))).strip()


def _missing(error: Exception) -> bool:
    return getattr(getattr(error, "response", None), "status_code", 0) == 404


async def _wiktionary(word: str) -> dict | None:
    try:
        data = await _get_json(
            "https://en.wiktionary.org/api/rest_v1/page/definition/" + urllib.parse.quote(word)
        )
    except Exception as error:
        if _missing(error):
            return None
        raise
    meanings = []
    for meaning in (data or {}).get("en") or []:
        definitions = []
        for d in meaning.get("definitions") or []:
            text = _plain(d.get("definition", ""))
            if not text:
                continue
            examples = [_plain(x.get("example", "")) for x in d.get("parsedExamples") or []]
            examples += [_plain(x) for x in d.get("examples") or []]
            definitions.append({"text": text, "example": next((x for x in examples if x), "")})
            if len(definitions) == 3:
                break
        if definitions:
            part = str(meaning.get("partOfSpeech") or "").lower()
            meanings.append({"part": part, "definitions": definitions})
    if not meanings:
        return None
    return {
        "kind": "define",
        "word": word,
        "phonetic": "",
        "meanings": meanings[:3],
        "source": "Wiktionary",
    }


def _element(row: dict) -> dict:
    return {**row, "category_label": CATEGORY_LABELS[row["category"]]}


async def _wikitext(word: str) -> str:
    """the english section of a wiktionary page, or "" when there is none."""
    data = await _get_json(
        "https://en.wiktionary.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": word,
                "format": "json",
                "formatversion": 2,
            }
        )
    )
    pages = (data.get("query") or {}).get("pages") or [{}]
    revisions = pages[0].get("revisions") or [{}]
    text = ((revisions[0].get("slots") or {}).get("main") or {}).get("content") or ""
    english = re.search(r"^==English==\s*$(.*?)(?=^==[^=]|\Z)", text, re.S | re.M)
    return english.group(1) if english else ""


def _ipa(wikitext: str) -> str:
    found = re.search(r"\{\{IPA\|en\|([^}|]+)", wikitext or "")
    return found.group(1).strip() if found else ""


def _misspelling_of(wikitext: str) -> list[str]:
    found = re.findall(r"\{\{(?:common )?misspelling of\|en\|([^}|]+)", wikitext or "")
    return list(dict.fromkeys(word.strip() for word in found))


async def _datamuse(**params) -> list[dict]:
    rows = await _get_json(
        "https://api.datamuse.com/words?" + urllib.parse.urlencode({**params, "md": "f"})
    )
    out = []
    for row in rows if isinstance(rows, list) else []:
        word = str(row.get("word") or "")
        freq = next(
            (float(tag[2:]) for tag in row.get("tags") or [] if str(tag).startswith("f:")), 0.0
        )
        if word:
            out.append({"word": word, "freq": freq})
    return out


def _edits(a: str, b: str) -> int:
    """optimal string alignment distance: insert, delete, replace, swap neighbours."""
    rows = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


async def _quiet(coro, default):
    try:
        return await coro
    except Exception:
        return default


async def spell(word: str) -> dict:
    word = word.strip().lower()
    from services import andromeda_dictionary

    local = andromeda_dictionary.spelling(word)
    if local is not None:
        return {
            "kind": "spell",
            "word": word,
            "status": "ok",
            "correct": local["known"] and not local["suggestions"],
            "suggestions": local["suggestions"],
            "source": "Wiktionary (local copy)",
        }
    wikitext, near = await asyncio.gather(
        _quiet(_wikitext(word), None), _quiet(_datamuse(sp=word, max=12), None)
    )
    if wikitext is None and near is None:
        return {
            "kind": "spell",
            "word": word,
            "status": "unavailable",
            "source": "Wiktionary, Datamuse",
        }
    near = near or []
    misspelt = _misspelling_of(wikitext or "")
    if misspelt:
        return {
            "kind": "spell",
            "word": word,
            "status": "ok",
            "correct": False,
            "suggestions": misspelt[:3],
            "source": "Wiktionary",
        }
    own = next((row["freq"] for row in near if row["word"] == word), 0.0)
    others = sorted(
        (
            row
            for row in near
            if row["word"] != word and " " not in row["word"] and _edits(row["word"], word) <= 2
        ),
        key=lambda row: -row["freq"],
    )
    if own >= 0.5 or (wikitext and own >= 0.05):
        return {
            "kind": "spell",
            "word": word,
            "status": "ok",
            "correct": True,
            "suggestions": [],
            "source": "Wiktionary, Datamuse",
        }
    likely = [row["word"] for row in others if row["freq"] >= 1.0][:3]
    return {
        "kind": "spell",
        "word": word,
        "status": "ok",
        "correct": bool(wikitext) and not likely,
        "suggestions": likely,
        "source": "Wiktionary, Datamuse",
    }


async def _free_dictionary(word: str) -> dict | None:
    data = await _get_json(
        "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    )
    if not isinstance(data, list) or not data:
        return None
    entry = data[0]
    meanings = []
    synonyms, antonyms = [], []
    for meaning in entry.get("meanings") or []:
        definitions = [
            {"text": d.get("definition", ""), "example": d.get("example", "")}
            for d in (meaning.get("definitions") or [])[:3]
            if d.get("definition")
        ]
        synonyms += meaning.get("synonyms") or []
        antonyms += meaning.get("antonyms") or []
        for d in meaning.get("definitions") or []:
            synonyms += d.get("synonyms") or []
            antonyms += d.get("antonyms") or []
        if definitions:
            meanings.append({"part": meaning.get("partOfSpeech", ""), "definitions": definitions})
    if not meanings:
        return None
    return {
        "kind": "define",
        "word": entry.get("word") or word,
        "phonetic": entry.get("phonetic")
        or next((p.get("text") for p in entry.get("phonetics") or [] if p.get("text")), ""),
        "meanings": meanings[:3],
        "synonyms": synonyms,
        "antonyms": antonyms,
        "source": "Free Dictionary API (Wiktionary)",
    }


def _words(values, word: str, limit: int = 8) -> list[str]:
    out = []
    for value in values:
        value = str(value or "").strip()
        if value and value.lower() != word.lower() and value not in out:
            out.append(value)
        if len(out) == limit:
            break
    return out


async def define(word: str, focus: str = "") -> dict:
    word = word.strip()
    from services import andromeda_dictionary

    # the local wiktionary copy answers in a millisecond and the word stays on this machine
    local = andromeda_dictionary.lookup(word, focus)
    if local is not None:
        return local
    # every source at once: the slowest one sets the wait, not the sum of them
    free, wiki, wikitext, related, opposite = await asyncio.gather(
        _quiet(_free_dictionary(word), None),
        _settled(_wiktionary(word)),
        _quiet(_wikitext(word), ""),
        _quiet(_datamuse(rel_syn=word, max=12), []),
        _quiet(_datamuse(rel_ant=word, max=8), []) if focus == "antonyms" else _none([]),
    )
    wiki_entry, wiki_failed = wiki
    entry = free or wiki_entry
    if entry is None:
        if wiki_failed:
            return {
                "kind": "define",
                "word": word,
                "focus": focus,
                "status": "unavailable",
                "source": "Wiktionary",
            }
        guesses = _misspelling_of(wikitext) or [
            row["word"]
            for row in await _quiet(_datamuse(sp=word, max=8), [])
            if row["word"] != word and row["freq"] >= 1.0
        ]
        return {
            "kind": "define",
            "word": word,
            "focus": focus,
            "status": "not_found",
            "suggestions": guesses[:3],
            "source": "Wiktionary",
        }
    if not entry.get("phonetic"):
        entry["phonetic"] = _ipa(wikitext)
    entry["synonyms"] = _words(
        list(entry.get("synonyms") or []) + [r["word"] for r in related], word
    )
    entry["antonyms"] = _words(
        list(entry.get("antonyms") or []) + [r["word"] for r in opposite], word
    )
    return {**entry, "focus": focus, "status": "ok"}


async def _settled(coro):
    """(value, failed): a lookup that broke is told apart from one that found nothing."""
    try:
        return await coro, False
    except Exception:
        return None, True


async def _none(value):
    return value


# ── did you mean ──
_COMMON = set(
    "the a an and or of to in on for with is are was were be by at as it this that from how what "
    "why when where who which best vs not can do does did i you we my your".split()
)
_SPELLING_CACHE: dict = {}


async def _word_fix(word: str) -> str:
    """the usual spelling of one word, or "" when it looks right or nothing is sure."""
    if word in _SPELLING_CACHE:
        return _SPELLING_CACHE[word]
    from services import andromeda_dictionary

    local = andromeda_dictionary.spelling(word)
    if local is not None:
        # wiktionary marks common misspellings ("recieve", "thier"); a known or unknown word is
        # left alone, and nothing is asked online
        return local["suggestions"][0] if local["suggestions"] else ""
    near = await _quiet(_datamuse(sp=word, max=8), None)
    if near is None:
        return ""
    own = next((row["freq"] for row in near if row["word"] == word), 0.0)
    fix = ""
    if own < 0.5:
        marked = _misspelling_of(await _quiet(_wikitext(word), ""))
        if marked:
            fix = marked[0]
        elif own < 0.05:
            close = [
                row
                for row in near
                if row["word"] != word
                and " " not in row["word"]
                and row["freq"] >= 2.0
                and _edits(row["word"], word) == 1
            ]
            fix = max(close, key=lambda row: row["freq"])["word"] if close else ""
    if len(_SPELLING_CACHE) > 2000:
        _SPELLING_CACHE.clear()
    _SPELLING_CACHE[word] = fix
    return fix


async def did_you_mean(query: str) -> str:
    """google-style "did you mean": the query with misspelled words fixed, or "".

    only short plain-word searches are checked, and only the words go out (to datamuse and
    wiktionary), the same words the search engine already got."""
    text = re.sub(r"\s+", " ", str(query or "").strip().lower())
    words = text.split(" ")
    if not text or len(words) > 6 or not re.fullmatch(r"[a-z' -]+", text):
        return ""
    checks = [w for w in dict.fromkeys(words) if len(w) >= 4 and w not in _COMMON]
    if not checks:
        return ""
    fixes = dict(zip(checks, await asyncio.gather(*(_word_fix(w) for w in checks))))
    fixed = " ".join(fixes.get(w) or w for w in words)
    return fixed if fixed != text else ""


def _unit_options() -> list[dict]:
    return [
        {"id": key, "label": label, "factor": factor, "kind": unit_kind}
        for key, (unit_kind, factor, label) in _UNITS.items()
    ]


async def _currency_answer(found: dict) -> dict:
    out = {
        "kind": "currency",
        "amount": _number(found["amount"]),
        "amount_value": found["amount"],
        "from": found["from"].upper(),
        "to": found["to"].upper(),
        "currencies": [{"code": code.upper(), "name": name} for code, name in _CURRENCIES.items()],
        "source": "European Central Bank rates via Frankfurter",
    }
    try:
        data = await _get_json(
            "https://api.frankfurter.dev/v1/latest?"
            + urllib.parse.urlencode({"base": out["from"], "symbols": out["to"]})
        )
        rate = float((data.get("rates") or {})[out["to"]])
    except Exception:
        return {**out, "status": "unavailable"}
    value = found["amount"] * rate
    return {
        **out,
        "status": "ok",
        "rate": rate,
        "result": f"{value:,.2f}",
        "result_value": value,
        "date": data.get("date", ""),
    }


async def _weather_answer(found: dict, strict: bool) -> dict | None:
    if not found["place"]:
        return {"kind": "weather", "place": "", "status": "empty", "source": "Open-Meteo"}
    try:
        places = await _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": found["place"], "count": 1})
        )
    except Exception:
        return {
            "kind": "weather",
            "place": found["place"],
            "status": "unavailable",
            "source": "Open-Meteo",
        }
    place = (places.get("results") or [None])[0]
    if not place:
        # a search like "climate change weather" stays a search; the tool says what it couldn't find
        if not strict:
            return None
        return {
            "kind": "weather",
            "place": found["place"],
            "status": "not_found",
            "source": "Open-Meteo",
        }
    forecast_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 7,
        }
    )
    data = None
    # open-meteo sheds load with a 503 now and then; one more try usually lands
    for attempt in range(2):
        try:
            data = await _get_json(forecast_url)
            break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(0.6)
    if not data:
        return {
            "kind": "weather",
            "place": found["place"],
            "status": "unavailable",
            "source": "Open-Meteo",
        }
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    days = [
        {"date": day, "high": high, "low": low, "sky": _WEATHER_CODES.get(code, ""), "rain": rain}
        for day, high, low, code, rain in zip(
            daily.get("time") or [],
            daily.get("temperature_2m_max") or [],
            daily.get("temperature_2m_min") or [],
            daily.get("weather_code") or [],
            daily.get("precipitation_probability_max") or [None] * len(daily.get("time") or []),
        )
    ]
    return {
        "kind": "weather",
        "status": "ok",
        "place": ", ".join(
            p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p
        ),
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "sky": _WEATHER_CODES.get(current.get("weather_code"), ""),
        "wind": current.get("wind_speed_10m"),
        "humidity": current.get("relative_humidity_2m"),
        "days": days,
        "source": "Open-Meteo",
    }


async def resolve(found: dict, *, strict: bool = False) -> dict | None:
    """the card's data. None means no card; a card with a status says why a lookup came up short.

    strict is set when the owner typed into a tool, so "not found" is said instead of hidden.
    """
    from services import andromeda_dates, andromeda_f1

    kind = found["kind"]
    if kind == "calc":
        expression = found.get("expression") or ""
        if not expression:
            return {"kind": kind, "expression": "", "result": "", "status": "empty"}
        value = calculate(expression, loose=strict)
        if value is None:
            return (
                {"kind": kind, "expression": expression, "result": "", "status": "invalid"}
                if strict
                else None
            )
        return {"kind": kind, "expression": expression, "result": _number(value), "status": "ok"}
    if kind == "units":
        value = convert(found["amount"], found["from"], found["to"])
        if value is None:
            return None
        unit_kind = _UNITS[found["from"]][0]
        return {
            "kind": kind,
            "amount": _number(found["amount"]),
            "amount_value": found["amount"],
            "from": _UNITS[found["from"]][2],
            "to": _UNITS[found["to"]][2],
            "from_id": found["from"],
            "to_id": found["to"],
            "result": _number(round(value, 6)),
            "result_value": value,
            "unit_kind": unit_kind,
            "units": _unit_options(),
            "kinds": sorted({row[0] for row in _UNITS.values()}),
            "status": "ok",
        }
    if kind == "time":
        now = datetime.now(ZoneInfo(found["zone"]))
        out = {
            "kind": kind,
            "place": found["place"],
            "zone": found["zone"],
            "iso": now.isoformat(timespec="seconds"),
            "offset": now.strftime("%z"),
            "status": "ok",
        }
        if found.get("other_zone"):
            other = datetime.now(ZoneInfo(found["other_zone"]))
            out.update(
                other_place=found["other_place"],
                other_zone=found["other_zone"],
                other_offset=other.strftime("%z"),
                difference_hours=(
                    other.utcoffset().total_seconds() - now.utcoffset().total_seconds()
                )
                / 3600,
            )
        return out
    if kind == "clock":
        return {
            "kind": kind,
            "status": "ok",
            "server_zone": str(datetime.now().astimezone().tzinfo),
        }
    if kind == "periodic":
        return {"kind": kind, "status": "ok", "elements": [_element(row) for row in ELEMENTS]}
    if kind == "element":
        return {
            "kind": kind,
            "status": "ok",
            "selected": found["number"],
            "fact": found.get("fact") or "",
            "elements": [_element(row) for row in ELEMENTS],
        }
    if kind == "currency":
        return await _currency_answer(found)
    if kind == "weather":
        return await _weather_answer(found, strict)
    if kind == "define":
        if not found["word"]:
            return {"kind": kind, "word": "", "focus": found.get("focus") or "", "status": "empty"}
        return await define(found["word"], found.get("focus") or "")
    if kind == "spell":
        if not found["word"]:
            return {"kind": kind, "word": "", "status": "empty"}
        return await spell(found["word"])
    if kind == "translate":
        base = {
            "kind": kind,
            "text": found["text"],
            "from": found.get("from") or "",
            "to": found["to"],
            "languages": list(LANGUAGES),
            "translation": "",
            "romanization": "",
        }
        # the owner asked for the tool: nothing is translated until they type. with text, the
        # card shows at once and the translator fills it in through POST /translate
        return {**base, "status": "pending" if found["text"] else "empty"}
    if kind == "f1":
        return await andromeda_f1.resolve(found, _get_json)
    if kind == "date":
        answer = andromeda_dates.resolve(found)
        return {**answer, "status": "ok"} if answer else None
    if kind in _BROWSER_TOOLS:
        return {**found, "status": "ok"}
    return None
