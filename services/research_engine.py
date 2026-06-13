"""
deep research engine.
web search + LLM reasoning loop → markdown report.
"""
import os, json, asyncio, time, logging, re
import html as _htmlmod
import urllib.parse
from pathlib import Path
from typing import AsyncGenerator
import httpx

log = logging.getLogger("aide.research")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def _strip_tags(s: str) -> str:
    return _htmlmod.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _html_to_text(html: str) -> str:
    """crude but dependency-free html → readable text, for feeding pages to the LLM."""
    html = re.sub(r"(?is)<(script|style|noscript|head|nav|footer|header|aside|form|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section|article)>", "\n", html)
    text = _htmlmod.unescape(re.sub(r"(?is)<[^>]+>", " ", html))
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


async def _fetch_page(url: str, max_chars: int = 4000) -> str:
    """grab a page and reduce it to text. returns '' on any failure (timeouts,
    non-html, blocks) — research must never hang on one bad link."""
    if not url or not url.startswith("http"):
        return ""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                     headers={"user-agent": _UA}) as c:
            r = await c.get(url)
            ct = r.headers.get("content-type", "")
            if ct and "html" not in ct and "text" not in ct:
                return ""
            return _html_to_text(r.text)[:max_chars]
    except Exception:
        return ""

DATA_DIR = Path(__file__).parent.parent / "data" / "research"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# in-memory task registry
_tasks: dict[str, dict] = {}   # session_id → task state


# ── web search ────────────────────────────────────────────────────────────────

async def _search_tavily(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.tavily.com/search", json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_raw_content": False,
        })
        r.raise_for_status()
        data = r.json()
    return [{"url": x["url"], "title": x.get("title",""), "snippet": x.get("content","")} for x in data.get("results", [])]


async def _search_brave(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": api_key, "user-agent": "aide-research/1.0"},
        )
        r.raise_for_status()
        data = r.json()
    return [{
        "url": x.get("url", ""),
        "title": x.get("title", ""),
        "snippet": x.get("description", ""),
    } for x in data.get("web", {}).get("results", []) if x.get("url")]


async def _search_searxng(query: str, base_url: str, max_results: int = 5) -> list[dict]:
    url = base_url.rstrip("/") + "/search"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(url, params={"q": query, "format": "json"})
        r.raise_for_status()
        data = r.json()
    return [{
        "url": x.get("url", ""),
        "title": x.get("title", ""),
        "snippet": x.get("content", ""),
    } for x in data.get("results", [])[:max_results] if x.get("url")]


async def _search_google_pse(query: str, api_key: str, cx: str, max_results: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://www.googleapis.com/customsearch/v1", params={
            "key": api_key,
            "cx": cx,
            "q": query,
            "num": min(max_results, 10),
        })
        r.raise_for_status()
        data = r.json()
    return [{
        "url": x.get("link", ""),
        "title": x.get("title", ""),
        "snippet": x.get("snippet", ""),
    } for x in data.get("items", []) if x.get("link")]


async def _search_serper(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": max_results},
            headers={"X-API-KEY": api_key, "user-agent": "aide-research/1.0"},
        )
        r.raise_for_status()
        data = r.json()
    return [{
        "url": x.get("link", ""),
        "title": x.get("title", ""),
        "snippet": x.get("snippet", ""),
    } for x in data.get("organic", []) if x.get("link")]


def _ddg_unwrap(href: str) -> str:
    # DDG wraps result links as //duckduckgo.com/l/?uddg=<urlencoded target>
    if "uddg=" in href:
        q = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href).query
        v = urllib.parse.parse_qs(q).get("uddg")
        if v:
            return v[0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _parse_ddg_html(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url = _ddg_unwrap(m.group(1))
        title = _strip_tags(m.group(2))
        if url.startswith("http") and title:
            out.append({"url": url, "title": title, "snippet": ""})
    snips = [_strip_tags(s) for s in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)]
    for i, s in enumerate(snips):
        if i < len(out):
            out[i]["snippet"] = s
    if not out:   # lite.duckduckgo.com layout
        for m in re.finditer(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            url = _ddg_unwrap(m.group(1))
            title = _strip_tags(m.group(2))
            if url.startswith("http") and title:
                out.append({"url": url, "title": title, "snippet": ""})
    return out


async def _search_duckduckgo(query: str, max_results: int = 6) -> list[dict]:
    # the instant-answer API returns almost nothing; scrape the HTML endpoints
    # instead — real web results, still no key required. DDG sometimes serves an
    # empty/anomaly page, so try the html endpoint then the lite one.
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


async def _search_wikipedia(query: str, max_results: int = 6) -> list[dict]:
    # reliable keyless fallback for factual queries — DDG scraping gets blocked a
    # lot; the Wikipedia API never does. covers far less of the web, but it always
    # returns real sources to ground the report.
    async with httpx.AsyncClient(timeout=12, follow_redirects=True,
                                 headers={"user-agent": _UA}) as c:
        r = await c.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "format": "json", "list": "search",
            "srsearch": query, "srlimit": max_results, "srprop": "snippet",
        })
        r.raise_for_status()
        data = r.json()
    out = []
    for x in data.get("query", {}).get("search", []):
        title = x.get("title", "")
        if not title:
            continue
        out.append({
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "title": title,
            "snippet": _strip_tags(x.get("snippet", "")),
        })
    return out


async def web_search(query: str, max_results: int = 5, provider: str | None = None) -> list[dict]:
    from core.settings import load_settings

    settings = load_settings()
    primary = provider or settings.get("search_provider") or "duckduckgo"
    chain = _provider_chain(primary, settings.get("search_fallback_chain"))
    if not chain:
        return []

    for name in chain:
        try:
            results = await _search_provider(name, query, settings, max_results)
            if results:
                if name != primary:
                    log.info("search fallback used: %s", name)
                return results
            log.warning("%s returned no results", name)
        except Exception as e:
            log.warning("%s search failed: %s", name, e)
    return []


def _provider_chain(primary: str, fallbacks) -> list[str]:
    if primary == "disabled":
        return []
    if isinstance(fallbacks, str):
        fallbacks = [p.strip() for p in fallbacks.split(",") if p.strip()]
    if not isinstance(fallbacks, list):
        fallbacks = []
    # always keep the keyless engines as last-resort fallbacks so research still
    # works with no API keys at all
    chain = [primary, *fallbacks, "duckduckgo", "wikipedia"]
    out = []
    for p in chain:
        p = str(p or "").strip()
        if p and p != "disabled" and p not in out:
            out.append(p)
    return out


async def _search_provider(name: str, query: str, settings: dict, max_results: int) -> list[dict]:
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


# ── task persistence ──────────────────────────────────────────────────────────

def _save_task(session_id: str, state: dict):
    (DATA_DIR / f"{session_id}.json").write_text(json.dumps(state, indent=2), "utf-8")

def _load_task(session_id: str) -> dict | None:
    p = DATA_DIR / f"{session_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return None

def get_task(session_id: str) -> dict | None:
    return _tasks.get(session_id) or _load_task(session_id)

def cancel_task(session_id: str):
    t = _tasks.get(session_id)
    if t:
        t["status"] = "cancelled"
        t["cancel"] = True


# ── research loop ─────────────────────────────────────────────────────────────

async def run_research(
    session_id: str,
    query: str,
    base_url: str,
    api_key: str,
    model: str,
    max_rounds: int = 6,
) -> AsyncGenerator[dict, None]:
    """
    async generator — yields progress events:
      {"type": "step",    "text": str}
      {"type": "search",  "query": str, "results": [...]}
      {"type": "finding", "text": str}
      {"type": "done",    "report": str, "sources": [...]}
      {"type": "error",   "text": str}
    """
    from services.llm import simple_complete, stream_chat

    state = {
        "session_id": session_id,
        "query": query,
        "status": "running",
        "cancel": False,
        "findings": [],
        "sources": [],
        "started_at": time.time(),
        "report": "",
    }
    _tasks[session_id] = state

    try:
        yield {"type": "step", "text": f"researching: {query}"}

        all_findings = []
        all_sources = []
        seen_urls = set()

        for round_num in range(max_rounds):
            if state.get("cancel"):
                yield {"type": "step", "text": "cancelled."}
                state["status"] = "cancelled"
                return

            # generate search query for this round
            if round_num == 0:
                search_q = query
            else:
                # ask LLM what to search next
                context = "\n".join(f"- {f}" for f in all_findings[-6:])
                sq_prompt = [
                    {"role": "system", "content": "You generate focused web search queries. Respond with ONLY the search query, nothing else."},
                    {"role": "user", "content": (
                        f"Original question: {query}\n\n"
                        f"What we've found so far:\n{context}\n\n"
                        f"Generate a new search query to find missing information. One query only."
                    )},
                ]
                search_q = await simple_complete(sq_prompt, base_url, api_key, model, max_tokens=40)
                search_q = search_q.strip().strip('"\'')
                if not search_q:
                    break

            yield {"type": "step", "text": f"searching: {search_q}"}

            results = await web_search(search_q, max_results=6)
            new_results = [r for r in results if r["url"] not in seen_urls]
            for r in new_results:
                seen_urls.add(r["url"])
            all_sources.extend(new_results)

            yield {"type": "search", "query": search_q, "results": new_results}

            if not new_results:
                yield {"type": "step", "text": "no new results, wrapping up..."}
                break

            # read the actual pages for the top hits — snippets alone are too thin
            # for real findings. fetched concurrently; failures fall back to snippet.
            top = new_results[:3]
            yield {"type": "step", "text": f"reading {len(top)} source" + ("s" if len(top) != 1 else "") + "…"}
            pages = await asyncio.gather(*[_fetch_page(r["url"]) for r in top])
            blocks = []
            for r, body in zip(top, pages):
                content = body or r.get("snippet", "")
                if content:
                    blocks.append(f"[{r['title']}] ({r['url']})\n{content[:3500]}")
            for r in new_results[3:6]:   # the rest as snippet-only context
                if r.get("snippet"):
                    blocks.append(f"[{r['title']}] ({r['url']})\n{r['snippet']}")
            snippets = "\n\n".join(blocks) or "(no readable content)"

            extract_prompt = [
                {"role": "system", "content": (
                    "Extract key factual findings relevant to the research question from the "
                    "page content below. Prefer specifics — numbers, names, dates, direct claims. "
                    "Be concise. Return bullet points only, no intro text."
                )},
                {"role": "user", "content": f"Question: {query}\n\nSources:\n{snippets}"},
            ]
            findings_raw = await simple_complete(extract_prompt, base_url, api_key, model, max_tokens=500)
            new_findings = [
                re.sub(r'^[-*\d.]+\s*', '', l).strip()
                for l in findings_raw.splitlines()
                if len(l.strip()) > 10
            ]
            all_findings.extend(new_findings)
            state["findings"] = all_findings
            state["sources"] = all_sources

            for f in new_findings:
                yield {"type": "finding", "text": f}

            # check if we have enough
            if len(all_findings) >= 12:
                yield {"type": "step", "text": "enough findings, writing report..."}
                break

        if state.get("cancel"):
            return

        # write final report
        yield {"type": "step", "text": "writing report..."}

        findings_block = "\n".join(f"- {f}" for f in all_findings)
        sources_block = "\n".join(f"- [{r['title']}]({r['url']})" for r in all_sources[:15])

        report_prompt = [
            {"role": "system", "content": (
                "You write clear, well-structured research reports in markdown. "
                "Use headings, bullet points. Cite sources inline as [title](url). "
                "Be comprehensive but concise."
            )},
            {"role": "user", "content": (
                f"Write a research report answering: {query}\n\n"
                f"Findings:\n{findings_block}\n\n"
                f"Sources:\n{sources_block}"
            )},
        ]

        report_parts = []
        async for chunk in stream_chat(report_prompt, base_url, api_key, model, max_tokens=2048):
            if chunk.get("delta"):
                report_parts.append(chunk["delta"])
                yield {"type": "report_delta", "text": chunk["delta"]}
            elif chunk.get("done"):
                break

        report = "".join(report_parts)
        state["report"] = report
        state["status"] = "done"
        _save_task(session_id, state)

        # dedup sources
        seen = set()
        unique_sources = []
        for s in all_sources:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique_sources.append(s)

        yield {"type": "done", "report": report, "sources": unique_sources[:15]}

        # fire webhook
        try:
            from routes.webhooks import fire
            await fire("research_done", {"session_id": session_id, "query": query, "sources": len(unique_sources)})
        except Exception:
            pass

    except Exception as e:
        log.exception(f"research error: {e}")
        state["status"] = "error"
        yield {"type": "error", "text": str(e)}
