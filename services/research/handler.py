"""
task registry + SSE bridge for the research engine.

DeepResearcher emits progress via a *sync* callback; routes want an *async*
generator of SSE events. we bridge with an asyncio.Queue: the callback drops
events on the queue, we run research() as a task and drain the queue, then yield
a final done event. keeps run_research's old signature so routes stay drop-in.
"""

import asyncio, json, time, logging
from pathlib import Path
from typing import AsyncGenerator

from .deep_research import DeepResearcher

log = logging.getLogger("aide.research")

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "research"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_tasks: dict[str, dict] = {}  # session_id → task state (live, in-memory)


def _save_task(session_id: str, state: dict):
    dump = {k: v for k, v in state.items() if not k.startswith("_")}
    (DATA_DIR / f"{session_id}.json").write_text(json.dumps(dump, indent=2), "utf-8")


def _load_task(session_id: str) -> dict | None:
    p = DATA_DIR / f"{session_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return None


def get_task(session_id: str) -> dict | None:
    t = _tasks.get(session_id)
    if t:
        return {k: v for k, v in t.items() if not k.startswith("_")}
    return _load_task(session_id)


def cancel_task(session_id: str):
    t = _tasks.get(session_id)
    if t:
        t["status"] = "cancelled"
        t["cancel"] = True
        r = t.get("_researcher")
        if r:
            r.cancel()


# phase → human step line for the existing research.js UI
def _map_event(ev: dict) -> dict | None:
    phase = ev.get("phase")
    if phase == "planning":
        return {"type": "step", "text": "planning the research…"}
    if phase == "searching":
        q = ev.get("query_preview")
        if q:
            return {"type": "step", "text": f"searching: {q}"}
        rn = ev.get("round")
        return {"type": "step", "text": f"round {rn}: searching…" if rn else "searching…"}
    if phase == "reading":
        url = ev.get("url")
        if url:
            return {"type": "source", "url": url, "title": ev.get("title") or url}
        return {"type": "step", "text": f"read {ev.get('new_sources', 0)} source(s)"}
    if phase == "analyzing":
        return {"type": "step", "text": f"synthesizing ({ev.get('total_findings', 0)} findings)…"}
    if phase == "writing":
        return {"type": "step", "text": ev.get("message") or "writing report…"}
    if phase == "warning":
        return {"type": "step", "text": "⚠ " + (ev.get("message") or "warning")}
    if phase == "error":
        return {"type": "error", "text": ev.get("message") or "research error"}
    return None


def _sources_from(researcher: DeepResearcher) -> list[dict]:
    """dedup findings into a sources list for the report footer."""
    seen, out = set(), []
    for f in researcher.findings:
        url = f.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append(
                {"url": url, "title": f.get("title") or url, "og_image": f.get("og_image", "")}
            )
    return out


async def run_research(
    session_id: str,
    query: str,
    base_url: str,
    api_key: str,
    model: str,
    max_rounds: int = 8,
) -> AsyncGenerator[dict, None]:
    """async generator of progress events. yields the alles SSE shapes:
    {step|source|error}, then a final {done, report, sources, stats}."""
    state = {
        "session_id": session_id,
        "query": query,
        "status": "running",
        "cancel": False,
        "findings": [],
        "sources": [],
        "report": "",
        "started_at": time.time(),
        "stats": {},
    }
    _tasks[session_id] = state

    q: asyncio.Queue = asyncio.Queue()

    def cb(ev):
        try:
            q.put_nowait(ev)
        except Exception:
            pass

    researcher = DeepResearcher(
        base_url, api_key, model, max_rounds=max_rounds, progress_callback=cb
    )
    state["_researcher"] = researcher

    yield {"type": "step", "text": f"researching: {query}"}

    task = asyncio.create_task(researcher.research(query))
    try:
        # drain progress events until research() finishes
        while True:
            getter = asyncio.ensure_future(q.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                mapped = _map_event(getter.result())
                if mapped:
                    yield mapped
            else:
                getter.cancel()
            if task.done():
                # flush anything still queued
                while not q.empty():
                    mapped = _map_event(q.get_nowait())
                    if mapped:
                        yield mapped
                break

        report = task.result()
        sources = _sources_from(researcher)
        stats = researcher.get_stats()
        state.update(
            status="cancelled" if state.get("cancel") else "done",
            report=report,
            sources=sources,
            findings=researcher.findings,
            stats=stats,
        )
        _save_task(session_id, state)
        yield {"type": "done", "report": report, "sources": sources[:15], "stats": stats}

        try:
            from routes.webhooks import fire

            await asyncio.wait_for(
                fire(
                    "research_done",
                    {"session_id": session_id, "query": query, "sources": len(sources)},
                ),
                timeout=10,
            )
        except Exception:
            pass  # a dead webhook must not hang/orphan the research task

    except Exception as e:
        log.exception("research error: %s", e)
        state["status"] = "error"
        _save_task(session_id, state)
        yield {"type": "error", "text": str(e)}
    finally:
        if not task.done():
            researcher.cancel()
            task.cancel()
