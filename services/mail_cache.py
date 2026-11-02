"""
persistent header cache for the inbox. the live IMAP fetch warms it; reads come
back instantly from sqlite (and survive a slow/dead network or a restart). local
search runs over the cache so it's instant and works offline.
"""

import json
from datetime import UTC, datetime, timezone

from core.database import CachedMessage, MailBody

# a body bigger than this is read from the server each time instead of kept
BODY_MAX_CHARS = 2_000_000


def _to_msg(r: CachedMessage) -> dict:
    return {
        "uid": r.uid,
        "folder": r.folder,
        "from": r.sender,
        "to": r.recipients or "",
        "subject": r.subject,
        "date": r.date,
        "date_ts": r.date_ts,
        "seen": r.seen,
        "flagged": bool(r.flagged),
        "has_attachment": bool(r.has_attachment),
        "list_unsubscribe": r.list_unsubscribe or "",
        "muted": bool(r.muted),
        "snoozed_until": r.snoozed_until or "",
        "labels": [x for x in (r.labels or "").split(",") if x],
        "account_id": r.account_id,
        "thread_id": r.thread_id or "",
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
    rows = db.query(CachedMessage).filter_by(account_id=account_id, folder=folder, uid=str(uid))
    # Reserve the SQLite writer before reading so concurrent additions cannot replace each other.
    if not rows.update({"labels": CachedMessage.labels}, synchronize_session=False):
        db.commit()
        return None
    messages = rows.populate_existing().all()
    labels = _norm_labels(
        [value for row in messages for value in (row.labels or "").split(",")] + [label]
    )
    for row in messages:
        row.labels = labels
    db.commit()
    return [value for value in labels.split(",") if value]


def by_label(db, account_id, label, limit=200):
    if limit <= 0:
        return []
    lab = str(label).strip().lower()
    rows = (
        _visible(db.query(CachedMessage).filter_by(account_id=account_id))
        .filter(CachedMessage.labels.like(f"%{lab}%"))
        .order_by(CachedMessage.date_ts.desc())
        .all()
    )
    out = []
    for r in rows:
        labels = [x.strip().lower() for x in (r.labels or "").split(",") if x.strip()]
        if lab in labels:
            out.append(_to_msg(r))
            if len(out) >= limit:
                break
    return out


def by_category(db, account_id, cat, limit=200):
    from services.mail import categorize

    if limit <= 0:
        return []
    rows = (
        _visible(db.query(CachedMessage).filter_by(account_id=account_id))
        .order_by(CachedMessage.date_ts.desc())
        .all()
    )
    out = []
    for r in rows:
        if categorize(r.sender or "", r.subject or "", r.list_unsubscribe or "") == cat:
            out.append(_to_msg(r))
            if len(out) >= limit:
                break
    return out


def _visible(q):
    """drop rows still snoozed into the future (ISO strings sort chronologically)."""
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    return q.filter((CachedMessage.snoozed_until == "") | (CachedMessage.snoozed_until <= now))


def save(db, account_id: str, folder: str, msgs: list[dict]) -> int:
    """replace this folder's cache with the latest fetch. local flagged state is
    carried over by uid so an IMAP re-fetch doesn't wipe stars."""
    prev = {
        r.uid: (r.flagged, r.muted, r.snoozed_until or "", r.labels or "")
        for r in db.query(CachedMessage).filter_by(account_id=account_id, folder=folder)
    }
    db.query(CachedMessage).filter_by(account_id=account_id, folder=folder).delete()
    from services.mail import thread_messages

    for m in thread_messages(msgs):  # 2i - assign reference-graph thread_id
        uid = str(m.get("uid", ""))
        pf, pm, ps, pl = prev.get(uid, (False, False, "", ""))
        db.add(
            CachedMessage(
                account_id=account_id,
                folder=folder,
                uid=uid,
                sender=m.get("from", ""),
                recipients=m.get("to", "") or "",
                subject=m.get("subject", ""),
                date=m.get("date", ""),
                date_ts=m.get("date_ts", 0) or 0,
                seen=bool(m.get("seen")),
                flagged=bool(m.get("flagged", pf)),
                has_attachment=bool(m.get("has_attachment") or m.get("attachments")),
                muted=bool(m.get("muted", pm)),  # muting survives an IMAP re-fetch
                list_unsubscribe=m.get("list_unsubscribe", "") or "",
                snoozed_until=m.get("snoozed_until", ps) or "",  # snooze survives re-fetch
                labels=m.get("labels", pl) or "",  # labels survive re-fetch
                message_id=m.get("message_id", "") or "",
                in_reply_to=m.get("in_reply_to", "") or "",
                references=m.get("references", "") or "",
                thread_id=m.get("thread_id", "") or "",
            )
        )
    _prune_bodies(db, account_id, folder, msgs)
    db.commit()
    return len(msgs)


def _prune_bodies(db, account_id, folder, msgs):
    """a stored body lives only as long as its message is in the folder's latest fetch. a new
    uidvalidity means the server renumbered the folder, so every stored body there goes."""
    keep = {str(m.get("uid", "")) for m in msgs}
    validity = next((str(m["uidvalidity"]) for m in msgs if m.get("uidvalidity")), "")
    rows = db.query(MailBody).filter_by(account_id=account_id, folder=folder)
    for row in rows:
        if row.uid not in keep or (validity and row.uidvalidity != validity):
            db.delete(row)


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
    """search the cache with parsed operators (5a)."""

    def _ts(d):
        try:
            return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    q = db.query(CachedMessage).filter_by(account_id=account_id)
    q = q.filter(CachedMessage.muted == False)  # noqa: E712
    if spec.get("from"):
        q = q.filter(CachedMessage.sender.ilike(f"%{spec['from']}%"))
    if spec.get("to"):
        q = q.filter(CachedMessage.recipients.ilike(f"%{spec['to']}%"))
    if spec.get("subject"):
        q = q.filter(CachedMessage.subject.ilike(f"%{spec['subject']}%"))
    if spec.get("has_attachment"):
        q = q.filter(CachedMessage.has_attachment == True)  # noqa: E712
    if spec.get("text"):
        like = f"%{spec['text']}%"
        q = q.filter(CachedMessage.subject.ilike(like) | CachedMessage.sender.ilike(like))
    if spec.get("after") and (ts := _ts(spec["after"])) is not None:
        q = q.filter(CachedMessage.date_ts >= ts)
    if spec.get("before") and (ts := _ts(spec["before"])) is not None:
        q = q.filter(CachedMessage.date_ts < ts)
    rows = q.order_by(CachedMessage.date_ts.desc()).limit(limit).all()
    return [_to_msg(r) for r in rows]


def get_muted(db, account_id, limit=50) -> list[dict]:
    if limit <= 0:
        return []
    rows = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, muted=True)
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(row) for row in rows]


def mute(db, account_id, subject, muted: bool = True) -> int:
    """set the mute state of this account's normalized-subject thread."""
    from services.mail import normalize_subject

    norm = normalize_subject(subject).lower()
    n = 0
    for r in db.query(CachedMessage).filter_by(account_id=account_id):
        if normalize_subject(r.subject or "").lower() == norm:
            r.muted = bool(muted)
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
    db.query(MailBody).filter_by(account_id=account_id, folder=folder, uid=str(uid)).delete()
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
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
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
        .filter(
            CachedMessage.subject.ilike(like, escape="\\")
            | CachedMessage.sender.ilike(like, escape="\\")
        )
        .order_by(CachedMessage.date_ts.desc())
        .limit(limit)
        .all()
    )
    return [_to_msg(r) for r in rows]


# ── stored bodies: open a message without asking the mail server ────────────────


def _body_and_header(db, account_id, folder, uid):
    """the stored body and the header row it belongs to, or None when either is gone or they
    no longer describe the same message (a reused uid shows up as a new message-id)."""
    body = db.query(MailBody).filter_by(account_id=account_id, folder=folder, uid=str(uid)).first()
    if body is None:
        return None
    header = (
        db.query(CachedMessage)
        .filter_by(account_id=account_id, folder=folder, uid=str(uid))
        .first()
    )
    if header is None or (header.message_id or "") != (body.message_id or ""):
        db.delete(body)
        db.commit()
        return None
    return body


def stored_body(db, account_id, folder, uid) -> dict | None:
    """the message as the reader wants it, from the database, or None to ask the server."""
    body = _body_and_header(db, account_id, folder, uid)
    if body is None:
        return None
    return {
        "uid": body.uid,
        "from": body.sender or "",
        "to": body.recipients or "",
        "subject": body.subject or "",
        "date": body.date or "",
        "message_id": body.message_id or "",
        "references": body.references or "",
        "has_attachment": bool(body.has_attachment),
        "text": body.text or "",
        "html": body.html or "",
        "stored": True,
    }


def keep_body(db, account_id, folder, msg) -> bool:
    """store a message read from the server, when its header row is saved and agrees on the
    message-id. a message nobody listed (a search hit, another folder) isn't kept."""
    uid = str(msg.get("uid", ""))
    if not uid or msg.get("error") or not isinstance(msg.get("text"), str):
        return False
    if len(msg.get("text") or "") + len(msg.get("html") or "") > BODY_MAX_CHARS:
        return False
    header = (
        db.query(CachedMessage).filter_by(account_id=account_id, folder=folder, uid=uid).first()
    )
    message_id = (msg.get("message_id") or "").strip()
    if header is None or (header.message_id or "") != message_id:
        return False
    row = db.query(MailBody).filter_by(account_id=account_id, folder=folder, uid=uid).first()
    if row is None:
        row = MailBody(account_id=account_id, folder=folder, uid=uid)
        db.add(row)
    row.uidvalidity = str(msg.get("uidvalidity") or "")
    row.message_id = message_id
    row.sender = msg.get("from", "") or ""
    row.recipients = msg.get("to", "") or ""
    row.subject = msg.get("subject", "") or ""
    row.date = msg.get("date", "") or ""
    row.references = msg.get("references", "") or ""
    row.has_attachment = bool(msg.get("has_attachment"))
    row.text = msg.get("text") or ""
    row.html = msg.get("html") or ""
    row.fetched_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return True


def missing_bodies(db, account_id, folder, limit) -> list[str]:
    """uids of the newest listed messages that have no stored body yet, newest first."""
    stored = {
        uid for (uid,) in db.query(MailBody.uid).filter_by(account_id=account_id, folder=folder)
    }
    rows = get(db, account_id, folder, limit)
    return [m["uid"] for m in rows if m["uid"] not in stored]


def stored_attachments(db, account_id, folder, uid) -> list | None:
    """the attachment list without the server: [] for a message stored without any, the list
    once it was read, None when the server has to be asked."""
    body = _body_and_header(db, account_id, folder, uid)
    if body is None:
        return None
    if not body.has_attachment:
        return []
    try:
        return json.loads(body.attachments) if body.attachments else None
    except ValueError:
        return None


def keep_attachments(db, account_id, folder, uid, attachments) -> None:
    body = _body_and_header(db, account_id, folder, uid)
    if body is not None:
        body.attachments = json.dumps(attachments)
        db.commit()


def forget_bodies(db, account_id) -> None:
    """drop every stored body of an account (it was removed)."""
    db.query(MailBody).filter_by(account_id=account_id).delete()
