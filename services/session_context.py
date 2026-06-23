"""1d - a compact, per-session context the model sees each turn, so aide stays coherent across
turns (knows the mode + topic + active project) without re-deriving intent from raw history.

deterministic heuristics - no extra model call.
"""

_MODE_KEYWORDS = {
    "debugging": [
        "error",
        "bug",
        "traceback",
        "failing",
        "fails",
        "broken",
        "crash",
        "exception",
        "stack",
        "not working",
        "stacktrace",
        "fix this",
    ],
    "planning": [
        "plan",
        "approach",
        "should i",
        "options",
        "option a",
        "option b",
        "decide",
        "strategy",
        "roadmap",
        "trade-off",
        "tradeoff",
        "which way",
    ],
    "writing": [
        "write",
        "draft",
        "rewrite",
        "essay",
        "poem",
        "rfc",
        "blog",
        "post",
        "paragraph",
        "proofread",
        "reword",
    ],
    "research": [
        "explain",
        "what is",
        "what's a",
        "how does",
        "research",
        "compare",
        "find out",
        "look up",
        "tell me about",
        "why does",
    ],
}


def infer_mode(texts) -> str:
    blob = " ".join((t or "").lower() for t in (texts or []))
    if not blob.strip():
        return "chat"
    scores = {m: sum(blob.count(k) for k in kws) for m, kws in _MODE_KEYWORDS.items()}
    best = max(scores, key=lambda m: scores[m])
    return best if scores[best] > 0 else "chat"


def _topic(text) -> str:
    return " ".join((text or "").split())[:80]


def summarize(db, session, *, recent=12) -> str:
    """a compact 'current session' block, or '' when there's nothing to say."""
    msgs = list(session.messages)[-recent:]
    user_texts = [m.content for m in msgs if m.role == "user" and (m.content or "").strip()]
    if not user_texts:
        return ""
    parts = [f"mode: {infer_mode(user_texts)}"]
    topic = _topic(user_texts[-1])
    if topic:
        parts.append(f"topic: {topic}")
    if session.project_id:
        from core.database import Project

        p = db.get(Project, session.project_id)
        if p and p.name:
            parts.append(f"project: {p.name}")
    return "### Current session\n" + "; ".join(parts)
