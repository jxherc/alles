"""
persistent header cache for the inbox. the live IMAP fetch warms it; reads come
back instantly from sqlite (and survive a slow/dead network or a restart). local
search runs over the cache so it's instant and works offline.
"""

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
        "account_id": r.account_id,
        "cached": True,
    }


def save(db, account_id: str, folder: str, msgs: list[dict]) -> int:
    """replace this folder's cache with the latest fetch. local flagged state is
    carried over by uid so an IMAP re-fetch doesn't wipe stars."""
    prev = {
        r.uid: r.flagged
        for r in db.query(CachedMessage).filter_by(account_id=account_id, folder=folder)
    }
    db.query(CachedMessage).filter_by(account_id=account_id, folder=folder).delete()
    for m in msgs:
        uid = str(m.get("uid", ""))
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
                flagged=bool(m.get("flagged", prev.get(uid, False))),
            )
        )
    db.commit()
    return len(msgs)


def get_unified(db, limit: int = 50) -> list[dict]:
    """one stream across every account's INBOX, newest first."""
    rows = (
        db.query(CachedMessage)
        .filter_by(folder="INBOX")
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]


def get_filtered(
    db, account_id, unread=False, flagged=False, folder="INBOX", limit=50
) -> list[dict]:
    q = db.query(CachedMessage).filter_by(account_id=account_id, folder=folder)
    if unread:
        q = q.filter(CachedMessage.seen == False)
    if flagged:
        q = q.filter(CachedMessage.flagged == True)
    rows = q.order_by(CachedMessage.date_ts.desc()).limit(limit).all()
    return [_to_msg(r) for r in rows]


def set_flag(db, account_id, folder, uid, flagged: bool) -> int:
    n = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .update({"flagged": bool(flagged)})
    )
    db.commit()
    return n


def get(db, account_id: str, folder: str = "INBOX", limit: int = 30) -> list[dict]:
    rows = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder)
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]


def search(db, account_id: str, q: str, limit: int = 40) -> list[dict]:
    like = f"%{q}%"
    rows = (
        db.query(CachedMessage)
        .filter(CachedMessage.account_id == account_id)
        .filter(CachedMessage.subject.ilike(like) | CachedMessage.sender.ilike(like))
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]
