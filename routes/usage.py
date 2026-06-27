"""
token usage + cost dashboard. aggregates what's already saved on each assistant
message (meta.usage from the model's stream) into per-month and per-model totals.
no new tracking — it reads the meta that chat.py has been writing all along.
"""

import json
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Message

router = APIRouter(prefix="/api")


def _toks(u: dict) -> tuple[int, int]:
    if not isinstance(u, dict):
        return 0, 0
    p = u.get("prompt_tokens") or u.get("input_tokens") or 0
    c = u.get("completion_tokens") or u.get("output_tokens") or 0
    try:
        return int(p), int(c)
    except (TypeError, ValueError):
        return 0, 0


@router.get("/usage/summary")
def usage_summary(db: DbSession = Depends(get_db)):
    by_month: dict[str, list] = defaultdict(lambda: [0, 0, 0])  # [prompt, completion, msgs]
    by_model: dict[str, list] = defaultdict(lambda: [0, 0, 0])
    total_p = total_c = total_msgs = 0

    for m in db.query(Message).filter(Message.role == "assistant").all():
        try:
            meta = json.loads(m.meta or "{}")
        except Exception:
            continue
        p, c = _toks(meta.get("usage"))
        if p == 0 and c == 0:
            continue
        model = meta.get("model") or "unknown"
        month = m.timestamp.isoformat()[:7] if m.timestamp else "?"
        for bucket, key in ((by_month, month), (by_model, model)):
            bucket[key][0] += p
            bucket[key][1] += c
            bucket[key][2] += 1
        total_p += p
        total_c += c
        total_msgs += 1

    def _rows(d):
        return [
            {"name": k, "prompt": v[0], "completion": v[1], "total": v[0] + v[1], "messages": v[2]}
            for k, v in d.items()
        ]

    months = sorted(_rows(by_month), key=lambda r: r["name"])
    models = sorted(_rows(by_model), key=lambda r: -r["total"])
    return {
        "total_prompt": total_p,
        "total_completion": total_c,
        "total_tokens": total_p + total_c,
        "total_messages": total_msgs,
        "by_month": months,
        "by_model": models,
    }


@router.get("/usage/by-session")
def usage_by_session(limit: int = 30, db: DbSession = Depends(get_db)):
    """token totals per chat — see which conversations are actually costing you."""
    from core.database import Session as Sess

    by_sess: dict[str, list] = defaultdict(lambda: [0, 0, 0])  # prompt, completion, msgs
    for m in db.query(Message).filter(Message.role == "assistant").all():
        try:
            meta = json.loads(m.meta or "{}")
        except Exception:
            continue
        p, c = _toks(meta.get("usage"))
        if p == 0 and c == 0:
            continue
        b = by_sess[m.session_id]
        b[0] += p
        b[1] += c
        b[2] += 1
    rows = []
    for sid, v in by_sess.items():
        s = db.get(Sess, sid)
        rows.append(
            {
                "session_id": sid,
                "name": (s.name if s else "(deleted)"),
                "prompt": v[0],
                "completion": v[1],
                "total": v[0] + v[1],
                "messages": v[2],
            }
        )
    rows.sort(key=lambda r: -r["total"])
    return {"sessions": rows[: max(0, limit)]}  # negative limit would slice off the top sessions
