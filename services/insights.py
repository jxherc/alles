"""1e - cross-domain causal insights. see docs/evidence/1e-insights/findings.md.

a gated, low-frequency pass that summarizes the user's corpus (signal history + category prefs)
and asks the model for a few higher-level, evidence-cited insights. default OFF (spends tokens);
a run-now forces it. dedupe + dismissal are by the cited evidence set. model_fn is the test seam.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta

from core.database import Insight, SignalSnapshot

log = logging.getLogger("alles.insights")


def _dedupe_key(evidence):
    return hashlib.sha1("|".join(sorted(str(e) for e in evidence)).encode()).hexdigest()[:16]


def gather_corpus(db, *, days=30):
    from services import proactive

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(SignalSnapshot).filter(SignalSnapshot.ts >= cutoff).all()
    hist = {}
    for r in rows:
        hist[r.category] = hist.get(r.category, 0) + 1
    prefs = proactive.feedback_stats(db)
    return {
        "signal_history": hist,
        "category_prefs": {c: v.get("act_rate", 0.0) for c, v in prefs.items()},
    }


def apply_insights(db, items):
    """upsert insights, deduped by the evidence set; a dismissed insight stays suppressed."""
    existing = {i.dedupe_key for i in db.query(Insight).all()}  # includes dismissed
    n = 0
    for it in items or []:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        ev = [str(e) for e in (it.get("evidence") or [])]
        dk = _dedupe_key(ev)
        if dk in existing:
            continue
        existing.add(dk)
        db.add(
            Insight(
                title=title[:200],
                body=(it.get("body") or "")[:1000],
                kind=(it.get("kind") or ""),
                evidence=json.dumps(ev),
                dedupe_key=dk,
            )
        )
        n += 1
    db.commit()
    return n


def _parse(raw):
    text = (raw or "").strip()
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b == -1 or b < a:
        return []
    try:
        arr = json.loads(text[a : b + 1])
    except Exception:
        return []
    out = []
    for it in arr:
        if isinstance(it, dict) and (it.get("title") or "").strip():
            out.append(
                {
                    "title": str(it["title"]).strip().replace("—", "-").replace("–", "-"),
                    "body": str(it.get("body") or "").replace("—", "-").replace("–", "-"),
                    "kind": str(it.get("kind") or ""),
                    "evidence": [str(e) for e in (it.get("evidence") or [])],
                }
            )
    return out


def _build_messages(corpus):
    sys = (
        "you find cross-domain causal insights in the user's own data - higher-level patterns "
        "that span weeks (productivity vs events, spending vs subscriptions, mood vs deadlines). "
        "given a compact corpus summary, write 1-4 well-supported insights, lowercase, no fluff, "
        "no em-dashes, each CITING the evidence it rests on. return ONLY a json array of "
        '{"title": short, "body": one or two sentences, "kind": a category, "evidence": [refs]}. '
        "[] if none."
    )
    user = "corpus summary:\n" + json.dumps(corpus, indent=1)
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


async def _run_default(db, corpus):
    from core.settings import load_settings
    from services.proactive import _resolve_endpoint_model, _run_model

    s = load_settings()
    ep, model = _resolve_endpoint_model(db, s)
    if not ep:
        return "[]"
    try:
        return await _run_model(_build_messages(corpus), ep, model, s)
    except Exception as e:
        log.warning(f"insights model call failed: {e}")
        return "[]"


async def generate_async(db, model_fn=None, force=False):
    """gather corpus -> model -> parse -> apply. gated by insights_enabled unless force."""
    from core.settings import load_settings

    if not force and not load_settings().get("insights_enabled", False):
        return {"ran": False, "reason": "disabled", "count": 0}
    corpus = gather_corpus(db)
    raw = await (model_fn(corpus) if model_fn else _run_default(db, corpus))
    n = apply_insights(db, _parse(raw))
    return {"ran": True, "count": n}
