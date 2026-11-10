"""
web search + page reading for the research engine.

the provider functions moved here from the old research_engine.py (they were
solid and already wired to alles settings). added: trafilatura-based page
reader and a chain helper that tells you which provider actually answered.
"""

import asyncio
import html as _htmlmod
import json
import logging
import os
import re
import threading
import urllib.parse
from dataclasses import dataclass

import httpx

from services.research import engines as _engines
from services.research.engines import BY_ID, CUSTOM_PREFIX

log = logging.getLogger("aide.research.search")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
# wikipedia refuses clients that don't say who they are (403 "respect our robot policy", seen
# nov 10) and asks for a name with a link, never a browser's:
# https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy
WIKIPEDIA_UA = "alles (https://github.com/jxherc/alles)"
_KNOWN_PROVIDERS = frozenset({*BY_ID, "wikipedia"})
# the keyless engines for web results, best first. ddgs runs them in this order and only goes
# down the list while it still needs rows, so a page comes from the best engine that answers.
# shuffled, a whole page came from whichever engine came up (yandex as often as the bing ones),
# under wikipedia and grokipedia every time. left out: startpage (a captcha page for every
# server request) and grokipedia (generated articles, not a search engine)
# also left out since nov 10: mojeek and yandex. they were the last resort when the others gave
# nothing, and what they gave was worse than nothing (shop listings for "nike", adult spam for
# a chinese question). no results and a retry is the honest answer then
_TEXT_ENGINES = ("wikipedia", "duckduckgo", "google", "brave", "yahoo")

# ddgs asks every engine in one "country-language" region and defaults to us-en: google then
# returns english pages only and wikipedia is the english one, so a query in another script
# found the wrong things (苹果 gave the english article on a beijing subway station)
_SCRIPT_REGIONS = (
    (re.compile(r"[\u3040-\u30ff]"), "jp-ja"),  # kana first: japanese also uses han
    (re.compile(r"[\uac00-\ud7af]"), "kr-ko"),
    (re.compile(r"[\u4e00-\u9fff]"), "cn-zh"),
    (re.compile(r"[\u0400-\u04ff]"), "ru-ru"),
    (re.compile(r"[\u0600-\u06ff]"), "xa-ar"),
)


def search_region(query: str) -> str:
    """the region for a query: its own script's when it isn't latin, else us-en."""
    for pattern, region in _SCRIPT_REGIONS:
        if pattern.search(query or ""):
            return region
    return "us-en"


class SearchProviderFailure(RuntimeError):
    """A provider failure with a stable code that is safe to show to the user."""

    def __init__(self, failure_type: str):
        super().__init__(failure_type)
        self.failure_type = failure_type


@dataclass(frozen=True)
class SearchReport:
    results: list
    provider: str | None
    error: str | None
    failure_type: str
    attempted_sources: tuple[str, ...]
    # the engine's own spelling fix for the query, when it gave one
    correction: str = ""
    # brave searches the fixed query itself; searxng and google pse answer for the typed one
    correction_applied: bool = False
    # the chosen engine, when another one answered in its place, and why: "refused" (it said
    # no to these words), "empty" (it found nothing) or "failed" (anything else)
    backup_for: str = ""
    backup_reason: str = ""


class Rows(list):
    """provider rows that also carry the engine's spelling fix for the query."""

    correction = ""
    correction_applied = False


class SearchChainResult(tuple):
    """Three-item legacy tuple carrying optional safe diagnostics."""

    def __new__(cls, report: SearchReport):
        value = super().__new__(cls, (report.results, report.provider, report.error))
        value.failure_type = report.failure_type
        value.attempted_sources = report.attempted_sources
        value.correction = report.correction
        value.backup_for = report.backup_for
        value.backup_reason = report.backup_reason
        value.correction_applied = report.correction_applied
        return value


def _safe_provider_name(value: str) -> str:
    name = str(value or "").strip()
    if name.startswith(CUSTOM_PREFIX) and re.fullmatch(r"custom-[0-9a-f]{8}", name):
        return name
    return name if name in _KNOWN_PROVIDERS else "unknown"


def _safe_failure_type(error: Exception) -> str:
    if isinstance(error, SearchProviderFailure):
        return error.failure_type
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "http_error"
    if isinstance(error, httpx.RequestError):
        return "network_error"
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        return "invalid_response"
    return "provider_error"


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


# trafilatura/lxml crash the whole process ("double free or corruption") when pages are
# parsed in parallel threads. fetching stays parallel; parsing takes turns.
_PARSE_LOCK = threading.Lock()


def fetch_webpage_content(url: str, timeout: int = 10) -> dict:
    """grab a page and pull the main article text out of it.

    returns {success, content, title, og_image}. trafilatura does the heavy
    lifting (strips nav/ads/boilerplate way better than regex); if it's not
    around or returns nothing, we fall back to the crude text stripper. never
    raises — research must not die on one bad link."""
    blank = {"success": False, "content": "", "title": "", "og_image": ""}
    if not url or not url.startswith("http"):
        return blank
    from services.net_guard import safe_get

    try:
        # SSRF guard re-checked on every redirect hop (a public url can 302 to internal/metadata)
        r = safe_get(url, timeout=timeout, headers={"user-agent": _UA})
        r.raise_for_status()
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

        with _PARSE_LOCK:
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
    rows = Rows(
        {"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("description", "")}
        for x in data.get("web", {}).get("results", [])
        if x.get("url")
    )
    # api-dashboard.search.brave.com/api-reference/web/search/get: query.altered is the
    # spellchecker's fix, and with the spellcheck flag on (the default) "the modified query is
    # always used for search"
    rows.correction = (data.get("query") or {}).get("altered") or ""
    rows.correction_applied = True
    return rows


async def _search_searxng(query, base_url, max_results=5, category="all"):
    from services.managed_searxng import managed_url

    base = base_url.rstrip("/")
    local_base = managed_url().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(base)
    except ValueError as exc:
        raise SearchProviderFailure("configuration") from exc
    loopback = (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
    if base != local_base and not base.startswith("https://") and not loopback:
        raise SearchProviderFailure("configuration")

    output = Rows()
    seen: set[str] = set()
    local_client = (
        httpx.AsyncClient(timeout=15, follow_redirects=False)
        if base == local_base or loopback
        else None
    )
    try:
        for page in range(1, min(64, max(1, max_results)) + 1):
            params = {"q": query, "format": "json", "pageno": page}
            if category in {"images", "news", "videos"}:
                params["categories"] = category
            url = base + "/search?" + urllib.parse.urlencode(params)
            if local_client is not None:
                response = await local_client.get(url)
            else:
                from services.net_guard import safe_get_async

                response = await safe_get_async(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            rows = data.get("results", []) if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise SearchProviderFailure("invalid_response")
            # searx/webutils.py get_json_response: "corrections" lists fixes for the typed query
            fixes = data.get("corrections")
            if page == 1 and isinstance(fixes, list) and fixes and isinstance(fixes[0], str):
                output.correction = fixes[0]
            added = 0
            for row in rows:
                result_url = row.get("url", "")
                if not result_url or result_url in seen:
                    continue
                seen.add(result_url)
                engines = row.get("engines") if isinstance(row.get("engines"), list) else []
                output.append(
                    {
                        "url": result_url,
                        "title": row.get("title", ""),
                        "snippet": row.get("content", ""),
                        "publisher": row.get("publisher")
                        or row.get("source")
                        or (engines[0] if engines else ""),
                        "favicon_url": row.get("favicon") or "",
                        "thumbnail_url": row.get("thumbnail_src")
                        or row.get("thumbnail")
                        or row.get("img_src")
                        or "",
                        "image_url": row.get("img_src") or row.get("thumbnail_src") or "",
                        "published": row.get("publishedDate") or row.get("published_date") or "",
                        "duration": row.get("length") or row.get("duration") or "",
                        "width": row.get("width") or row.get("img_width"),
                        "height": row.get("height") or row.get("img_height"),
                    }
                )
                added += 1
                if len(output) >= max_results:
                    return output
            if not rows or not added:
                break
    finally:
        if local_client is not None:
            await local_client.aclose()
    return output


async def _search_google_pse(query, api_key, cx, max_results=5):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
        )
        r.raise_for_status()
        data = r.json()
    rows = Rows(
        {"url": x.get("link", ""), "title": x.get("title", ""), "snippet": x.get("snippet", "")}
        for x in data.get("items", [])
        if x.get("link")
    )
    # developers.google.com/custom-search/v1/reference/rest/v1/Search: spelling.correctedQuery
    rows.correction = (data.get("spelling") or {}).get("correctedQuery") or ""
    return rows


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


def _plain_snippet(text: str) -> str:
    """exa highlights are page markdown; a result row wants plain words."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links and images keep their text
    text = re.sub(r"(^|\s)#{1,6}\s+", r"\1", text)  # headings
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"(^|\s)[*-]\s+", r"\1", text)  # list bullets
    return re.sub(r"\s+", " ", text).strip()


async def _search_exa(query, api_key, max_results=5, category="all"):
    # exa is a web index, not an image or video engine; empty hands those to the next engine
    if category in ("images", "videos"):
        return []
    # "auto" is exa's default and the mode its docs recommend; "instant" (used here before) is a
    # legacy mode that trades depth for speed (docs.exa.ai/reference/search, read 2026-11-09).
    # highlights give the result list a snippet
    body = {
        "query": query,
        "type": "auto",
        "numResults": max_results,
        "contents": {"highlights": {"maxCharacters": 320}},
    }
    if category == "news":
        body["category"] = "news"
    headers = {"x-api-key": api_key, "user-agent": "aide-research/1.0"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.exa.ai/search", json=body, headers=headers)
        # exa's error page (docs.exa.ai/reference/error-codes, read 2026-11-10): 429, 500, 503
        # and 504 are worth another try after a pause; 403 is its content filter or the plan
        # saying no, and asking again changes nothing
        if r.status_code in (429, 500, 503, 504):
            try:
                pause = float(r.headers.get("retry-after") or 0.6)
            except ValueError:
                pause = 0.6
            await asyncio.sleep(min(max(pause, 0.2), 2.0))
            r = await c.post("https://api.exa.ai/search", json=body, headers=headers)
        if r.status_code == 403:
            raise SearchProviderFailure("refused")
        r.raise_for_status()
        data = r.json()
    return [
        {
            "url": x["url"],
            "title": x.get("title") or "",
            "snippet": _plain_snippet(" ".join(x.get("highlights") or []))[:500],
            "published": x.get("publishedDate") or "",
            "favicon_url": x.get("favicon") or "",
        }
        for x in data.get("results", [])
        if x.get("url")
    ]


async def _post_json(url, key, body, header="authorization", prefix="Bearer "):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            url, json=body, headers={header: prefix + key, "user-agent": "aide-research/1.0"}
        )
        r.raise_for_status()
        return r.json()


def _rows(items, url="url", title="title", snippet="snippet", date=None):
    out = []
    for x in items or []:
        if not isinstance(x, dict) or not x.get(url):
            continue
        text = x.get(snippet)
        if isinstance(text, list):
            text = " ".join(str(part) for part in text)
        row = {"url": x[url], "title": x.get(title) or "", "snippet": str(text or "")[:500]}
        if date and x.get(date):
            row["published"] = x[date]
        if x.get("site_name"):
            row["site_name"] = str(x["site_name"])[:80]
        if x.get("site_icon"):
            row["favicon_url"] = str(x["site_icon"])
        out.append(row)
    return out


async def _search_deepseek(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    data = await _post_json(
        "https://api.deepseek.com/v1/tools/search",
        api_key,
        {"query": query[:128], "count": max_results},
    )
    return _rows(data.get("results"), date="date")


async def _search_firecrawl(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    body = {"query": query, "limit": max_results}
    if category == "news":
        body["sources"] = ["news"]
    data = (await _post_json("https://api.firecrawl.dev/v2/search", api_key, body)).get("data")
    data = data if isinstance(data, dict) else {}
    if category == "news":
        return _rows(data.get("news"), date="date")
    return _rows(data.get("web"), snippet="description")


async def _search_you(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    data = await _post_json(
        "https://ydc-index.io/v1/search",
        api_key,
        {"query": query, "count": max_results},
        header="x-api-key",
        prefix="",
    )
    sections = data.get("results") if isinstance(data.get("results"), dict) else {}
    items = sections.get("news" if category == "news" else "web")
    rows = _rows(items, snippet="description", date="page_age")
    return rows[:max_results]


async def _search_linkup(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    data = await _post_json(
        "https://api.linkup.so/v1/search",
        api_key,
        {"q": query, "depth": "fast", "outputType": "searchResults", "maxResults": max_results},
    )
    items = [
        x for x in data.get("results") or [] if isinstance(x, dict) and x.get("type") != "image"
    ]
    return _rows(items, title="name", snippet="content")


async def _search_perplexity(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    body = {"query": query, "max_results": min(max_results, 20), "search_type": "fast"}
    if category == "news":
        body["search_recency_filter"] = "week"
    data = await _post_json("https://api.perplexity.ai/search", api_key, body)
    return _rows(data.get("results"), date="date")


async def _search_jina(query, api_key, max_results=5, category="all"):
    if category in ("images", "videos"):
        return []
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://s.jina.ai/",
            params={"q": query, "count": min(max_results, 20)},
            headers={
                "authorization": f"Bearer {api_key}",
                "accept": "application/json",
                "x-respond-with": "no-content",
                "user-agent": "aide-research/1.0",
            },
        )
        r.raise_for_status()
        data = r.json()
    # the list comes back bare or under "data"
    items = data.get("data") if isinstance(data, dict) else data
    return _rows(items if isinstance(items, list) else [], snippet="description", date="date")


_KEYED_SEARCH = {
    "deepseek": _search_deepseek,
    "firecrawl": _search_firecrawl,
    "you": _search_you,
    "linkup": _search_linkup,
    "perplexity": _search_perplexity,
    "jina": _search_jina,
}


async def _search_custom(row, key, query, max_results=5):
    method, url, headers, body = _engines.custom_request(row, key, query, max_results)
    # checked again here: settings can be edited by hand outside the form
    if not _engines._allowed_address(url):
        raise SearchProviderFailure("configuration")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as c:
        r = await c.request(method, url, headers=headers, content=body or None)
        r.raise_for_status()
        data = r.json()
    return _engines.custom_results(row, data, max_results)


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


def yahoo_phone_rows(tree) -> list[tuple[str, str, str]]:
    """(title, link, text) rows from the page yahoo sends a phone browser. read from saved pages
    on 2026-11-10: each result is `h3.title > a.s-title` with the title in aria-label and yahoo's
    redirect in href, and its text in the next `p.s-desc` (a leading `span.s-time` is the date)."""
    links = tree.xpath("//h3[contains(@class, 'title')]/a[contains(@class, 's-title')][@href]")
    rows = []
    for link in links:
        title = " ".join(str(link.get("aria-label") or "".join(link.xpath("./text()"))).split())
        body = ""
        for text in link.xpath("following::p[contains(@class, 's-desc')][1]"):
            owner = text.xpath("preceding::a[contains(@class, 's-title')][1]")
            if owner and owner[0] is link:  # the text under this title, not the next result's
                words = text.xpath(".//text()[not(ancestor::span[contains(@class, 's-time')])]")
                body = " ".join("".join(words).split())
        if title:
            rows.append((title, str(link.get("href")), body))
    return rows


def _read_both_yahoo_pages() -> None:
    """ddgs poses as a random browser. when that is a phone, yahoo answers with its phone page,
    which ddgs's yahoo engine can't read: about half its replies came back as "no results"
    (measured nov 9 and 10) and the search fell to far worse engines. this puts the same engine
    back with a second reader for that page."""
    try:
        from ddgs.engines import ENGINES
        from ddgs.engines.yahoo import Yahoo
    except ImportError:
        return
    engines = ENGINES.get("text")
    if not isinstance(engines, dict) or getattr(engines.get("yahoo"), "reads_phone_page", False):
        return

    class YahooBothPages(Yahoo):
        reads_phone_page = True
        # a result with a video strip under it has more than one h3 and link inside: ddgs joins
        # them all ("4 Ways to Tie a Tie - wikiHowHow to tie a tie - YouTube"). the first is the result
        elements_xpath = {
            **Yahoo.elements_xpath,
            "title": "(.//div[contains(@class, 'Title')]//h3)[1]//text()",
            "href": "(.//div[contains(@class, 'Title')]//a/@href)[1]",
        }

        def extract_results(self, html_text):
            rows = super().extract_results(html_text)
            if rows:
                return rows
            for title, href, body in yahoo_phone_rows(self.extract_tree(html_text)):
                row = self.result_type()
                row.title, row.href, row.body = title, href, body
                rows.append(row)
            return rows

    engines["yahoo"] = YahooBothPages


def _text_backends(names=_TEXT_ENGINES):
    """the engines ddgs asks for web results, in the order given."""
    try:
        from ddgs.engines import ENGINES
    except ImportError:  # old duckduckgo_search: duckduckgo only, nothing to order
        return {}
    _read_both_yahoo_pages()
    keys = [k for k in names if k in ENGINES.get("text", {})]
    return {"backend": ",".join(keys)} if keys else {}


def _web_rows(d, query: str, max_results: int, region: str) -> list:
    """web results from the keyless engines, asked up to 3 times: an engine that answered
    nothing once (a busy moment, a page with no results in it) usually answers on the next
    request. measured nov 10: yahoo, the one that answers from most networks, gives a readable
    page 5 times in 6. a second page fills a short first one."""
    backends = _text_backends()
    rows = []
    for _attempt in range(3):
        try:
            found = d.text(query, max_results=max_results, region=region, **backends)
        except Exception as error:  # ddgs raises when every engine came back empty
            log.debug("keyless engines %s: %s", backends.get("backend", "default"), error)
            found = []
        rows = found or rows
        # wikipedia alone is one article, not a results page: worth one more try, and still
        # better than nothing if that is all there is
        if any("wikipedia.org" not in str(r.get("href") or "") for r in rows) or not backends:
            break
    if rows and len(rows) < max_results and backends:
        try:
            more = d.text(query, max_results=max_results, region=region, page=2, **backends)
        except Exception:
            more = []
        seen = {r.get("href") for r in rows}
        rows = rows + [r for r in more if r.get("href") not in seen]
    return rows


async def _search_duckduckgo(query, max_results=6, category="all"):
    # prefer the maintained ddg lib if present; else scrape the html endpoints.
    # the lib got renamed duckduckgo_search -> ddgs, so try the new name first.
    try:
        import asyncio

        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        region = search_region(query)

        def _go():
            with DDGS() as d:
                if category == "images":
                    rows = d.images(query, max_results=max_results, region=region)
                    return [
                        {
                            "url": r.get("url") or r.get("image") or "",
                            "title": r.get("title") or r.get("source") or "image result",
                            "snippet": r.get("source") or "",
                            "publisher": r.get("source") or "",
                            "thumbnail_url": r.get("thumbnail") or r.get("image") or "",
                            "image_url": r.get("image") or r.get("thumbnail") or "",
                            "width": r.get("width"),
                            "height": r.get("height"),
                        }
                        for r in rows
                        if r.get("url") or r.get("image")
                    ]
                if category == "news":
                    rows = d.news(query, max_results=max_results, region=region)
                    return [
                        {
                            "url": r.get("url") or "",
                            "title": r.get("title") or "",
                            "snippet": r.get("body") or "",
                            "publisher": r.get("source") or "",
                            "thumbnail_url": r.get("image") or "",
                            "published": r.get("date") or "",
                        }
                        for r in rows
                        if r.get("url")
                    ]
                if category == "videos":
                    rows = d.videos(query, max_results=max_results, region=region)
                    output = []
                    for r in rows:
                        images = r.get("images") if isinstance(r.get("images"), dict) else {}
                        output.append(
                            {
                                "url": r.get("content") or r.get("url") or "",
                                "title": r.get("title") or "",
                                "snippet": r.get("description") or r.get("publisher") or "",
                                "publisher": r.get("publisher") or "",
                                "thumbnail_url": images.get("large")
                                or images.get("medium")
                                or images.get("small")
                                or "",
                                "duration": r.get("duration") or "",
                                "published": r.get("published") or r.get("date") or "",
                            }
                        )
                    return [row for row in output if row["url"]]
                return [
                    {
                        "url": r.get("href", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                    }
                    for r in _web_rows(d, query, max_results, region)
                    if r.get("href")
                ]

        hits = await asyncio.to_thread(_go)
        if hits:
            return hits[:max_results]
    except Exception as e:
        log.debug("ddg lib failed, scraping: %s", e)
    if category != "all":
        return []
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
        timeout=12, follow_redirects=True, headers={"user-agent": WIKIPEDIA_UA}
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
    # the chain someone picked is the chain. "fallback: none" is [] and must stay none: tacking
    # duckduckgo and wikipedia on anyway sent the query to engines they had turned off. only a
    # chain never set at all gets the keyless engines, so research works with no api keys
    if not isinstance(fallbacks, list):
        fallbacks = ["duckduckgo", "wikipedia"]
    chain = [primary, *fallbacks]
    out = []
    for p in chain:
        p = str(p or "").strip()
        if p and p != "disabled" and p not in out:
            out.append(p)
    return out


def _category_query(query: str, category: str) -> str:
    if category == "news":
        return f"{query} latest news"
    if category == "videos":
        return f"{query} video"
    if category == "images":
        return f"{query} images"
    return query


async def _search_provider(name, query, settings, max_results, category="all"):
    if name == "duckduckgo":
        return await _search_duckduckgo(query, max_results, category)
    if name == "wikipedia":
        if category != "all":
            return []
        return await _search_wikipedia(query, max_results)
    provider_query = _category_query(query, category)
    if name == "tavily":
        key = settings.get("tavily_api_key") or os.getenv("TAVILY_API_KEY", "")
        if not key:
            raise SearchProviderFailure("configuration")
        return await _search_tavily(provider_query, key, max_results)
    if name == "brave":
        key = settings.get("brave_api_key") or os.getenv("BRAVE_API_KEY", "")
        if not key:
            raise SearchProviderFailure("configuration")
        return await _search_brave(provider_query, key, max_results)
    if name == "searxng":
        url = settings.get("searxng_url") or os.getenv("SEARXNG_URL", "")
        if not url:
            raise SearchProviderFailure("configuration")
        return await _search_searxng(query, url, max_results, category)
    if name == "google_pse":
        key = settings.get("google_pse_api_key") or os.getenv("GOOGLE_PSE_API_KEY", "")
        cx = settings.get("google_pse_cx") or os.getenv("GOOGLE_PSE_CX", "")
        if not key or not cx:
            raise SearchProviderFailure("configuration")
        return await _search_google_pse(provider_query, key, cx, max_results)
    if name in _KEYED_SEARCH:
        key = settings.get(BY_ID[name].key) or ""
        if not key:
            raise SearchProviderFailure("configuration")
        return await _KEYED_SEARCH[name](query, key, max_results, category)
    if name.startswith(CUSTOM_PREFIX):
        row = _engines.custom_engine(settings, name)
        if not row:
            raise SearchProviderFailure("configuration")
        if category in ("images", "videos"):
            return []
        keys = settings.get("custom_search_keys")
        key = keys.get(name, "") if isinstance(keys, dict) else ""
        return await _search_custom(row, key, query, max_results)
    if name == "exa":
        key = settings.get("exa_api_key") or os.getenv("EXA_API_KEY", "")
        if not key:
            raise SearchProviderFailure("configuration")
        return await _search_exa(query, key, max_results, category)
    if name == "serper":
        key = settings.get("serper_api_key") or os.getenv("SERPER_API_KEY", "")
        if not key:
            raise SearchProviderFailure("configuration")
        return await _search_serper(provider_query, key, max_results)
    raise SearchProviderFailure("configuration")


async def search_chain_report(query, override=None, max_results=10, category="all") -> SearchReport:
    """Run every needed provider and return safe, structured diagnostics."""
    from core.settings import load_settings

    settings = load_settings()
    primary = (
        (override or "").strip()
        or settings.get("research_search_provider")
        or settings.get("search_provider")
        or "duckduckgo"
    )
    if primary == "disabled":
        return SearchReport([], None, None, "disabled", ())
    # A person choosing one exact engine expects that engine, not a silent switch.
    # Automatic searches keep the configured fallback chain.
    chain = (
        [primary]
        if (override or "").strip()
        else _provider_chain(primary, settings.get("search_fallback_chain"))
    )
    attempted = []
    failure_type = ""
    # why the chosen engine did not answer, for a search it can answer (exa has no pictures or
    # videos, so its empty hand there is no news)
    lost = ""
    tells = category in ("all", "news")
    # an engine can fix the spelling and still find nothing, so keep the first fix it gave
    fix = ("", False)
    for name in chain:
        safe_name = _safe_provider_name(name)
        if safe_name not in attempted:
            attempted.append(safe_name)
        try:
            results = await _search_provider(name, query, settings, max_results, category)
            if not fix[0] and getattr(results, "correction", ""):
                fix = (str(results.correction), bool(results.correction_applied))
            if results:
                if name != primary:
                    log.info("research search fallback: %s", safe_name)
                # a fix brave already searched doesn't describe another engine's results
                own = bool(getattr(results, "correction", ""))
                backup = bool(lost) and name != primary
                return SearchReport(
                    results,
                    safe_name,
                    None,
                    "",
                    tuple(attempted),
                    fix[0],
                    fix[1] and own,
                    _safe_provider_name(primary) if backup else "",
                    lost if backup else "",
                )
            log.warning("research search: %s returned nothing", safe_name)
            if name == primary and tells:
                lost = "empty"
        except Exception as error:
            current_type = _safe_failure_type(error)
            failure_type = failure_type or current_type
            log.warning("research search: %s failed (%s)", safe_name, current_type)
            if name == primary and tells:
                lost = "refused" if current_type == "refused" else "failed"
    if failure_type:
        safe_error = f"search providers failed ({failure_type})"
    else:
        failure_type = "no_results"
        safe_error = "search providers returned no results"
    return SearchReport([], None, safe_error, failure_type, tuple(attempted), *fix)


async def search_chain(query, override=None, max_results=10, category="all"):
    """run the provider chain, return (results, provider_used, last_error).

    provider_used is the one that actually answered (for the report stats);
    last_error is set when every provider in the chain came back empty/failed
    so the engine can tell the user *why* instead of a bare 'no results'.

    The value still unpacks exactly like the historical three-item tuple. Safe
    diagnostics are available as ``failure_type`` and ``attempted_sources``.
    """
    return SearchChainResult(await search_chain_report(query, override, max_results, category))


async def web_search(query, max_results=5, provider=None):
    """back-compat: just the results, no provider/error tuple."""
    results, _, _ = await search_chain(query, provider, max_results)
    return results
