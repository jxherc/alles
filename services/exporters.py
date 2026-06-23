"""3h - unified multi-format export. pure encoders (json/csv/opml) + a registry that maps each
exportable kind to its allowed formats and a row builder. contacts/calendar reuse the existing
vCard / iCal encoders so there's one export path instead of scattered one-offs.
"""

import io
import json
from xml.sax.saxutils import quoteattr


def to_json(rows):
    return json.dumps(rows, indent=2, default=str)


def _csv_safe(v):
    """neutralize spreadsheet formula injection: a cell starting with = + - @ (or a tab/CR) is
    evaluated as a formula by Excel/Sheets/LibreOffice. prefix a ' so it's treated as text."""
    if isinstance(v, str) and v and v[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(rows):
    """list of dicts -> CSV (header = union of keys, first-seen order). RFC-4180 quoting +
    formula-injection neutralization on cell values."""
    rows = list(rows or [])
    if not rows:
        return ""
    cols = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    import csv

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else _csv_safe(r.get(k))) for k in cols})
    return buf.getvalue()


def to_opml(items):
    """items {title, url} -> OPML 2.0 (feeds/read-later). url goes in xmlUrl."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">', "  <body>"]
    for it in items or []:
        title = quoteattr(str(it.get("title", "") or ""))
        url = it.get("url", "") or ""
        attrs = f"text={title}"
        if url:
            attrs += f' type="link" xmlUrl={quoteattr(url)}'
        lines.append(f"    <outline {attrs}/>")
    lines += ["  </body>", "</opml>"]
    return "\n".join(lines)


# ── row builders (kind -> rows) ───────────────────────────────────────────────
def _tasks(db):
    from core.database import Task

    return [
        {
            "id": t.id,
            "title": t.title,
            "done": bool(t.done),
            "due_date": t.due_date or "",
            "priority": t.priority,
            "project": t.project or "",
            "tags": t.tags or "",
        }
        for t in db.query(Task).order_by(Task.created_at.asc()).all()
    ]


def _notes(db):
    from core.database import Note

    return [
        {
            "id": n.id,
            "title": n.title or "",
            "content": n.content or "",
            "tags": n.tags or "",
            "pinned": bool(n.pinned),
            "archived": bool(n.archived),
        }
        for n in db.query(Note).order_by(Note.created_at.asc()).all()
    ]


def _transactions(db):
    from core.database import Transaction

    return [
        {
            "id": t.id,
            "date": t.date,
            "amount": t.amount,
            "payee": t.payee or "",
            "category": t.category or "",
            "tags": t.tags or "",
            "notes": t.notes or "",
        }
        for t in db.query(Transaction).order_by(Transaction.date.asc()).all()
    ]


def _contacts_vcard(db):
    from core.database import Contact
    from services.vcard import to_vcard

    # to_vcard wants dicts (c.get(...)), not ORM rows — passing Contact objects crashes
    rows = db.query(Contact).order_by(Contact.name).all()
    cards = [
        {
            "name": c.name or "",
            "email": c.email or "",
            "phone": c.phone or "",
            "company": c.company or "",
            "title": c.title or "",
            "address": c.address or "",
            "birthday": c.birthday or "",
            "website": c.website or "",
            "notes": c.notes or "",
        }
        for c in rows
    ]
    return to_vcard(cards)


def _calendar_ics(db):
    from core.database import CalendarEvent
    from routes.calendar import _fmt
    from services.ics import to_ics

    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    return to_ics([_fmt(e) for e in rows])


# kind -> {formats: set, rows: builder, special: {fmt: builder->str}}
EXPORTERS = {
    "tasks": {"formats": ("json", "csv"), "rows": _tasks},
    "notes": {"formats": ("json", "csv"), "rows": _notes},
    "transactions": {"formats": ("json", "csv"), "rows": _transactions},
    "contacts": {
        "formats": ("json", "csv", "vcard"),
        "rows": lambda db: _contacts_rows(db),
        "special": {"vcard": _contacts_vcard},
    },
    "calendar": {
        "formats": ("json", "csv", "ical"),
        "rows": lambda db: _calendar_rows(db),
        "special": {"ical": _calendar_ics},
    },
}

_MEDIA = {
    "json": "application/json",
    "csv": "text/csv",
    "opml": "text/x-opml",
    "vcard": "text/vcard",
    "ical": "text/calendar",
}
_EXT = {"vcard": "vcf", "ical": "ics"}


def _contacts_rows(db):
    from core.database import Contact

    return [
        {"id": c.id, "name": c.name or "", "email": c.email or "", "phone": c.phone or ""}
        for c in db.query(Contact).all()
    ]


def _calendar_rows(db):
    from core.database import CalendarEvent

    return [
        {
            "id": e.id,
            "title": e.title or "",
            "start_dt": str(e.start_dt),
            "all_day": bool(e.all_day),
        }
        for e in db.query(CalendarEvent).all()
    ]


def kinds():
    return {k: list(v["formats"]) for k, v in EXPORTERS.items()}


def export(db, kind, fmt):
    """returns (content, media_type, filename). raises ValueError on unknown kind/format."""
    spec = EXPORTERS.get(kind)
    if not spec:
        raise ValueError(f"unknown export kind: {kind}")
    if fmt not in spec["formats"]:
        raise ValueError(f"{kind} does not support format {fmt}")
    special = spec.get("special", {})
    if fmt in special:
        content = special[fmt](db)
    else:
        rows = spec["rows"](db)
        content = to_csv(rows) if fmt == "csv" else to_json(rows)
    ext = _EXT.get(fmt, fmt)
    return content, _MEDIA.get(fmt, "text/plain"), f"alles-{kind}.{ext}"
