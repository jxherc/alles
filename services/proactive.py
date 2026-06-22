"""the proactive agent - a scheduled pass that reads the user's current signals
(services.signals) and, only when something's worth saying, asks aide to write a
few short advisory suggestion cards. advisory only: cards never mutate anything,
the user clicks through. default OFF (it spends tokens); a manual 'run now'
bypasses the toggle/interval so it can be tested before being switched on."""

import hashlib
import json
import logging
from datetime import datetime

from core.database import ModelEndpoint, ProactiveItem, SessionLocal
from core.settings import load_settings
from services import signals

log = logging.getLogger(__name__)

# views a card may deep-link to; anything else gets blanked
ALLOWED_LINKS = {
    "tasks", "calendar", "reminders", "subscriptions", "days",
    "habits", "books", "health", "money", "mail", "notes", "home",
}

# signal category -> the settings switch that gates it
_CAT_SETTING = {
    "task": "pidx_proactive_cat_task",
    "reminder": "pidx_proactive_cat_task",      # reminders ride the task toggle
    "sub": "pidx_proactive_cat_sub",
    "event": "pidx_proactive_cat_event",
    "day_event": "pidx_proactive_cat_event",    # day-events ride the event toggle
    "habit": "pidx_proactive_cat_habit",
    "book": "pidx_proactive_cat_read",
    "health": "pidx_proactive_cat_health",
}


def _enabled_categories(s):
    return {cat for cat, key in _CAT_SETTING.items() if s.get(key, True)}


def _in_quiet_hours(s, now=None):
    now = now or datetime.now()
    start = int(s.get("pidx_proactive_quiet_start", 22))
    end = int(s.get("pidx_proactive_quiet_end", 7))
    if start == end:
        return False
    h = now.hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # window wraps past midnight


def _dedupe_key(source_keys):
    return hashlib.sha1("|".join(sorted(source_keys)).encode()).hexdigest()[:16]


def _interval_seconds():
    try:
        return max(1, int(load_settings().get("pidx_proactive_every_hours", 6))) * 3600
    except Exception:
        return 6 * 3600


# -- model plumbing (isolated so the gates/dedup are testable without an LLM) --

def _resolve_endpoint_model(db, s):
    from services.routing import pick_endpoint

    eps = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()  # noqa: E712
    ep = pick_endpoint(eps)
    if not ep:
        return None, None
    model = (s.get("proactive_model") or "").strip()
    if not model:
        ml = ep.models_list()
        model = ml[0] if ml else ""
    return (ep, model) if model else (None, None)


async def _run_model(messages, ep, model, s):
    from services.llm import stream_chat

    acc = []
    max_tokens = int(s.get("pidx_proactive_max_tokens", 800))
    async for chunk in stream_chat(messages, ep.base_url, ep.api_key, model, max_tokens=max_tokens):
        if "delta" in chunk:
            acc.append(chunk["delta"])
    return "".join(acc)


def _recall_context(db, sigs, s):
    if not s.get("pidx_enabled", True):
        return ""
    try:
        from services import personal_index

        q = " ".join(x["title"] for x in sigs[:5])
        hits = personal_index.search(db, q, k=4)
        if not hits:
            return ""
        return "\n".join(f"- {h.get('label', '')}: {(h.get('chunk', '') or '')[:160]}" for h in hits)
    except Exception:
        return ""


def _build_messages(sigs, recall_ctx):
    lines = [
        f"[{x['urgency']}] {x['category']} - {x['title']} - {x['detail']} "
        f"(link:{x['link']}) <key:{x['key']}>"
        for x in sigs[:40]
    ]
    sys = (
        "you are aide, the user's assistant, running quietly in the background. you get a "
        "list of the user's current signals (what's going on right now). write a SHORT ranked "
        "set of advisory suggestion cards - only for things genuinely worth surfacing. each "
        "card is advisory: the user clicks through, you never take actions yourself. merge "
        "related signals into one card when sensible. be concise, specific, lowercase, no fluff. "
        "return ONLY a json array (no prose) of objects: "
        '{"title": short headline, "body": one or two sentences, "link": one of the signal '
        'links or "", "score": 0-100 importance, "source_keys": [the key values this card is '
        "based on]}. return [] if nothing is worth surfacing."
    )
    user = "current signals:\n" + "\n".join(lines)
    if recall_ctx:
        user += "\n\nrelevant context from the user's own data:\n" + recall_ctx
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def _parse_suggestions(raw, sigs):
    valid = {x["key"] for x in sigs}
    text = (raw or "").strip()
    if "```" in text:  # tolerate a fenced block
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b == -1 or b < a:
        return []
    try:
        arr = json.loads(text[a:b + 1])
    except Exception:
        return []
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title", "")).strip()
        if not title:
            continue
        sk = [k for k in (it.get("source_keys") or []) if k in valid]
        if not sk:  # a card must cite at least one real signal
            continue
        link = str(it.get("link", "") or "")
        if link not in ALLOWED_LINKS:
            link = ""
        try:
            score = max(0, min(100, int(it.get("score", 50))))
        except (TypeError, ValueError):
            score = 50
        out.append({"title": title[:120], "body": str(it.get("body", "")).strip()[:400],
                    "link": link, "score": score, "source_keys": sk})
    return out


async def _reason(db, sigs, s):
    """run aide over the signals -> list of suggestion dicts. [] on any failure."""
    ep, model = _resolve_endpoint_model(db, s)
    if not ep:
        return []
    messages = _build_messages(sigs, _recall_context(db, sigs, s))
    try:
        raw = await _run_model(messages, ep, model, s)
    except Exception as e:
        log.warning(f"proactive model call failed: {e}")
        return []
    return _parse_suggestions(raw, sigs)


# -- card bookkeeping ----------------------------------------------------------

def _prune_resolved(db, sigs):
    """drop live cards whose underlying signals are all gone (situation resolved)."""
    live = {x["key"] for x in sigs}
    for item in db.query(ProactiveItem).filter(ProactiveItem.dismissed == False).all():  # noqa: E712
        try:
            sk = json.loads(item.source_keys or "[]")
        except Exception:
            sk = []
        if sk and not any(k in live for k in sk):
            db.delete(item)
    db.commit()


def _has_uncarded(db, sigs):
    """is there a signal not already covered by an existing card? dismissed cards
    suppress their signals too, so a dismissed situation won't re-trigger a run."""
    covered = set()
    for item in db.query(ProactiveItem).all():
        try:
            covered.update(json.loads(item.source_keys or "[]"))
        except Exception:
            pass
    return any(x["key"] not in covered for x in sigs)


def _upsert(db, cards, sigs):
    key_urgency = {x["key"]: x["urgency"] for x in sigs}
    key_cat = {x["key"]: x["category"] for x in sigs}
    written = 0
    for c in cards:
        dk = _dedupe_key(c["source_keys"])
        urg = max((key_urgency.get(k, 0) for k in c["source_keys"]), default=0)
        live = (
            db.query(ProactiveItem)
            .filter(ProactiveItem.dedupe_key == dk, ProactiveItem.dismissed == False)  # noqa: E712
            .first()
        )
        if live:
            live.score, live.urgency = c["score"], urg
            live.title, live.body, live.link = c["title"], c["body"], c["link"]
            live.updated_at = datetime.utcnow()
            continue
        # a dismissed card with this exact key stays suppressed
        if db.query(ProactiveItem).filter(ProactiveItem.dedupe_key == dk).first():
            continue
        cat = next((key_cat[k] for k in c["source_keys"] if k in key_cat), "")
        db.add(ProactiveItem(dedupe_key=dk, category=cat, title=c["title"], body=c["body"],
                             link=c["link"], score=c["score"], urgency=urg,
                             source_keys=json.dumps(c["source_keys"])))
        written += 1
    db.commit()
    return written


async def run(force=False):
    """one proactive pass. force=True (manual 'run now') bypasses the master
    toggle, the interval, and quiet hours so it can be tested before being turned
    on; the no-signal / already-carded gates always apply (no pointless spend)."""
    s = load_settings()
    if not force and not s.get("pidx_proactive_enabled", False):
        return {"ran": False, "reason": "disabled"}
    if not force and _in_quiet_hours(s):
        return {"ran": False, "reason": "quiet_hours"}
    db = SessionLocal()
    try:
        sigs = signals.gather(db, categories=_enabled_categories(s))
        min_u = int(s.get("pidx_proactive_min_urgency", 1))
        sigs = [x for x in sigs if x["urgency"] >= min_u]
        _prune_resolved(db, sigs)
        if not sigs:
            return {"ran": False, "reason": "no_signals"}
        if not _has_uncarded(db, sigs):
            return {"ran": False, "reason": "all_carded"}
        cards = await _reason(db, sigs, s)
        written = _upsert(db, cards, sigs)
        return {"ran": True, "signals": len(sigs), "cards": len(cards), "written": written}
    finally:
        db.close()
