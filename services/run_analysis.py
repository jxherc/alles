"""3e - agent run analysis + replay. reads the run JSON logs (agent_state) and turns them into
summaries, intent clusters, few-shot precedents for the system prompt, and replay plans.

pure functions operate on run dicts; load_runs() pulls them off disk.
"""

import json
import re
from datetime import datetime


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _duration(run):
    try:
        a = datetime.fromisoformat(run.get("started_at", ""))
        b = datetime.fromisoformat(run.get("finished_at", "") or run.get("updated_at", ""))
        return round((b - a).total_seconds(), 1)
    except ValueError:
        return 0.0


def summarize(run):
    tools = _dedupe(s.get("name", "") for s in run.get("tool_steps", []) if s.get("name"))
    return {
        "id": run.get("id", ""),
        "intent": (run.get("intent") or "").strip(),
        "tools": tools,
        "status": run.get("status", ""),
        "turns": run.get("turn", 0),
        "duration_sec": _duration(run),
        "model": run.get("model", ""),
    }


def _intent_key(summary):
    intent = summary["intent"]
    if intent:
        return intent.lower().strip()
    return "tools:" + ",".join(summary["tools"])  # fallback signature when no intent recorded


def cluster_by_intent(runs):
    clusters = {}
    for r in runs:
        s = summarize(r)
        clusters.setdefault(_intent_key(s), []).append(s)
    return clusters


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s):
    return set(_WORD.findall((s or "").lower()))


def precedents(runs, query, k=3):
    """successful past runs whose intent overlaps the query, best first."""
    q = _tokens(query)
    scored = []
    for r in runs:
        s = summarize(r)
        if s["status"] != "done" or not s["intent"]:
            continue
        overlap = len(q & _tokens(s["intent"]))
        if overlap:
            scored.append((overlap, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:k]]


def precedents_text(runs, query, k=3):
    """a compact few-shot block for the system prompt: what worked for similar past requests."""
    ps = precedents(runs, query, k)
    if not ps:
        return ""
    lines = ["Similar past runs that succeeded (use as precedent, not gospel):"]
    for s in ps:
        tools = ", ".join(s["tools"]) or "(no tools)"
        lines.append(f'- "{s["intent"]}" -> {tools}')
    return "\n".join(lines)


def replay_plan(run, *, model=None, effort=None):
    """rebuild a past run's input to re-submit, optionally on a different model/effort."""
    return {
        "messages": [{"role": "user", "content": (run.get("intent") or "").strip()}],
        "model": model or run.get("model", ""),
        "effort": effort or run.get("effort", "medium"),
        "from_run": run.get("id", ""),
    }


def load_runs(limit=50):
    from services import agent_state

    runs = []
    try:
        files = sorted(
            agent_state.DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except Exception:
        return runs
    for p in files[:limit]:
        try:
            runs.append(json.loads(p.read_text("utf-8")))
        except Exception:
            continue
    return runs
