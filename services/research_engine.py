"""
deep research engine.
web search + LLM reasoning loop → markdown report.
"""
import os, json, asyncio, time, logging, re
from pathlib import Path
from typing import AsyncGenerator
import httpx

log = logging.getLogger("aide.research")

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


async def _search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    # DDG instant answer API — free, no key needed, limited
    params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get("https://api.duckduckgo.com/", params=params,
                        headers={"user-agent": "aide-research/1.0"})
        data = r.json()

    results = []
    # related topics as snippets
    for t in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(t, dict) and t.get("FirstURL"):
            results.append({
                "url": t["FirstURL"],
                "title": t.get("Text","")[:80],
                "snippet": t.get("Text","")[:300],
            })
    return results


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
    chain = [primary, *fallbacks, "duckduckgo"]
    out = []
    for p in chain:
        p = str(p or "").strip()
        if p and p != "disabled" and p not in out:
            out.append(p)
    return out


async def _search_provider(name: str, query: str, settings: dict, max_results: int) -> list[dict]:
    if name == "duckduckgo":
        return await _search_duckduckgo(query, max_results)
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

            results = await web_search(search_q, max_results=5)
            new_results = [r for r in results if r["url"] not in seen_urls]
            for r in new_results:
                seen_urls.add(r["url"])
            all_sources.extend(new_results)

            yield {"type": "search", "query": search_q, "results": new_results}

            if not new_results:
                yield {"type": "step", "text": "no new results, wrapping up..."}
                break

            # ask LLM to extract findings from search results
            snippets = "\n\n".join(
                f"[{r['title']}] ({r['url']})\n{r['snippet']}"
                for r in new_results[:5]
            )
            extract_prompt = [
                {"role": "system", "content": (
                    "Extract key factual findings relevant to the research question. "
                    "Be concise. Return bullet points only, no intro text."
                )},
                {"role": "user", "content": f"Question: {query}\n\nSearch results:\n{snippets}"},
            ]
            findings_raw = await simple_complete(extract_prompt, base_url, api_key, model, max_tokens=400)
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
