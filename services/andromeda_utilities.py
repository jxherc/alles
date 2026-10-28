"""small offline tools for andromeda: tip, percentages, bmi, loans, number bases, roman numerals,
unix time, passwords and uuids, encoders, counters, the moon and number facts.

detect() only reads the query and says which tool fits and what it was given. the maths runs in
the browser (static/js/andromeda_calcs.js), so a tool also works while it is being typed into.
a tool asked for by name opens empty; a query that carries its input answers right away.
"""

from __future__ import annotations

import re

_NUM = r"\d[\d,]*(?:\.\d+)?|\.\d+"
_PCT = r"(?:%|percent(?:age)?)"


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _only(text: str, words: set[str]) -> bool:
    """true when nothing but filler words is left, so a tool never steals a real search."""
    return all(word in words for word in re.findall(r"[a-z']+", text))


def _named(low: str, pattern: str) -> bool:
    return bool(
        re.fullmatch(
            rf"(?:(?:open|show(?: me)?|launch|use) )?(?:an? |the )?(?:online |free )?(?:{pattern})(?: tool| online| app)?",
            low,
        )
    )


# ── tip ──
_TIP_WORDS = set(
    "tip tips on of the a for at with bill calculate calculator what is whats how much to should i "
    "leave split between among ways way people person each per gratuity and pay total".split()
)


def _tip(low: str) -> dict | None:
    if _named(
        low,
        r"(?:restaurant |bill )?tip(?:ping)? calculator|gratuity calculator|split (?:the )?bill|bill split(?:ter| calculator)?",
    ):
        return {"kind": "tip", "bill": None, "percent": None, "people": None}
    if not re.search(r"\b(?:tip|tips|gratuity|split)\b", low):
        return None
    text = low
    percent = re.search(rf"({_NUM})\s*{_PCT}", text)
    if percent:
        text = text.replace(percent[0], " ", 1)
    people = re.search(
        r"(?:between|among|by)\s+(\d{1,3})(?:\s+(?:people|persons|ways|friends))?|(\d{1,3})\s+(?:people|persons|ways|friends)",
        text,
    )
    if people:
        text = text.replace(people[0], " ", 1)
    bill = re.findall(rf"\$?\s*({_NUM})", text)
    text = re.sub(rf"\$?\s*({_NUM})", " ", text)
    if len(bill) != 1 or not _only(text, _TIP_WORDS):
        return None
    count = int(people[1] or people[2]) if people else None
    if count is not None and not 1 <= count <= 100:
        return None
    return {
        "kind": "tip",
        "bill": _number(bill[0]),
        "percent": _number(percent[1]) if percent else None,
        "people": count,
    }


# ── percentages ──
def _percent(low: str) -> dict | None:
    if _named(
        low,
        r"percent(?:age)? (?:change |increase |decrease |difference )?calculator",
    ):
        change = re.search(r"change|increase|decrease|difference", low)
        return {"kind": "percent", "mode": "change" if change else "of", "a": None, "b": None}
    if _named(low, r"discount calculator|sale price calculator|percent(?:age)? off calculator"):
        return {"kind": "percent", "mode": "off", "a": None, "b": None}
    value = rf"\$?({_NUM})"
    found = (
        re.fullmatch(rf"(?:what is |what's )?{value} is what {_PCT} of {value}", low)
        or re.fullmatch(rf"what {_PCT} is {value} of {value}", low)
        or re.fullmatch(rf"{value} out of {value} as a {_PCT}", low)
        or re.fullmatch(rf"{value} as a {_PCT} of {value}", low)
    )
    if found:
        return {"kind": "percent", "mode": "is", "a": _number(found[1]), "b": _number(found[2])}
    found = re.fullmatch(
        rf"{_PCT} (?:change|increase|decrease|difference) (?:from |between )?{value} (?:to|and) {value}",
        low,
    ) or re.fullmatch(rf"{value} to {value} {_PCT} (?:change|increase|decrease|difference)", low)
    if found:
        return {"kind": "percent", "mode": "change", "a": _number(found[1]), "b": _number(found[2])}
    found = re.fullmatch(rf"(?:what is |what's )?({_NUM})\s*{_PCT} off (?:of )?{value}", low)
    if found:
        return {"kind": "percent", "mode": "off", "a": _number(found[1]), "b": _number(found[2])}
    found = re.fullmatch(rf"{value} (?:with |minus )?({_NUM})\s*{_PCT} (?:off|discount)", low)
    if found:
        return {"kind": "percent", "mode": "off", "a": _number(found[2]), "b": _number(found[1])}
    return None


# ── bmi ──
_BMI_WORDS = set(
    "bmi for of calculator calculate my is what at and a tall weigh weighing height weight i am with "
    "body mass index".split()
)


def _bmi(low: str) -> dict | None:
    if _named(low, r"bmi(?: calculator)?|body mass index(?: calculator)?|calculate (?:my )?bmi"):
        return {"kind": "bmi", "unit": "metric", "weight": None, "height": None}
    if not re.search(r"\bbmi\b", low):
        return None
    text = low
    weight = re.search(r"(\d+(?:\.\d+)?)\s*(kgs?|kilos?|kilograms?|lbs?|pounds?)\b", text)
    if not weight:
        return None
    text = text.replace(weight[0], " ", 1)
    height = re.search(
        r"(\d)\s*(?:ft|feet|foot|')\s*(\d{1,2}(?:\.\d+)?)?\s*(?:in|inches|\")?", text
    )
    if height:
        centimetres = (int(height[1]) * 12 + float(height[2] or 0)) * 2.54
    else:
        height = re.search(r"(\d+(?:\.\d+)?)\s*(cm|m|meters?|metres?)\b", text)
        if not height:
            return None
        centimetres = float(height[1]) * (1 if height[2] == "cm" else 100)
    text = text.replace(height[0], " ", 1)
    if not _only(text, _BMI_WORDS) or re.search(r"\d", text) or not 50 <= centimetres <= 272:
        return None
    if weight[2].startswith(("lb", "pound")):
        return {
            "kind": "bmi",
            "unit": "imperial",
            "weight": float(weight[1]),
            "height": round(centimetres / 2.54, 1),
        }
    return {
        "kind": "bmi",
        "unit": "metric",
        "weight": float(weight[1]),
        "height": round(centimetres, 1),
    }


# ── loans ──
_LOAN_WORDS = set(
    "mortgage loan payment payments monthly on a an for at over of with the calculator calculate "
    "what is whats my car auto home house student personal".split()
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}


def _loan(low: str) -> dict | None:
    mode = "mortgage" if "mortgage" in low else "loan"
    if _named(
        low,
        r"(?:mortgage|loan)(?: payment)? calculator|(?:car|auto|home|student|personal) loan(?: payment)? calculator|"
        r"monthly payment calculator|loan payment|mortgage payment",
    ):
        return {"kind": "loan", "mode": mode, "amount": None, "rate": None, "years": None}
    if not re.search(r"\b(?:mortgage|loan)\b", low):
        return None
    text = low
    rate = re.search(rf"({_NUM})\s*{_PCT}", text)
    if rate:
        text = text.replace(rate[0], " ", 1)
    term = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?(years?|yrs?|y|months?|mos?)\b", text)
    if term:
        text = text.replace(term[0], " ", 1)
    amount = re.search(rf"\$?\s*({_NUM})\s*(k|thousand|m|million)?\b", text)
    if amount:
        text = text.replace(amount[0], " ", 1)
    if not amount or not (rate or term) or re.search(r"\d", text) or not _only(text, _LOAN_WORDS):
        return None
    years = float(term[1]) / (12 if term[2].startswith("mo") else 1) if term else None
    return {
        "kind": "loan",
        "mode": mode,
        "amount": _number(amount[1]) * _SCALE.get(amount[2] or "", 1),
        "rate": _number(rate[1]) if rate else None,
        "years": round(years, 4) if years else None,
    }


# ── number bases ──
_BASE_WORDS = {
    "binary": 2,
    "bin": 2,
    "octal": 8,
    "oct": 8,
    "decimal": 10,
    "dec": 10,
    "hex": 16,
    "hexadecimal": 16,
}
_BASE = "(" + "|".join(sorted(_BASE_WORDS, key=len, reverse=True)) + ")"
_DIGITS = {2: "[01]", 8: "[0-7]", 10: r"\d", 16: "[0-9a-f]"}
_PREFIXES = {"0x": 16, "0b": 2, "0o": 8}


def _base(low: str) -> dict | None:
    if _named(
        low,
        r"(?:number )?(?:base|number system|radix) (?:converter|conversion|calculator)|(?:binary|hex|hexadecimal|octal|decimal) converter",
    ):
        return {"kind": "base", "value": "", "from": 10, "to": 16}
    found = re.fullmatch(
        rf"{_BASE} (?:to|2|into) {_BASE}(?: converter| conversion| calculator)?", low
    )
    if found and found[1] != found[2]:
        return {
            "kind": "base",
            "value": "",
            "from": _BASE_WORDS[found[1]],
            "to": _BASE_WORDS[found[2]],
        }
    found = re.fullmatch(rf"(?:convert )?(-?0[xbo][0-9a-f]+) (?:in|to|as|into) {_BASE}", low)
    if found:
        source = _PREFIXES[found[1].lstrip("-")[:2]]
        if re.fullmatch(rf"-?0.{_DIGITS[source]}+", found[1]) and _BASE_WORDS[found[2]] != source:
            return {"kind": "base", "value": found[1], "from": source, "to": _BASE_WORDS[found[2]]}
        return None
    found = re.fullmatch(rf"(?:convert )?(-?\d+) (?:in|to|as|into) {_BASE}(?: number)?", low)
    if found and _BASE_WORDS[found[2]] != 10:
        return {"kind": "base", "value": found[1], "from": 10, "to": _BASE_WORDS[found[2]]}
    found = re.fullmatch(
        rf"(?:convert )?(-?[0-9a-f]+) (?:in )?{_BASE} (?:to|in|into|as) {_BASE}", low
    ) or re.fullmatch(rf"convert (-?[0-9a-f]+) from {_BASE} to {_BASE}", low)
    if found:
        source, target = _BASE_WORDS[found[2]], _BASE_WORDS[found[3]]
        if source != target and re.fullmatch(rf"-?{_DIGITS[source]}+", found[1]):
            return {"kind": "base", "value": found[1], "from": source, "to": target}
    return None


# ── roman numerals ──
_ROMAN = r"(?=[mdclxvi])m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"


def _roman(low: str) -> dict | None:
    if _named(
        low,
        r"roman numerals?(?: converter| calculator| chart| generator| translator)?|numbers? to roman(?: numerals?)?(?: converter)?|"
        r"roman numerals? to (?:numbers?|decimal)(?: converter)?|roman (?:to|and) (?:numbers?|decimal|arabic)(?: converter)?",
    ):
        return {"kind": "roman", "value": ""}
    found = re.fullmatch(
        r"(?:what is |what's |convert )?(\d{1,4}) (?:in|to|as|into) roman(?: numerals?)?|roman(?: numerals?)? (?:for |of )?(\d{1,4})",
        low,
    )
    if found:
        return {"kind": "roman", "value": found[1] or found[2]}
    found = re.fullmatch(
        rf"(?:what is |what's |convert )?({_ROMAN}) (?:in|to|as|into) (?:numbers?|decimal|arabic(?: numerals?)?|digits|integers?)|roman numerals? ({_ROMAN})",
        low,
    )
    if found:
        return {"kind": "roman", "value": (found[1] or found[2]).upper()}
    # a bare numeral is only a numeral when it is long enough not to be a word ("mix", "civil")
    found = re.fullmatch(rf"(?:what is |what's )?({_ROMAN})", low)
    if found and len(found[1]) >= 4:
        return {"kind": "roman", "value": found[1].upper()}
    return None


# ── unix time ──
def _unix(low: str) -> dict | None:
    if _named(
        low,
        r"(?:what(?:'s| is) the )?(?:current )?(?:unix|epoch)(?: time ?stamp| time| epoch| timestamp)(?: converter| now)?|"
        r"(?:unix|epoch) converter|time ?stamp converter|current time ?stamp",
    ):
        return {"kind": "unix", "value": ""}
    found = re.fullmatch(
        r"(?:convert )?(\d{9,13}) (?:to date|(?:unix|epoch)(?: time| timestamp)?|time ?stamp|to human(?: readable)?(?: date)?|in date)",
        low,
    ) or re.fullmatch(
        r"(?:convert )?(?:(?:unix|epoch)(?: time| timestamp)?|time ?stamp)(?: converter)? (\d{1,13})(?: to date)?",
        low,
    )
    if found:
        return {"kind": "unix", "value": found[1]}
    return None


# ── passwords and uuids ──
_ASKED = r"\b(?:generate|create|make|random|strong|secure)\b"
_ADJ = r"(?:new|random|strong|secure|safe|good|complex|long)"


def _generate(low: str) -> dict | None:
    found = re.fullmatch(
        rf"(?:(?:generate|create|make|get|give me) )*(?:an? |me )?(?:(\d{{1,3}})[ -]?(?:char(?:acter)?s?[ -]?)?(?:long )?)?(?:{_ADJ} )*password"
        r"(?: (?:generator|maker|creator))?(?: (?:with |of |length )?(\d{1,3})(?: char(?:acter)?s?(?: long)?)?)?",
        low,
    )
    asked = re.search(_ASKED, low)
    if found and (asked or re.search(r"generator|maker|creator", low)):
        length = int(found[1] or found[2] or 0)
        return {
            "kind": "generate",
            "mode": "password",
            "length": length if 6 <= length <= 64 else None,
            "roll": bool(asked),
        }
    found = re.fullmatch(
        r"(?:(?:generate|create|make|get|new|random) )*(?:an? )?(?:uuid|guid)(?: ?v?4| version 4)?(?: (?:generator|maker))?",
        low,
    )
    asked = re.search(r"\b(?:generate|create|make|get|new|random)\b", low)
    if found and (asked or re.search(r"generator|maker|v ?4|version 4", low)):
        return {"kind": "generate", "mode": "uuid", "length": None, "roll": bool(asked)}
    return None


# ── encoders ──
_SCHEMES = {"base64": "base64", "base 64": "base64", "url": "url", "uri": "url", "html": "html"}
_SCHEME = r"(base64|base 64|url|uri|html)"
# a question about encoding in some language or tool is a search, not a string to encode
_NOT_TEXT = set(
    "in with using for vs of tool meaning works how what why is are to a an the on from".split()
)
_LANGS = set(
    "javascript js python java php node nodejs bash c# linux powershell rust go golang ruby swift "
    "kotlin typescript online tutorial example examples explained algorithm".split()
)


def _encode(text: str) -> dict | None:
    def card(scheme: str, direction: str, rest: str | None) -> dict | None:
        rest = (rest or "").strip()
        words = rest.lower().split(" ")
        if rest and (words[0] in _NOT_TEXT or _LANGS & set(words)):
            return None
        return {
            "kind": "encode",
            "scheme": _SCHEMES[scheme.lower()],
            "dir": direction,
            "text": rest,
        }

    found = re.fullmatch(rf"{_SCHEME}[ -]?(encode|decode)(?: (.+))?", text, re.I)
    if found:
        return card(found[1], found[2].lower(), found[3])
    found = re.fullmatch(r"(encode|decode)(?: to| in| as)? " + _SCHEME + r"(?: (.+))?", text, re.I)
    if found:
        return card(found[2], found[1].lower(), found[3])
    found = re.fullmatch(
        r"(url|uri|html|base64)[ -]?(encoder|decoder)(?:[ /](?:decoder|encoder))?(?: online)?",
        text,
        re.I,
    )
    if found:
        return card(found[1], "decode" if found[2].lower() == "decoder" else "encode", "")
    return None


# ── counters ──
def _counter(low: str) -> dict | None:
    if _named(
        low,
        r"(?:word|character|char|letter)s? (?:count|counter|counting)|(?:word|character)s? and (?:word|character)s? (?:count|counter)|"
        r"count (?:the )?(?:words|characters|letters)|reading time calculator|(?:word|character) count tool",
    ):
        return {"kind": "counter", "text": ""}
    return None


# ── moon ──
def _moon(low: str) -> dict | None:
    phase = r"moon phases?|phase of the moon|phases of the moon|lunar phases?"
    when = r"(?: today| tonight| now| right now)?"
    if re.fullmatch(
        rf"(?:what(?:'s| is) )?(?:the )?(?:current |today's |tonight's )?(?:{phase}){when}|"
        rf"what (?:moon )?phase is (?:the )?moon(?: in)?{when}|what (?:moon )?phase is it{when}|"
        r"(?:is (?:it|there) )?(?:an? )?(?:full|new) moon (?:today|tonight)|(?:when is )?(?:the )?next (?:full|new) moon|"
        r"(?:the )?moon (?:today|tonight)",
        low,
    ):
        return {"kind": "moon"}
    return None


# ── number facts ──
def _numfacts(low: str) -> dict | None:
    names = {
        "prime": r"prime(?: number)? (?:checker|calculator|tester|finder)",
        "factors": r"(?:factor|factors|prime factor|prime factors|prime factorization) (?:calculator|finder)",
        "gcd": r"(?:gcd|gcf|greatest common (?:divisor|factor)) calculator",
        "lcm": r"(?:lcm|least common multiple) calculator",
    }
    for mode, pattern in names.items():
        if _named(low, pattern):
            return {"kind": "numfacts", "mode": mode, "a": None, "b": None}
    found = re.fullmatch(r"is (\d{1,12}) (?:a )?prime(?: number)?", low)
    if found:
        return {"kind": "numfacts", "mode": "prime", "a": int(found[1]), "b": None}
    found = re.fullmatch(
        r"(?:what are the )?(?:prime )?(?:factors|factorization) of (\d{1,12})", low
    )
    if found:
        return {"kind": "numfacts", "mode": "factors", "a": int(found[1]), "b": None}
    found = re.fullmatch(
        r"(?:what is the )?(gcd|gcf|greatest common (?:divisor|factor)|lcm|least common multiple) (?:of )?(\d{1,12}) (?:and|,|&) (\d{1,12})",
        low,
    )
    if found:
        mode = "lcm" if found[1] in ("lcm", "least common multiple") else "gcd"
        return {"kind": "numfacts", "mode": mode, "a": int(found[2]), "b": int(found[3])}
    return None


def detect(low: str, text: str) -> dict | None:
    """which small tool fits this query, if any. low is lowercased, text keeps the owner's case."""
    for check in (
        _tip,
        _percent,
        _bmi,
        _loan,
        _base,
        _roman,
        _unix,
        _generate,
        _counter,
        _moon,
        _numfacts,
    ):
        found = check(low)
        if found:
            return found
    return _encode(text.strip().rstrip("?!. ").strip())
