"""the panel beside andromeda's results that says what the searched thing is.

wikipedia's own summary of the page, shown only when the search names that page: its title, a
redirect to it, or the same words in another case or script variant. "toronto" gets toronto,
"how to get to toronto" gets nothing. the searched words leave this server for wikipedia and
nothing else about the owner goes along. a search engine set to "disabled" turns this off too.

one request per search. wikipedia allows a client that only shows an ip address 10 requests a
minute (https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits, read 2026-11-10), answers
429 with retry-after past that, and this module then stays quiet until that time.

request and reply (read 2026-11-10 from live replies; https://www.mediawiki.org/wiki/API:Query):
  https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2&redirects=1
      &converttitles=1&titles=nyc|Nyc|NYC&prop=extracts|pageimages|description|info|pageprops
      &exintro=1&explaintext=1&exlimit=max&inprop=url&piprop=thumbnail&pithumbsize=500
      &pilimit=max&ppprop=disambiguation
  -> {"query": {"normalized": [{"from": "nyc", "to": "Nyc"}],
                "redirects": [{"from": "Nyc", "to": "New York City"}],
                "pages": [{"title", "extract", "description", "fullurl",
                           "thumbnail": {"source", "width", "height"},
                           "missing": true, "pageprops": {"disambiguation": ""}}]}}
"""

from __future__ import annotations

import re
import time
import unicodedata

import httpx

from services.research.search import WIKIPEDIA_UA, search_region

MAX_QUERY = 60
MAX_WORDS = 6
MAX_EXTRACT = 520
_TTL = 900
_KEEP = 256
_cache: dict[tuple, tuple[float, dict | None]] = {}
_quiet_until = 0.0
# a query in one of these scripts is asked in that language's wikipedia
_SCRIPT_WIKIS = {"ja", "zh", "ko", "ru", "ar"}
# other languages alles speaks that have their own wikipedia for latin text
_APP_WIKIS = {"es", "fr"}
_OPERATOR = re.compile(r"\b(?:site|inurl|intitle|filetype|ext|cache|related):", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])")


def _norm(text: str) -> str:
    """letters and digits only, one case: "The Weeknd" and "the weeknd?" are the same name."""
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in folded).split())


def wikis(query: str, app_language: str = "") -> list[str]:
    """which wikipedias to ask, first choice first."""
    language = search_region(query).split("-")[1]
    if language in _SCRIPT_WIKIS:
        return [language]
    app = str(app_language or "").split("-")[0].lower()
    return [app, "en"] if app in _APP_WIKIS else ["en"]


def wanted(query: str) -> bool:
    """a short plain name, not a question for an engine."""
    query = " ".join(str(query or "").split())
    return bool(
        query
        and len(query) <= MAX_QUERY
        and len(query.split()) <= MAX_WORDS
        and not query.startswith("!")
        and not _OPERATOR.search(query)
        and "://" not in query
        and _norm(query)
    )


def _short(extract: str) -> str:
    """whole sentences up to MAX_EXTRACT; wikipedia's first paragraph can run to 1500 characters."""
    text = " ".join(str(extract or "").split())
    if len(text) <= MAX_EXTRACT:
        return text
    kept = ""
    for sentence in _SENTENCE_END.split(text):
        if not sentence:
            continue
        gap = " " if kept and kept[-1] in ".!?" else ""
        if len(kept) + len(gap) + len(sentence) > MAX_EXTRACT:
            break
        kept += gap + sentence
    return kept or text[: MAX_EXTRACT - 1].rstrip() + "…"


def _names(query: str) -> list[str]:
    """the ways the same name may be written as a title. wikipedia only forgives the case of
    the first letter, and redirects cover the rest for most names."""
    words = query.split()
    capped = " ".join(word[:1].upper() + word[1:] for word in words)
    lowered = " ".join(word[:1].upper() + word[1:].lower() for word in words)
    names = [query, capped, lowered]
    if len(query) <= 5:
        names.append(query.upper())
    out: list[str] = []
    for name in names:
        if name and name not in out:
            out.append(name)
    return out


def _resolve(names: list[str], found: dict) -> tuple[dict | None, bool]:
    """the first way of writing the name that is a real page, and whether a redirect led there."""
    steps = {}
    for key in ("normalized", "converted", "redirects"):
        for row in found.get(key) or []:
            steps.setdefault(key, {})[str(row.get("from"))] = str(row.get("to"))
    pages = {str(page.get("title")): page for page in found.get("pages") or []}
    for name in names:
        title = steps.get("normalized", {}).get(name, name)
        title = steps.get("converted", {}).get(title, title)
        target = steps.get("redirects", {}).get(title, title)
        page = pages.get(target)
        if page and not page.get("missing") and not page.get("invalid"):
            return page, target != title
    return None, False


def _panel(page: dict, language: str, redirected: bool, query: str) -> dict | None:
    if "disambiguation" in (page.get("pageprops") or {}):
        return None  # a page that names many things
    title = " ".join(str(page.get("title") or "").split())
    extract = _short(page.get("extract") or "")
    url = str(page.get("fullurl") or "")
    description = " ".join(str(page.get("description") or "").split())[:200]
    if not title or not extract or not url.startswith(f"https://{language}.wikipedia.org/"):
        return None
    if redirected and _norm(title) != _norm(query) and not description:
        # a phrase someone pointed at a list or a section: wikipedia gives no short description
        return None
    panel = {
        "title": title[:200],
        "description": description,
        "extract": extract,
        "url": url,
        "language": language,
        "source": "wikipedia",
    }
    thumbnail = page.get("thumbnail") or {}
    source = str(thumbnail.get("source") or "")
    width, height = thumbnail.get("width"), thumbnail.get("height")
    if source.startswith("https://") and isinstance(width, int) and isinstance(height, int):
        panel.update(image=source, image_width=width, image_height=height)
    return panel


class _Busy(Exception):
    def __init__(self, seconds: float):
        self.seconds = seconds


async def _ask(client: httpx.AsyncClient, language: str, query: str, variant: str) -> dict | None:
    names = _names(query)
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "converttitles": "1",
        "titles": "|".join(names),
        "prop": "extracts|pageimages|description|info|pageprops",
        "exintro": "1",
        "explaintext": "1",
        "exlimit": "max",
        "inprop": "url|varianttitles",
        "piprop": "thumbnail",
        "pithumbsize": "500",
        "pilimit": "max",
        "ppprop": "disambiguation",
    }
    if language == "zh":
        # chinese wikipedia writes one page in both scripts and converts to the one asked for
        params["variant"] = variant
    reply = await client.get(f"https://{language}.wikipedia.org/w/api.php", params=params)
    if reply.status_code == 429:
        try:
            seconds = float(reply.headers.get("retry-after") or 30)
        except ValueError:
            seconds = 30
        raise _Busy(min(max(seconds, 5), 600))
    reply.raise_for_status()
    page, redirected = _resolve(names, reply.json().get("query") or {})
    panel = _panel(page, language, redirected, query) if page else None
    if panel and language == "zh":
        # the title in the same script as the text under it
        shown = (page.get("varianttitles") or {}).get(variant)
        if isinstance(shown, str) and shown.strip():
            panel["title"] = " ".join(shown.split())[:200]
    return panel


async def lookup(query: str, app_language: str = "") -> dict | None:
    """the panel for `query`, or None when it names no single page or nothing answers in time."""
    global _quiet_until
    query = " ".join(str(query or "").split())
    if not wanted(query) or "|" in query:
        return None
    languages = wikis(query, app_language)
    variant = (
        "zh-tw" if str(app_language or "").lower() in ("zh-hant", "zh-tw", "zh-hk") else "zh-cn"
    )
    key = (_norm(query), tuple(languages), variant)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _TTL:
        return hit[1]
    if now < _quiet_until:
        return None
    found = None
    answered = False
    async with httpx.AsyncClient(timeout=3, headers={"user-agent": WIKIPEDIA_UA}) as client:
        for language in languages:
            try:
                found = await _ask(client, language, query, variant)
                answered = True
            except _Busy as busy:
                _quiet_until = time.monotonic() + busy.seconds
                break
            except Exception:
                # a side request for a convenience: the results page must not notice
                found = None
            if found:
                break
    if answered:
        # a wikipedia that did not answer is asked again next time
        if len(_cache) >= _KEEP:
            for old in sorted(_cache, key=lambda item: _cache[item][0])[: _KEEP // 4]:
                _cache.pop(old, None)
        _cache[key] = (now, found)
    return found
