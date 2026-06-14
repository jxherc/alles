"""
persistent header cache for the inbox. the live IMAP fetch warms it; reads come
back instantly from sqlite (and survive a slow/dead network or a restart). local
search runs over the cache so it's instant and works offline.
"""
from core.database import CachedMessage


def _to_msg(r: CachedMessage) -> dict:
    return {
        "uid": r.uid, "from": r.sender, "subject": r.subject,
        "date": r.date, "date_ts": r.date_ts, "seen": r.seen, "cached": True,
    }


def save(db, account_id: str, folder: str, msgs: list[dict]) -> int:
    """replace this folder's cache with the latest fetch."""
    db.query(CachedMessage).filter_by(account_id=account_id, folder=folder).delete()
    for m in msgs:
        db.add(CachedMessage(
            account_id=account_id, folder=folder, uid=str(m.get("uid", "")),
            sender=m.get("from", ""), subject=m.get("subject", ""),
            date=m.get("date", ""), date_ts=m.get("date_ts", 0) or 0,
            seen=bool(m.get("seen")),
        ))
    db.commit()
    return len(msgs)


def get(db, account_id: str, folder: str = "INBOX", limit: int = 30) -> list[dict]:
    rows = (db.query(CachedMessage)
            .filter_by(account_id=account_id, folder=folder)
            .order_by(CachedMessage.date_ts.desc()).limit(limit).all())
    return [_to_msg(r) for r in rows]


def search(db, account_id: str, q: str, limit: int = 40) -> list[dict]:
    like = f"%{q}%"
    rows = (db.query(CachedMessage)
            .filter(CachedMessage.account_id == account_id)
            .filter(CachedMessage.subject.ilike(like) | CachedMessage.sender.ilike(like))
            .order_by(CachedMessage.date_ts.desc()).limit(limit).all())
    return [_to_msg(r) for r in rows]
