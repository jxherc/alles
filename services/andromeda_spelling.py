"""Google-style spelling fix for the andromeda search box.

Local part: pyspellchecker's english word list, used the careful way. A wrong fix is worse than
none (people search for brands, game names and other languages), so only plain typos are fixed.
Engine part: brave, searxng and google pse give their own fix; it is checked, never trusted blindly.
"""

from __future__ import annotations

import difflib
import re
from functools import lru_cache

# a fix must be a word people really write: at least about one in a million words in the
# list's corpus (1.6 billion words). "achievements" sits at 1.4 per million; the rare words
# below the floor are mostly names and misspellings that the list happens to hold
MIN_FREQUENCY = 1e-6
# the best fix must beat the runner-up of the same kind by this much, else it's a coin flip
CLEAR_WIN = 6.0
# edits that people make by accident (swap two letters, double or undouble one) are safe on any
# word of 4+ letters. other single edits (a missed letter, a neighbouring key) need a long word:
# "gmail" is one letter from "mail", "spacex" from "space"
SAFE_MIN = 4
OTHER_MIN = 7
MAX_FIXES = 3
MAX_CHARS = 300

_ORDER = ("swap", "double", "slip", "missing")
_VOWELS = frozenset("aeiou")
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_PLAIN = re.compile(r"([(]*)([A-Za-z]+)([?.,;:!)]*)")
_QUOTED = re.compile(r'("[^"]*(?:"|$))')


def _near_keys() -> dict[str, set[str]]:
    spots = {ch: (r, c) for r, row in enumerate(_ROWS) for c, ch in enumerate(row)}
    return {
        a: {b for b, (r2, c2) in spots.items() if b != a and abs(r - r2) <= 1 and abs(c - c2) <= 1}
        for a, (r, c) in spots.items()
    }


_NEAR = _near_keys()


@lru_cache(maxsize=1)
def _checker():
    """the english word list, loaded on first use. a missing package means no fixes, not an error."""
    try:
        from spellchecker import SpellChecker

        return SpellChecker(distance=1)
    except Exception:
        return None


def _kind(word: str, fix: str) -> str:
    """how `fix` differs from `word` by one edit: swap, double, slip, missing, or '' if none."""
    if len(word) == len(fix):
        spots = [i for i, (a, b) in enumerate(zip(word, fix, strict=True)) if a != b]
        if len(spots) == 2 and spots[1] == spots[0] + 1:
            i = spots[0]
            if word[i] == fix[i + 1] and word[i + 1] == fix[i]:
                return "swap"
        if len(spots) == 1:
            a, b = word[spots[0]], fix[spots[0]]
            if (a in _VOWELS and b in _VOWELS) or b in _NEAR.get(a, ()):
                return "slip"
        return ""
    longer, shorter = (fix, word) if len(fix) > len(word) else (word, fix)
    if len(longer) - len(shorter) != 1:
        return ""
    kinds = set()
    for i, ch in enumerate(longer):
        if longer[:i] + longer[i + 1 :] == shorter:
            twin = (i > 0 and longer[i - 1] == ch) or (i + 1 < len(longer) and longer[i + 1] == ch)
            kinds.add("double" if twin else "missing")
    return "double" if "double" in kinds else ("missing" if kinds else "")


def _fix_word(checker, word: str) -> tuple[str, str] | None:
    """(fix, kind) for an unknown word, (word, "") for an unknown word with no safe fix."""
    low = word.lower()
    if not checker.unknown([low]):
        return None
    found: dict[str, list[tuple[float, str]]] = {}
    for fix in checker.known(checker.edit_distance_1(low)):
        if fix == low or not (fix.isascii() and fix.isalpha()):
            continue
        freq = checker.word_usage_frequency(fix)
        kind = _kind(low, fix)
        if freq < MIN_FREQUENCY or not kind:
            continue
        if kind not in ("swap", "double") and len(low) < OTHER_MIN:
            continue
        found.setdefault(kind, []).append((freq, fix))
    for kind in _ORDER:
        rows = sorted(found.get(kind, ()), reverse=True)
        if not rows:
            continue
        if len(rows) > 1 and rows[0][0] < CLEAR_WIN * rows[1][0]:
            break
        return (rows[0][1].capitalize() if word[0].isupper() else rows[0][1]), kind
    return word, ""


def correct(query: str) -> str | None:
    """the query with plain typos fixed, or None. the rest stays exactly as typed.

    left alone: words in quotes, words with digits or capitals inside (tft, iPhone, NASA),
    urls, operators like site:, bangs and everything after one, and any query with letters
    outside plain english (the word list is english only). a query with words the list can't
    place either (names, other languages) only gets the safe kinds of fix."""
    text = str(query or "")
    if not text.strip() or len(text) > MAX_CHARS or not text.isascii():
        return None
    checker = _checker()
    if checker is None:
        return None
    stop = False
    plans: dict[int, tuple[str, str]] = {}
    stuck = 0
    counter = 0

    def plan(match: re.Match) -> str:
        nonlocal stop, stuck, counter
        index, counter = counter, counter + 1
        token = match.group(0)
        if stop or token.startswith("!"):
            stop = True
            return token
        plain = _PLAIN.fullmatch(token)
        word = plain.group(2) if plain else ""
        if len(word) < SAFE_MIN or not (
            word.islower() or (word[0].isupper() and word[1:].islower())
        ):
            return token
        done = _fix_word(checker, word)
        if done and done[1]:
            plans[index] = (plain.group(1) + done[0] + plain.group(3), done[1])
        elif done:
            stuck += 1
        return token

    segments = _QUOTED.split(text)
    for index, part in enumerate(segments):
        if not index % 2:
            re.sub(r"\S+", plan, part)
    if not plans:
        return None
    if stuck:
        plans = {k: v for k, v in plans.items() if v[1] in ("swap", "double")}
    if not plans or len(plans) > MAX_FIXES:
        return None

    counter = 0

    def apply(match: re.Match) -> str:
        nonlocal counter
        index, counter = counter, counter + 1
        return plans[index][0] if index in plans else match.group(0)

    out = [
        part if index % 2 else re.sub(r"\S+", apply, part) for index, part in enumerate(segments)
    ]
    return "".join(out)


def _plain_query(query: str) -> bool:
    """no quotes, bangs, operators or urls: nothing an engine's fix could break."""
    return not re.search(r'["!]|\S:\S|\S\.\S|/', query)


def from_engine(query: str, suggestion) -> str | None:
    """an engine's own fix, if it is a believable one for this query."""
    if not isinstance(suggestion, str) or not _plain_query(query):
        return None
    fixed = re.sub(r"\s+", " ", suggestion).strip()
    original = re.sub(r"\s+", " ", query).strip()
    if not fixed or len(fixed) > MAX_CHARS or fixed.lower() == original.lower():
        return None
    # a spelling fix is a small change; anything bigger is a different search
    if difflib.SequenceMatcher(None, original.lower(), fixed.lower()).ratio() < 0.7:
        return None
    return fixed
