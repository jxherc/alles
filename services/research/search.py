"""
web search + page reading for the research engine.

the provider functions moved here from the old research_engine.py (they were
solid and already wired to alles settings). added: trafilatura-based page
reader and a chain helper that tells you which provider actually answered.
"""

import html as _htmlmod
import logging
import os
import re
import urllib.parse

import httpx

log = logging.getLogger("aide.research.search")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def _strip_tags(s: str) -> str:
    return _htmlmod.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _html_to_text(html: str) -> str:
    """crude but dependency-free html → readable text — the fallback when
    trafilatura isn't installed or comes back empty."""
    html = re.sub(
        r"(?is)<(script|style|noscript|head|nav|footer|header|aside|form|svg)[^>]*>.*?</\1>",
        " ",
        html,
    )
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section|article)>", "\n", html)
    text = _htmlmod.unescape(re.sub(r"(?is)<[^>]+>", " ", html))
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def fetch_webpage_content(url: str, timeout: int = 10) -> dict:
    """grab a page and pull the main article text out of it.

    returns {success, content, title, og_image}. trafilatura does the heavy
    lifting (strips nav/ads/boilerplate way better than regex); if it's not
    around or returns nothing, we fall back to the crude text stripper. never
    raises — research must not die on one bad link."""
    blank = {"success": False, "content": "", "title": "", "og_image": ""}
    if not url or not url.startswith("http"):
        return blank
    from services.net_guard import is_safe_url

    if not is_safe_url(url):  # SSRF guard: don't let a url point at internal/metadata addresses
        return blank
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"user-agent": _UA})
        ct = r.headers.get("content-type", "")
        if ct and "html" not in ct and "text" not in ct:
            return blank
        html = r.text
    except Exception as e:
        log.debug("fetch failed %s: %s", url, e)
        return blank

    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        title = _strip_tags(m.group(1))[:300]
    og = ""
    mo = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if mo:
        og = mo.group(1)

    content = ""
    try:
        import trafilatura

        content = (
            trafilatura.extract(
                html, include_comments=False, include_tables=True, favor_recall=True
            )
            or ""
        )
    except Exception:
        content = ""
    if not content.strip():
        content = _html_to_text(html)
    return {"success": bool(content.strip()), "content": content, "title": title, "og_image": og}


# ── providers ───────────────────────────────────────────────────────────────


async def _search_tavily(query, api_key, max_results=5):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_raw_content": False,
            },
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"url": x["url"], "title": x.get("title", ""), "snippet": x.get("content", "")}
        for x in data.get("results", [])
    ]


async def _search_brave(query, api_key, max_results=5):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": api_key, "user-agent": "aide-research/1.0"},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("description", "")}
        for x in data.get("web", {}).get("results", [])
        if x.get("url")
    ]


async def _search_searxng(query, base_url, max_results=5):
    url = base_url.rstrip("/") + "/search"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(url, params={"q": query, "format": "json"})
        r.raise_for_status()
        data = r.json()
    return [
        {"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", "")}
        for x in data.get("results", [])[:max_results]
        if x.get("url")
    ]


async def _search_google_pse(query, api_key, cx, max_results=5):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"url": x.get("link", ""), "title": x.get("title", ""), "snippet": x.get("snippet", "")}
        for x in data.get("items", [])
        if x.get("link")
    ]


async def _search_serper(query, api_key, max_results=5):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": max_results},
            headers={"X-API-KEY": api_key, "user-agent": "aide-research/1.0"},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"url": x.get("link", ""), "title": x.get("title", ""), "snippet": x.get("snippet", "")}
        for x in data.get("organic", [])
        if x.get("link")
    ]


def _ddg_unwrap(href: str) -> str:
    if "uddg=" in href:
        q = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href).query
        v = urllib.parse.parse_qs(q).get("uddg")
        if v:
            return v[0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_html(html: str) -> list:
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url = _ddg_unwrap(m.group(1))
        title = _strip_tags(m.group(2))
        if url.startswith("http") and title:
            out.append({"url": url, "title": title, "snippet": ""})
    snips = [
        _strip_tags(s) for s in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    ]
    for i, s in enumerate(snips):
        if i < len(out):
            out[i]["snippet"] = s
    if not out:  # lite.duckduckgo.com layout
        for m in re.finditer(
            r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
        ):
            url = _ddg_unwrap(m.group(1))
            title = _strip_tags(m.group(2))
            if url.startswith("http") and title:
                out.append({"url": url, "title": title, "snippet": ""})
    return out


async def _search_duckduckgo(query, max_results=6):
    # prefer the maintained ddg lib if present; else scrape the html endpoints.
    # the lib got renamed duckduckgo_search -> ddgs, so try the new name first.
    try:
        import asyncio

        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        def _go():
            with DDGS() as d:
                return [
                    {
                        "url": r.get("href", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                    }
                    for r in d.text(query, max_results=max_results)
                    if r.get("href")
                ]

        hits = await asyncio.to_thread(_go)
        if hits:
            return hits[:max_results]
    except Exception as e:
        log.debug("ddg lib failed, scraping: %s", e)
    headers = {"user-agent": _UA, "accept-language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=headers) as c:
        for attempt in ("html", "lite"):
            try:
                if attempt == "html":
                    r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
                else:
                    r = await c.get("https://lite.duckduckgo.com/lite/", params={"q": query})
                r.raise_for_status()
                hits = _parse_ddg_html(r.text)
                if hits:
                    return hits[:max_results]
            except Exception as e:
                log.warning("ddg %s failed: %s", attempt, e)
    return []


async def _search_wikipedia(query, max_results=6):
    async with httpx.AsyncClient(
        timeout=12, follow_redirects=True, headers={"user-agent": _UA}
    ) as c:
        r = await c.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "srprop": "snippet",
            },
        )
        r.raise_for_status()
        data = r.json()
    out = []
    for x in data.get("query", {}).get("search", []):
        title = x.get("title", "")
        if not title:
            continue
        out.append(
            {
                "url": "https://en.wikipedia.org/wiki/"
                + urllib.parse.quote(title.replace(" ", "_")),
                "title": title,
                "snippet": _strip_tags(x.get("snippet", "")),
            }
        )
    return out


def _provider_chain(primary: str, fallbacks) -> list:
    if primary == "disabled":
        return []
    if isinstance(fallbacks, str):
        fallbacks = [p.strip() for p in fallbacks.split(",") if p.strip()]
    if not isinstance(fallbacks, list):
        fallbacks = []
    # keyless engines stay as last-resort so research works with no api keys
    chain = [primary, *fallbacks, "duckduckgo", "wikipedia"]
    out = []
    for p in chain:
        p = str(p or "").strip()
        if p and p != "disabled" and p not in out:
            out.append(p)
    return out


async def _search_provider(name, query, settings, max_results):
    if name == "duckduckgo":
        return await _search_duckduckgo(query, max_results)
    if name == "wikipedia":
        return await _search_wikipedia(query, max_results)
    if name == "tavily":
        key = settings.get("tavily_api_key") or os.getenv("TAVILY_API_KEY", "")
        if not key:
            raise RuntimeError("missing tavily api key")
        return await _search_tavily(query, key, max_results)
    if name == "brave":
        key = settings.get("brave_api_key") or os.getenv("BRAVE_API_KEY", "")
        if not key:
            raise RuntimeError("missing brave api key")
        return await _search_brave(query, key, max_results)
    if name == "searxng":
        url = settings.get("searxng_url") or os.getenv("SEARXNG_URL", "")
        if not url:
            raise RuntimeError("missing searxng url")
        return await _search_searxng(query, url, max_results)
    if name == "google_pse":
        key = settings.get("google_pse_api_key") or os.getenv("GOOGLE_PSE_API_KEY", "")
        cx = settings.get("google_pse_cx") or os.getenv("GOOGLE_PSE_CX", "")
        if not key or not cx:
            raise RuntimeError("missing google pse credentials")
        return await _search_google_pse(query, key, cx, max_results)
    if name == "serper":
        key = settings.get("serper_api_key") or os.getenv("SERPER_API_KEY", "")
        if not key:
            raise RuntimeError("missing serper api key")
        return await _search_serper(query, key, max_results)
    raise RuntimeError(f"unknown search provider: {name}")


async def search_chain(query, override=None, max_results=10):
    """run the provider chain, return (results, provider_used, last_error).

    provider_used is the one that actually answered (for the report stats);
    last_error is set when every provider in the chain came back empty/failed
    so the engine can tell the user *why* instead of a bare 'no results'."""
    from core.settings import load_settings

    s = load_settings()
    primary = (
        (override or "").strip()
        or s.get("research_search_provider")
        or s.get("search_provider")
        or "duckduckgo"
    )
    if primary == "disabled":
        return [], None, None
    chain = _provider_chain(primary, s.get("search_fallback_chain"))
    last_err = None
    raised = False
    for name in chain:
        try:
            res = await _search_provider(name, query, s, max_results)
            if res:
                if name != primary:
                    log.info("research search fallback: %s", name)
                return res, name, None
            log.warning("research search: %s returned nothing", name)
        except Exception as e:
            raised = True
            last_err = f"{name}: {e}"
            log.warning("research search: %s failed: %s", name, e)
    if not raised and last_err is None:
        last_err = f"no results from search provider(s): {', '.join(chain) if chain else primary}"
    return [], None, last_err


async def web_search(query, max_results=5, provider=None):
    """back-compat: just the results, no provider/error tuple."""
    results, _, _ = await search_chain(query, provider, max_results)
    return results
