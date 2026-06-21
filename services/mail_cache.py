"""
persistent header cache for the inbox. the live IMAP fetch warms it; reads come
back instantly from sqlite (and survive a slow/dead network or a restart). local
search runs over the cache so it's instant and works offline.
"""

from datetime import datetime, timezone

from core.database import CachedMessage


def _to_msg(r: CachedMessage) -> dict:
    return {
        "uid": r.uid,
        "from": r.sender,
        "subject": r.subject,
        "date": r.date,
        "date_ts": r.date_ts,
        "seen": r.seen,
        "flagged": bool(r.flagged),
        "list_unsubscribe": r.list_unsubscribe or "",
        "muted": bool(r.muted),
        "snoozed_until": r.snoozed_until or "",
        "labels": [x for x in (r.labels or "").split(",") if x],
        "account_id": r.account_id,
        "cached": True,
    }


def _norm_labels(labels):
    """list or csv → lowercased, trimmed, de-duped csv."""
    if isinstance(labels, str):
        labels = labels.split(",")
    seen, out = set(), []
    for x in labels or []:
        x = str(x).strip().lower()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return ",".join(out)


def set_labels(db, account_id, folder, uid, labels):
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .update({"labels": _norm_labels(labels)})
    )
    db.commit()
    return n


def add_label(db, account_id, folder, uid, label):
    row = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .first()
    )
    if not row:
        return 0
    row.labels = _norm_labels((row.labels or "") + "," + str(label))
    db.commit()
    return 1


def by_label(db, account_id, label, limit=200):
    lab = str(label).strip().lower()
    rows = (
        _visible(db.query(CachedMessage).filter_by(account_id=account_id))
        .filter(CachedMessage.labels.like(f"%{lab}%"))
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows if lab in [x for x in (r.labels or "").split(",")]]


def by_category(db, account_id, cat, limit=200):
    from services.mail import categorize

    rows = (
        _visible(db.query(CachedMessage).filter_by(account_id=account_id))
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        if categorize(r.sender or "", r.subject or "", r.list_unsubscribe or "") == cat:
            out.append(_to_msg(r))
    return out


def _visible(q):
    """drop rows still snoozed into the future (ISO strings sort chronologically)."""
    now = datetime.utcnow().isoformat()
    return q.filter((CachedMessage.snoozed_until == "") | (CachedMessage.snoozed_until <= now))


def save(db, account_id: str, folder: str, msgs: list[dict]) -> int:
    """replace this folder's cache with the latest fetch. local flagged state is
    carried over by uid so an IMAP re-fetch doesn't wipe stars."""
    prev = {
        r.uid: (r.flagged, r.muted, r.snoozed_until or "", r.labels or "")
        for r in db.query(CachedMessage).filter_by(account_id=account_id, folder=folder)
    }
    db.query(CachedMessage).filter_by(account_id=account_id, folder=folder).delete()
    for m in msgs:
        uid = str(m.get("uid", ""))
        pf, pm, ps, pl = prev.get(uid, (False, False, "", ""))
        db.add(
            CachedMessage(
                account_id=account_id,
                folder=folder,
                uid=uid,
                sender=m.get("from", ""),
                subject=m.get("subject", ""),
                date=m.get("date", ""),
                date_ts=m.get("date_ts", 0) or 0,
                seen=bool(m.get("seen")),
                flagged=bool(m.get("flagged", pf)),
                muted=bool(m.get("muted", pm)),  # muting survives an IMAP re-fetch
                list_unsubscribe=m.get("list_unsubscribe", "") or "",
                snoozed_until=m.get("snoozed_until", ps) or "",  # snooze survives re-fetch
                labels=m.get("labels", pl) or "",  # labels survive re-fetch
            )
        )
    db.commit()
    return len(msgs)


def get_unified(db, limit: int = 50) -> list[dict]:
    """one stream across every account's INBOX, newest first."""
    rows = (
        _visible(
            db.query(CachedMessage).filter_by(folder="INBOX").filter(CachedMessage.muted == False)  # noqa: E712 — muted threads hidden
        )
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]


def get_filtered(
    db, account_id, unread=False, flagged=False, folder="INBOX", limit=50
) -> list[dict]:
    q = db.query(CachedMessage).filter_by(account_id=account_id, folder=folder)
    q = _visible(q.filter(CachedMessage.muted == False))  # noqa: E712
    if unread:
        q = q.filter(CachedMessage.seen == False)
    if flagged:
        q = q.filter(CachedMessage.flagged == True)
    rows = q.order_by(CachedMessage.date_ts.desc()).limit(limit).all()
    return [_to_msg(r) for r in rows]


def advanced_search(db, account_id, spec, limit=50) -> list[dict]:
    """search the cache with parsed operators (5a). from/subject/text/before/after are
    answerable from cached headers; to:/has:attachment need the full message (left to IMAP)."""

    def _ts(d):
        try:
            return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    q = db.query(CachedMessage).filter_by(account_id=account_id)
    q = q.filter(CachedMessage.muted == False)  # noqa: E712
    if spec.get("from"):
        q = q.filter(CachedMessage.sender.ilike(f"%{spec['from']}%"))
    if spec.get("subject"):
        q = q.filter(CachedMessage.subject.ilike(f"%{spec['subject']}%"))
    if spec.get("text"):
        like = f"%{spec['text']}%"
        q = q.filter(CachedMessage.subject.ilike(like) | CachedMessage.sender.ilike(like))
    if spec.get("after") and (ts := _ts(spec["after"])) is not None:
        q = q.filter(CachedMessage.date_ts >= ts)
    if spec.get("before") and (ts := _ts(spec["before"])) is not None:
        q = q.filter(CachedMessage.date_ts < ts)
    rows = q.order_by(CachedMessage.date_ts.desc()).limit(limit).all()
    return [_to_msg(r) for r in rows]


def mute(db, account_id, subject) -> int:
    """mute a whole thread: flag every cached message whose normalized subject matches."""
    from services.mail import normalize_subject

    norm = normalize_subject(subject).lower()
    n = 0
    for r in db.query(CachedMessage).filter_by(account_id=account_id):
        if normalize_subject(r.subject or "").lower() == norm:
            r.muted = True
            n += 1
    db.commit()
    return n


def archive(db, account_id, folder, uid) -> int:
    """drop a message from the inbox cache (the IMAP move is best-effort in the route)."""
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .delete()
    )
    db.commit()
    return n


def set_flag(db, account_id, folder, uid, flagged: bool) -> int:
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .update({"flagged": bool(flagged)})
    )
    db.commit()
    return n


def set_seen(db, account_id, folder, uid, seen: bool) -> int:
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .update({"seen": bool(seen)})
    )
    db.commit()
    return n


def get(db, account_id: str, folder: str = "INBOX", limit: int = 30) -> list[dict]:
    rows = (
        _visible(
            db.query(CachedMessage)
            .filter_by(account_id=account_id, folder=folder)
            .filter(CachedMessage.muted == False)  # noqa: E712 — muted threads hidden
        )
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]


def snooze(db, account_id, folder, uid, until) -> int:
    """hide a message until `until` (ISO). it reappears once the cache filter sees now >= until."""
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .update({"snoozed_until": until or ""})
    )
    db.commit()
    return n


def snoozed(db, account_id) -> list[dict]:
    """messages currently snoozed into the future, for the snoozed view."""
    now = datetime.utcnow().isoformat()
    rows = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id)
        .filter(CachedMessage.snoozed_until > now)
        .order_by(CachedMessage.snoozed_until.asc())
        .all()
    )
    return [_to_msg(r) for r in rows]


def search(db, account_id: str, q: str, limit: int = 40) -> list[dict]:
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        db.query(CachedMessage)
        .filter(CachedMessage.account_id == account_id)
        .filter(CachedMessage.subject.ilike(like, escape="\\") | CachedMessage.sender.ilike(like, escape="\\"))
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]
