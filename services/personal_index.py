"""personal recall index - feeds the user's text apps (notes, journal, mail, contacts,
read-later, books) into the shared textindex so the agent can recall them. chunking +
embedding live in services/textindex.py. privacy: the vault is never indexed, the journal
honours its passcode lock, and each source is toggle-able in settings."""

import json

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

_ADAPTERS = {
    "note": {
        "text": _note_text,
        "ref": lambda o: o.id,
        "get": _get_note,
        "label": lambda o: o.title or "(untitled note)",
        "link": lambda ref: f"/?app=notes#{ref}",
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
