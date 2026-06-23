"""the proactive agent - a scheduled pass that reads the user's current signals
(services.signals) and, only when something's worth saying, asks aide to write a
few short advisory suggestion cards. advisory only: cards never mutate anything,
the user clicks through. default OFF (it spends tokens); a manual 'run now'
bypasses the toggle/interval so it can be tested before being switched on."""

import hashlib
import json
import logging
from datetime import datetime

from core.database import (
    ModelEndpoint,
    ProactiveItem,
    ProactiveOutcome,
    ProactiveState,
    SessionLocal,
)
from core.settings import load_settings
from services import signals

log = logging.getLogger(__name__)

# views a card may deep-link to (must be real navigateTo names); else blanked
ALLOWED_LINKS = {
    "tasks",
    "calendar",
    "reminders",
    "subs",
    "days",
    "habits",
    "read",
    "books",
    "health",
    "money",
    "mail",
    "journal",
    "contacts",
    "home",
}

# signal category -> the settings switch that gates it
_CAT_SETTING = {
    "task": "pidx_proactive_cat_task",
    "reminder": "pidx_proactive_cat_task",  # reminders ride the task toggle
    "sub": "pidx_proactive_cat_sub",
    "event": "pidx_proactive_cat_event",
    "day_event": "pidx_proactive_cat_event",  # day-events ride the event toggle
    "habit": "pidx_proactive_cat_habit",
    "book": "pidx_proactive_cat_read",
    "health": "pidx_proactive_cat_health",
    "budget": "pidx_proactive_cat_money",
    "account": "pidx_proactive_cat_money",  # budget + low balance ride the money toggle
    "mail": "pidx_proactive_cat_mail",
    "journal": "pidx_proactive_cat_journal",
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
        return "\n".join(
            f"- {h.get('label', '')}: {(h.get('chunk', '') or '')[:160]}" for h in hits
        )
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
        arr = json.loads(text[a : b + 1])
    except Exception:
        return []

    def _dedash(t):  # the user hates em/en dashes; keep aide's cards clean
        return t.replace("—", "-").replace("–", "-").strip()

    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        title = _dedash(str(it.get("title", "")))
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
        out.append(
            {
                "title": title[:120],
                "body": _dedash(str(it.get("body", "")))[:400],
                "link": link,
                "score": score,
                "source_keys": sk,
            }
        )
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
            # shown but never acted/dismissed before the situation resolved -> ignored
            if item.status != "acted":
                record_outcome(db, item, "ignored")
            db.delete(item)
    db.commit()


def _load_seen(db):
    st = db.get(ProactiveState, "singleton")
    if not st:
        return set()
    try:
        return set(json.loads(st.seen_keys or "[]"))
    except Exception:
        return set()


def _save_seen(db, keys):
    st = db.get(ProactiveState, "singleton")
    blob = json.dumps(sorted(keys))
    if st:
        st.seen_keys = blob
        st.updated_at = datetime.utcnow()
    else:
        db.add(ProactiveState(id="singleton", seen_keys=blob))
    db.commit()


# ── feedback loop (1a) ────────────────────────────────────────────────────────────
def record_outcome(db, item, outcome):
    """log one card fate (acted|dismissed|ignored). latency = card age when it landed."""
    try:
        latency = (datetime.utcnow() - (item.created_at or datetime.utcnow())).total_seconds()
    except Exception:
        latency = 0.0
    db.add(
        ProactiveOutcome(
            item_id=item.id,
            dedupe_key=item.dedupe_key,
            category=item.category or "",
            outcome=outcome,
            latency_sec=max(0.0, latency),
        )
    )
    db.commit()


def _category_weight(db, cat):
    """learned per-category score multiplier, bounded [0.5, 1.5]. cold-start neutral (1.0);
    acts pull it up, dismisses down, ignores weakly down. +3 smoothing keeps a cold/quiet
    category near 1.0 so it still gets shown."""
    rows = db.query(ProactiveOutcome.outcome).filter(ProactiveOutcome.category == cat).all()
    acts = sum(1 for (o,) in rows if o == "acted")
    dis = sum(1 for (o,) in rows if o == "dismissed")
    ign = sum(1 for (o,) in rows if o == "ignored")
    total = acts + dis + ign
    if not total:
        return 1.0
    signal = acts - dis - 0.3 * ign
    w = 1.0 + 0.5 * signal / (total + 3)
    return max(0.5, min(1.5, w))


def feedback_stats(db):
    """per-category {acted, dismissed, ignored, act_rate, weight} for the stats surface."""
    out = {}
    for cat, o in db.query(ProactiveOutcome.category, ProactiveOutcome.outcome).all():
        c = out.setdefault(cat or "", {"acted": 0, "dismissed": 0, "ignored": 0})
        if o in c:
            c[o] += 1
    for cat, c in out.items():
        tot = c["acted"] + c["dismissed"] + c["ignored"]
        c["act_rate"] = round(c["acted"] / tot, 3) if tot else 0.0
        c["weight"] = round(_category_weight(db, cat), 3)
    return out


def _weighted(db, base, cat):
    return max(0, min(100, round(base * _category_weight(db, cat))))


def _upsert(db, cards, sigs):
    key_urgency = {x["key"]: x["urgency"] for x in sigs}
    key_cat = {x["key"]: x["category"] for x in sigs}
    written = 0
    for c in cards:
        dk = _dedupe_key(c["source_keys"])
        urg = max((key_urgency.get(k, 0) for k in c["source_keys"]), default=0)
        cat = next((key_cat[k] for k in c["source_keys"] if k in key_cat), "")
        score = _weighted(db, c["score"], cat)  # fold in the learned per-category weight
        live = (
            db.query(ProactiveItem)
            .filter(ProactiveItem.dedupe_key == dk, ProactiveItem.dismissed == False)  # noqa: E712
            .first()
        )
        if live:
            live.score, live.urgency = score, urg
            live.title, live.body, live.link = c["title"], c["body"], c["link"]
            live.updated_at = datetime.utcnow()
            continue
        # a dismissed card with this exact key stays suppressed
        if db.query(ProactiveItem).filter(ProactiveItem.dedupe_key == dk).first():
            continue
        db.add(
            ProactiveItem(
                dedupe_key=dk,
                category=cat,
                title=c["title"],
                body=c["body"],
                link=c["link"],
                score=score,
                urgency=urg,
                source_keys=json.dumps(c["source_keys"]),
            )
        )
        written += 1
    db.commit()
    return written


def _gather_with_synthesis(db, sigs, s, base=None):
    """1b: on the periodic path, snapshot the signals (base, or sigs) into history and append
    the derived trend/corr signals. derived signals bypass the category filter on purpose
    (their categories are 'trend'/'corr', not user-gated). off -> return sigs unchanged."""
    if not s.get("pidx_proactive_synthesis", True):
        return sigs
    signals.record_snapshot(db, base if base is not None else sigs)
    return sigs + signals.synthesize(db)


async def _maybe_push(db, s):
    """web-push the urgent new cards, if the user opted into the push channel. caps
    to the top 2 per run so a busy day doesn't spam the lock screen."""
    if s.get("pidx_proactive_channel", "inapp") != "push":
        return 0
    push_min = int(s.get("pidx_proactive_push_min", 70))
    rows = (
        db.query(ProactiveItem)
        .filter(
            ProactiveItem.dismissed == False,
            ProactiveItem.pushed == False,  # noqa: E712
            ProactiveItem.urgency >= push_min,
        )
        .order_by(ProactiveItem.urgency.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return 0
    from routes.push import broadcast

    sent = 0
    for r in rows:
        try:
            await broadcast(
                {"title": "aide", "body": r.title, "url": "/", "tag": f"proactive-{r.id}"}
            )
            r.pushed = True
            sent += 1
        except Exception as e:
            log.warning(f"proactive push failed: {e}")
    db.commit()
    return sent


async def run(force=False):
    """one proactive pass. force=True (manual 'run now') bypasses the master
    toggle, the interval, quiet hours, and the 'nothing new' gate so it can be
    tested on demand; the no-signal gate always applies (no pointless spend).

    a scheduled run only fires when a signal turns up that the agent hasn't been
    shown before - the model legitimately skips trivial signals, so gating on
    'every signal carded' would re-run forever. we gate on 'genuinely new' instead."""
    s = load_settings()
    if not force and not s.get("pidx_proactive_enabled", False):
        return {"ran": False, "reason": "disabled"}
    if not force and _in_quiet_hours(s):
        return {"ran": False, "reason": "quiet_hours"}
    db = SessionLocal()
    try:
        # prune against the FULL signal set - a card should only be dropped when its
        # situation actually resolved, not when the user toggled its category off
        full = signals.gather(db)
        _prune_resolved(db, full)
        cats = _enabled_categories(s)
        min_u = int(s.get("pidx_proactive_min_urgency", 1))
        sigs = [x for x in full if x["category"] in cats and x["urgency"] >= min_u]
        sigs = _gather_with_synthesis(db, sigs, s, base=full)  # 1b: history + derived signals
        if not sigs:
            return {"ran": False, "reason": "no_signals"}
        seen = _load_seen(db)
        if not force and all(x["key"] in seen for x in sigs):
            return {"ran": False, "reason": "nothing_new"}
        cards = await _reason(db, sigs, s)
        written = _upsert(db, cards, sigs)
        pushed = await _maybe_push(db, s)
        _save_seen(db, {x["key"] for x in sigs})
        return {
            "ran": True,
            "signals": len(sigs),
            "cards": len(cards),
            "written": written,
            "pushed": pushed,
        }
    finally:
        db.close()
