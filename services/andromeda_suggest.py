"""what people search next, for the list under andromeda's search box.

google's suggest endpoint, the one a browser's own search box uses, answers first; duckduckgo's
is asked when it gives nothing or fails. the typed text leaves this server for it and nothing
else about the owner goes along: no cookies, no account, a plain user agent. a search engine
set to "disabled" turns this off with it.

request and reply shapes (read 2026-11-10 from live replies, neither has formal docs):
  https://suggestqueries.google.com/complete/search?client=firefox&q=nik  -> ["nik", ["nike", ...]]
  https://duckduckgo.com/ac/?q=nik&type=list                              -> ["nik", ["nike", ...]]
"""

from __future__ import annotations

import time

import httpx

from services.research.search import search_region

MAX_QUERY = 120
MAX_SUGGESTIONS = 8
_TTL = 300
_KEEP = 256
_cache: dict[str, tuple[float, list[str]]] = {}
_UA = "Mozilla/5.0 (compatible; alles)"


def _clean(query: str, data) -> list[str]:
    rows = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    typed = query.strip().lower()
    out: list[str] = []
    for row in rows:
        text = " ".join(str(row).split()) if isinstance(row, str) else ""
        if text and text.lower() != typed and len(text) <= 200 and text not in out:
            out.append(text)
    return out[:MAX_SUGGESTIONS]


async def _ask(client: httpx.AsyncClient, url: str, params: dict, query: str) -> list[str]:
    reply = await client.get(url, params=params)
    reply.raise_for_status()
    return _clean(query, reply.json())


async def suggest(query: str) -> list[str]:
    """up to MAX_SUGGESTIONS completions of `query`, [] when nothing answers in time."""
    query = " ".join(str(query or "").split())
    if not query or len(query) > MAX_QUERY:
        return []
    key = query.lower()
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _TTL:
        return hit[1]
    # the query's own language, so chinese text gets chinese completions
    country, language = search_region(query).split("-")
    found: list[str] = []
    async with httpx.AsyncClient(timeout=2.5, headers={"user-agent": _UA}) as client:
        for url, params in (
            (
                "https://suggestqueries.google.com/complete/search",
                {
                    "client": "firefox",
                    "q": query,
                    "hl": language,
                    "gl": country,
                    "ie": "utf-8",
                    "oe": "utf-8",
                },
            ),
            (
                "https://duckduckgo.com/ac/",
                {"q": query, "type": "list", "kl": f"{country}-{language}"},
            ),
        ):
            try:
                found = await _ask(client, url, params, query)
            except Exception:
                # a side request for a convenience: whatever went wrong, typing must not notice
                found = []
            if found:
                break
    if len(_cache) >= _KEEP:
        for old in sorted(_cache, key=lambda item: _cache[item][0])[: _KEEP // 4]:
            _cache.pop(old, None)
    _cache[key] = (now, found)
    return found
