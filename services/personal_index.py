"""personal recall index - feeds the user's text apps (notes, journal, mail, contacts,
read-later, books) into the shared textindex so the agent can recall them. chunking +
embedding live in services/textindex.py. privacy: the vault is never indexed, the journal
honours its passcode lock, and each source is toggle-able in settings."""

import json
import time as _time

from core.settings import load_settings
from services import textindex

PERSONAL_KINDS = ("doc", "note", "journal", "mail", "contact", "read", "book")
WRITE_KINDS = ("note", "journal", "mail", "contact", "read", "book")  # the kinds this module owns


# -- gates (read settings each call so toggles take effect live) ---------------
def _indexing_enabled():
    return load_settings().get("pidx_enabled", True)

def _source_enabled(kind):
    return _indexing_enabled() and load_settings().get(f"pidx_{kind}", True)

def _journal_locked():
    return bool(load_settings().get("journal_passcode"))


# -- adapters: each maps a record -> text/ref/label, and a ref -> link ---------
def _note_text(db, n):
    items = ""
    try:
        items = " ".join(i.get("text", "") for i in json.loads(n.items or "[]"))
    except Exception:
        items = ""
    return " ".join(x for x in (n.title, n.content, items, n.tags) if x)

def _get_note(db, ref):
    from core.database import Note
    return db.query(Note).filter_by(id=ref).first()

def _journal_text(db, e):
    return " ".join(x for x in (e.content, e.mood, e.tags) if x)

def _get_journal(db, ref):
    from core.database import JournalEntry
    return db.query(JournalEntry).filter_by(date=ref).first()

def _contact_text(db, c):
    from core.database import ContactField
    fv = " ".join(f.value for f in db.query(ContactField).filter_by(contact_id=c.id).all() if f.value)
    return " ".join(x for x in (c.name, c.company, c.title, c.notes, c.email, c.phone, c.address, fv) if x)

def _get_contact(db, ref):
    from core.database import Contact
    return db.query(Contact).filter_by(id=ref).first()

def _read_text(db, r):
    return " ".join(x for x in (r.title, r.excerpt, r.text, r.tags) if x)

def _get_read(db, ref):
    from core.database import ReadItem
    return db.query(ReadItem).filter_by(id=ref).first()

def _book_text(db, b):
    return " ".join(x for x in (b.title, b.author, b.notes) if x)

def _get_book(db, ref):
    from core.database import Book
    return db.query(Book).filter_by(id=ref).first()

def _iter_notes(db):
    from core.database import Note
    return db.query(Note).all()

def _iter_journal(db):
    from core.database import JournalEntry
    return db.query(JournalEntry).all()

def _iter_contacts(db):
    from core.database import Contact
    return db.query(Contact).all()

def _iter_read(db):
    from core.database import ReadItem
    return db.query(ReadItem).all()

def _iter_books(db):
    from core.database import Book
    return db.query(Book).all()

_ADAPTERS = {
    "note": {
        "text": _note_text,
        "ref": lambda o: o.id,
        "get": _get_note,
        "label": lambda o: o.title or "(untitled note)",
        "link": lambda ref: f"/?app=notes#{ref}",
        "iter": _iter_notes,
    },
    "journal": {
        "text": _journal_text, "ref": lambda o: o.date, "get": _get_journal,
        "label": lambda o: f"journal {o.date}", "link": lambda ref: f"/?app=journal#{ref}",
        "iter": _iter_journal,
    },
    "contact": {
        "text": _contact_text, "ref": lambda o: o.id, "get": _get_contact,
        "label": lambda o: o.name or "(no name)", "link": lambda ref: f"/?app=contacts#{ref}",
        "iter": _iter_contacts,
    },
    "read": {
        "text": _read_text, "ref": lambda o: o.id, "get": _get_read,
        "label": lambda o: o.title or o.url or "(saved item)", "link": lambda ref: f"/?app=read#{ref}",
        "iter": _iter_read,
    },
    "book": {
        "text": _book_text, "ref": lambda o: o.id, "get": _get_book,
        "label": lambda o: o.title or "(book)", "link": lambda ref: f"/?app=books#{ref}",
        "iter": _iter_books,
    },
}


# -- verbs ----------------------------------------------------------------
def index_record(db, kind, obj) -> int:
    ad = _ADAPTERS.get(kind)
    if not ad:
        return 0
    ref = ad["ref"](obj)
    if not _source_enabled(kind) or (kind == "journal" and _journal_locked()):
        return textindex.remove(db, kind, ref)
    text = ad["text"](db, obj)
    if not (text or "").strip():
        return textindex.remove(db, kind, ref)
    return textindex.index(db, kind, ref, text)

def remove_record(db, kind, ref) -> int:
    return textindex.remove(db, kind, ref)

def _label(db, kind, ref):
    ad = _ADAPTERS.get(kind)
    if not ad:
        return ref
    obj = ad["get"](db, ref)
    return ad["label"](obj) if obj else ref

def _link(kind, ref):
    ad = _ADAPTERS.get(kind)
    return ad["link"](ref) if ad else ""

def search(db, query, kinds=None, k=8) -> list[dict]:
    wanted = set(kinds or [x for x in PERSONAL_KINDS if x == "doc" or _source_enabled(x)])
    raw = textindex.search(db, query, kind=None, k=k * 3)
    out = []
    for h in raw:
        if h["kind"] not in wanted:
            continue
        out.append({**h, "label": _label(db, h["kind"], h["ref"]), "link": _link(h["kind"], h["ref"])})
        if len(out) >= k:
            break
    return out


_last_reconcile = ""  # iso, for stats

def reindex_source(db, kind) -> int:
    ad = _ADAPTERS.get(kind)
    if not ad or not _source_enabled(kind) or (kind == "journal" and _journal_locked()):
        from services import textindex as _ti
        _ti.reindex_kind(db, kind, [])  # wipe it
        return 0
    items = []
    for o in ad["iter"](db):
        text = ad["text"](db, o)
        if (text or "").strip():
            items.append((ad["ref"](o), text))
    return textindex.reindex_kind(db, kind, items)

def reindex_all(db) -> dict:
    return {k: reindex_source(db, k) for k in WRITE_KINDS if k != "mail"}  # mail bodies fill in via reconcile

def reconcile(db) -> dict:
    global _last_reconcile
    from core.database import IndexChunk
    orphans = 0
    for kind in WRITE_KINDS:
        ad = _ADAPTERS.get(kind)
        if not ad:
            continue
        refs = {r[0] for r in db.query(IndexChunk.ref).filter_by(kind=kind).distinct().all()}
        for ref in refs:
            if ad["get"](db, ref) is None:
                orphans += textindex.remove(db, kind, ref)
    mailed = _index_mail_batch(db)  # stub returns 0 until A6
    from datetime import datetime
    _last_reconcile = datetime.utcnow().isoformat(timespec="seconds")
    return {"orphans": orphans, "mail_indexed": mailed}

def stats(db) -> dict:
    by = {k: v for k, v in textindex.stats(db).items() if k in PERSONAL_KINDS}
    pending = 0
    try:
        from core.database import CachedMessage
        pending = db.query(CachedMessage).filter_by(body_indexed=False).count()
    except Exception:
        pending = 0
    return {"by_kind": by, "mail_pending": pending, "last_reconcile": _last_reconcile}

def clear(db) -> int:
    n = 0
    for kind in PERSONAL_KINDS:
        from core.database import IndexChunk
        n += db.query(IndexChunk).filter_by(kind=kind).delete()
    db.commit()
    return n

def _index_mail_batch(db, limit=20) -> int:
    return 0  # real implementation in A6
