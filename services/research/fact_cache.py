"""3g - cross-session deep-research fact cache: persist findings keyed by URL, dedup, cache-first
lookup, and a heuristic contradiction flag (two same-topic findings of opposite polarity).
"""

import re

from core.database import ResearchFinding

_NEG = re.compile(
    r"\b(not|no|never|cannot|can't|isn't|aren't|doesn't|don't|won't|false|incorrect|fails?)\b", re.I
)
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "as",
    "at",
    "by",
    "from",
    "too",
    "also",
    "among",
    "into",
    "than",
    "then",
    "they",
    "their",
}


def _norm_url(u):
    u = (u or "").strip().lower()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"/+$", "", u)
    return u


def _tokens(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3 and w not in _STOP}


def dedupe(findings):
    """unique by normalized URL, first occurrence wins. findings without a url pass through."""
    seen, out = set(), []
    for f in findings or []:
        u = _norm_url(f.get("url", ""))
        if u:
            if u in seen:
                continue
            seen.add(u)
        out.append(f)
    return out


def store(db, findings, question=""):
    """insert findings whose url isn't already cached. returns the number newly stored."""
    have = {_norm_url(r.url) for r in db.query(ResearchFinding.url).all()}
    n = 0
    for f in dedupe(findings):
        u = _norm_url(f.get("url", ""))
        if not u or u in have:
            continue
        db.add(
            ResearchFinding(
                url=f.get("url", ""),
                question=question or "",
                title=f.get("title", "") or "",
                summary=f.get("summary", "") or "",
            )
        )
        have.add(u)
        n += 1
    if n:
        db.commit()
    return n


def cached(db, question, *, limit=20):
    """prior findings whose stored question overlaps `question` (the cache-first source)."""
    q = _tokens(question)
    if not q:
        return []
    scored = []
    for r in db.query(ResearchFinding).all():
        overlap = len(q & _tokens(r.question))
        if overlap:
            scored.append((overlap, r))
    scored.sort(key=lambda x: -x[0])
    return [
        {"url": r.url, "title": r.title, "summary": r.summary, "question": r.question}
        for _, r in scored[:limit]
    ]


def contradictions(findings):
    """pairs of findings that talk about the same thing (>=3 shared content tokens) but disagree in
    polarity (exactly one carries a negation). a heuristic flag, not a proof."""
    out = []
    items = list(findings or [])
    for i in range(len(items)):
        a = items[i].get("summary", "")
        ta = _tokens(a)
        na = bool(_NEG.search(a))
        for j in range(i + 1, len(items)):
            b = items[j].get("summary", "")
            shared = ta & _tokens(b)
            if len(shared) >= 3 and na != bool(_NEG.search(b)):
                out.append(
                    {
                        "a": items[i].get("url", ""),
                        "b": items[j].get("url", ""),
                        "shared": sorted(shared)[:5],
                    }
                )
    return out
