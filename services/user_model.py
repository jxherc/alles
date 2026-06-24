"""1c - distill a living user model from behavior into the 'distilled' memory lane.

evidence = recent session topics + the 1a proactive outcomes (which card categories the user
acts on). a model turns that into a few short, sourced facts ("batches research before
deciding") stored as source='distilled' with a confidence that decays over time unless the
fact keeps being re-distilled. the user can veto a fact (hidden + never re-distilled).
"""

import json
import logging

from core.database import Memory
from core.database import Session as Sess

log = logging.getLogger("alles.user_model")


def _norm(t):
    return (t or "").strip().lower()


def gather_evidence(db, *, sessions=20):
    from services import proactive

    topics = [
        s.name
        # incognito = no trace: never let its name become distilled evidence (matches the
        # sidebar's incognito exclusion in routes/sessions.py)
        for s in db.query(Sess)
        .filter(Sess.incognito == False)  # noqa: E712
        .order_by(Sess.last_message_at.desc())
        .limit(sessions)
        .all()
        if s.name
    ]
    prefs = proactive.feedback_stats(db)  # reuse 1a: per-category act_rate
    return {
        "topics": topics,
        "category_prefs": {c: v.get("act_rate", 0.0) for c, v in prefs.items()},
    }


def apply_distilled(db, facts, provenance=""):
    """upsert distilled facts. dedupe by normalized text; never re-create a vetoed fact."""
    existing = {_norm(m.text) for m in db.query(Memory).all()}
    vetoed = {_norm(m.text) for m in db.query(Memory).filter(Memory.vetoed == True).all()}  # noqa: E712
    n = 0
    for f in facts or []:
        txt = (f.get("text") or "").strip()
        if not txt:
            continue
        key = _norm(txt)
        if key in vetoed or key in existing:
            continue
        existing.add(key)
        db.add(
            Memory(
                text=txt,
                category=f.get("category") or "general",
                source="distilled",
                confidence=float(f.get("confidence", 0.6)),
                provenance=provenance,
            )
        )
        n += 1
    db.commit()
    return n


def decay(db, *, factor=0.85, floor=0.25):
    """age distilled (non-pinned) facts' confidence; drop the faded ones. returns dropped count."""
    dropped = 0
    for m in db.query(Memory).filter(Memory.source == "distilled").all():
        if m.pinned:
            continue
        m.confidence = round((m.confidence if m.confidence is not None else 1.0) * factor, 4)
        if m.confidence < floor:
            db.delete(m)
            dropped += 1
    db.commit()
    return dropped


def veto(db, mid):
    m = db.get(Memory, mid)
    if not m:
        return False
    m.vetoed = True
    db.commit()
    return True


def inject_distilled(db, *, threshold=0.5, limit=8):
    """a short system-prompt block of what's been learned about the user, or '' if none.
    excludes vetoed + low-confidence facts; highest confidence first."""
    rows = (
        db.query(Memory)
        .filter(
            Memory.source == "distilled",
            Memory.vetoed == False,  # noqa: E712
            Memory.confidence >= threshold,
        )
        .order_by(Memory.confidence.desc(), Memory.timestamp.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""
    lines = [f"- {m.text}" for m in rows]
    return "what you've learned about the user from their behavior:\n" + "\n".join(lines)


def _parse_facts(raw):
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
        if isinstance(it, dict) and (it.get("text") or "").strip():
            try:
                conf = max(0.0, min(1.0, float(it.get("confidence", 0.6))))
            except (TypeError, ValueError):
                conf = 0.6
            out.append(
                {
                    "text": str(it["text"]).strip()[:300].replace("—", "-").replace("–", "-"),
                    "category": str(it.get("category") or "general"),
                    "confidence": conf,
                }
            )
    return out


def _build_messages(evidence):
    topics = ", ".join(evidence.get("topics", [])[:15]) or "(none)"
    prefs = evidence.get("category_prefs", {})
    pref_line = (
        ", ".join(f"{c}:{r:.0%} acted" for c, r in prefs.items()) or "(no proactive history)"
    )
    sys = (
        "you build a concise model of your user from their behavior. given recent conversation "
        "topics and how they engage with proactive suggestions, write 3-6 SHORT durable facts "
        "about their work-style, preferences, and interests - only well-supported ones, lowercase, "
        "no fluff, no em-dashes. return ONLY a json array of "
        '{"text": the fact, "category": identity|preference|fact, "confidence": 0..1}. [] if unsure.'
    )
    user = f"recent topics: {topics}\nproactive engagement by category: {pref_line}"
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


async def _run_default(db, evidence):
    from core.settings import load_settings
    from services.proactive import _resolve_endpoint_model, _run_model

    s = load_settings()
    ep, model = _resolve_endpoint_model(db, s)
    if not ep:
        return "[]"
    try:
        return await _run_model(_build_messages(evidence), ep, model, s)
    except Exception as e:
        log.warning(f"user-model distill call failed: {e}")
        return "[]"


async def distill_async(db, model_fn=None):
    """gather evidence -> model -> parse -> apply + decay. model_fn is the test seam (an async
    callable returning the raw model output); default uses the configured model."""
    ev = gather_evidence(db)
    raw = await (model_fn(ev) if model_fn else _run_default(db, ev))
    n = apply_distilled(db, _parse_facts(raw), provenance=f"sessions:{len(ev['topics'])}")
    decay(db)
    return n
