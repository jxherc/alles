# Personal RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** let aide answer questions grounded in the user's own text (mail, notes, journal, contacts, read-later, books) by feeding those apps into the existing `textindex`, and give the agent a `recall` tool plus a read-only `money_query` tool so it can blend recall with live analytics.

**Architecture:** a new `services/personal_index.py` owns per-source adapters (record -> text/ref/label/link) and wraps the existing `services/textindex.py` (chunk + embed + store in `IndexChunk`). On-write hooks in each app's routes keep it fresh per-record; a reconcile job catches drift and incrementally indexes mail bodies. The agent gets two read-only tools. A settings section controls it.

**Tech Stack:** python 3.11, fastapi, sqlalchemy/sqlite, the existing `textindex` + `memory_store` (fastembed with jaccard fallback), the `jobs` background registry, vanilla-js settings UI.

## Global Constraints

- house style: lowercase commit messages, NO em/en-dashes anywhere (use "-"), minimal informal comments, no AI attribution, commit author `jxherc <houjx0103@gmail.com>`.
- reuse `services/textindex.py` for all chunking/embedding/storage. do NOT add a new vector store.
- agent tool handlers return exactly `{"output": str, "error": bool}`.
- DB access in tools/jobs: `db = SessionLocal()` inside a `try/finally` that calls `db.close()`; lazy-import models from `core.database`.
- on-write index hooks are BEST-EFFORT: wrapped in `try/except` so an index failure never breaks the user's save.
- the secrets vault is NEVER indexed (no adapter touches `vault_entries`/`vault_attachments`).
- the journal honours its passcode: when settings `journal_passcode` is set, journal entries are not indexed and existing `journal` chunks are dropped.
- pinned settings keys (flat booleans, default True): `pidx_enabled`, `pidx_mail`, `pidx_note`, `pidx_journal`, `pidx_contact`, `pidx_read`, `pidx_book`.
- frontend changes require bumping all four cache stamps together: `static/sw.js` `VERSION` (`v93`->`v94`) + `STAMP` (`119`->`120`), `static/index.html` `style.css?v=` (`119`->`120`) and `const _v` (`119`->`120`).
- unit tests build an isolated db: `create_engine("sqlite:///:memory:")` + `Base.metadata.create_all`. route tests call the route handler functions directly, passing that in-memory session as the `db` arg (bypassing `Depends`), so nothing touches real data.

---

## File Structure

- **Create** `services/personal_index.py` - adapters + gates + index_record/remove_record/search/reindex/reconcile/stats/clear. one focused module.
- **Create** `routes/recall.py` - `/api/recall/{reindex,stats,clear}` management endpoints.
- **Modify** `routes/notes.py`, `routes/journal.py`, `routes/contacts.py`, `routes/read.py`, `routes/books.py` - one best-effort hook call at each commit point.
- **Modify** `core/database.py` - add `CachedMessage.body_indexed` column + its migration.
- **Modify** `app.py` - register the reconcile job; include the recall router.
- **Modify** `services/agent_tools.py` - `recall` + `money_query` tool schemas, permissions, dispatch, handlers.
- **Modify** `core/settings.py` (defaults), `routes/settings.py` (SettingsPatch), `static/js/settings.js` + `static/index.html` (the settings pane), `static/sw.js` (cache bump).
- **Create** tests: `tests/test_personal_index.py`, `tests/test_personal_hooks.py`, `tests/test_recall_tools.py`, `tests/test_api_recall.py`, `tests/pw_recall_settings.py`.

---

# PHASE A - the recall index (ingestion + freshness + privacy)

### Task A1: personal_index module + note adapter + core verbs

**Files:**
- Create: `services/personal_index.py`
- Test: `tests/test_personal_index.py`

**Interfaces:**
- Consumes: `services/textindex.py` -> `index(db, kind, ref, text)`, `remove(db, kind, ref)`, `search(db, query, kind=None, k)`; `core.settings.load_settings()`.
- Produces: `PERSONAL_KINDS`, `WRITE_KINDS`, `_indexing_enabled()`, `_source_enabled(kind)`, `_journal_locked()`, `index_record(db, kind, obj) -> int`, `remove_record(db, kind, ref) -> int`, `search(db, query, kinds=None, k=8) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_index.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base, Note
from services import personal_index as pix

def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()

def test_note_indexed_and_searchable():
    db = _db()
    n = Note(id="n1", title="apartment hunt", content="viewed a 2br near the park", tags="home")
    db.add(n); db.commit()
    assert pix.index_record(db, "note", n) > 0
    hits = pix.search(db, "apartment park", k=5)
    assert any(h["ref"] == "n1" and h["kind"] == "note" for h in hits)
    assert hits[0]["label"] == "apartment hunt"
    assert hits[0]["link"] == "/?app=notes#n1"

def test_remove_record():
    db = _db()
    n = Note(id="n2", title="temp", content="throwaway")
    db.add(n); db.commit()
    pix.index_record(db, "note", n)
    assert pix.remove_record(db, "note", "n2") >= 1
    assert not pix.search(db, "throwaway", k=5)
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.personal_index'`.

- [ ] **Step 3: Implement**

```python
# services/personal_index.py
"""personal recall index - feeds the user's text apps (notes, journal, mail, contacts,
read-later, books) into the shared textindex so the agent can recall them. chunking +
embedding live in services/textindex.py. privacy: the vault is never indexed, the journal
honours its passcode lock, and each source is toggle-able in settings."""

import json

from core.settings import load_settings
from services import textindex

PERSONAL_KINDS = ("doc", "note", "journal", "mail", "contact", "read", "book")
WRITE_KINDS = ("note", "journal", "mail", "contact", "read", "book")  # the kinds this module owns


# ── gates (read settings each call so toggles take effect live) ──────────────
def _indexing_enabled():
    return load_settings().get("pidx_enabled", True)

def _source_enabled(kind):
    return _indexing_enabled() and load_settings().get(f"pidx_{kind}", True)

def _journal_locked():
    return bool(load_settings().get("journal_passcode"))


# ── adapters: each maps a record -> text/ref/label, and a ref -> link ────────
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


# ── verbs ────────────────────────────────────────────────────────────────────
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
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/personal_index.py tests/test_personal_index.py
git commit -m "personal index: module + note adapter + index/remove/search"
```

---

### Task A2: journal/contact/read/book adapters

**Files:**
- Modify: `services/personal_index.py` (add four entries to `_ADAPTERS` + their helpers)
- Test: `tests/test_personal_index.py` (add cases)

**Interfaces:**
- Consumes: the `_ADAPTERS` shape from A1 (`text(db,obj)`, `ref(obj)`, `get(db,ref)`, `label(obj)`, `link(ref)`).
- Produces: adapters for kinds `journal`, `contact`, `read`, `book`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_index.py (append)
from core.database import JournalEntry, Contact, ContactField, ReadItem, Book

def test_journal_contact_read_book():
    db = _db()
    db.add(JournalEntry(id="j1", date="2026-03-04", content="felt good about the move", mood="happy")); db.commit()
    db.add(Contact(id="c1", name="Sam Rivera", company="Acme", notes="met at the trip")); db.commit()
    db.add(ContactField(id="cf1", contact_id="c1", kind="email", label="work", value="sam@acme.com")); db.commit()
    db.add(ReadItem(id="r1", url="http://x", title="rust tips", text="ownership and borrowing")); db.commit()
    db.add(Book(id="b1", title="Dune", author="Herbert", notes="reread the desert parts")); db.commit()
    for kind, ref, obj_q, q, want in [
        ("journal", "2026-03-04", JournalEntry, "felt good move", "journal 2026-03-04"),
        ("contact", "c1", Contact, "sam acme trip", "Sam Rivera"),
        ("read", "r1", ReadItem, "ownership borrowing", "rust tips"),
        ("book", "b1", Book, "desert reread", "Dune"),
    ]:
        obj = db.query(obj_q).filter_by(id=ref).first() if kind != "journal" else db.query(JournalEntry).filter_by(date=ref).first()
        assert pix.index_record(db, kind, obj) > 0
        hits = pix.search(db, q, kinds=[kind], k=5)
        assert hits and hits[0]["label"] == want
    # contact field value is searchable too
    assert any(h["ref"] == "c1" for h in pix.search(db, "sam@acme.com", kinds=["contact"], k=5))
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_index.py::test_journal_contact_read_book -q`
Expected: FAIL with `KeyError`/empty hits (adapters not registered).

- [ ] **Step 3: Implement**

Add these helpers above `_ADAPTERS` and the four entries inside it in `services/personal_index.py`:

```python
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
```

```python
# add inside _ADAPTERS (after the "note" entry):
    "journal": {
        "text": _journal_text, "ref": lambda o: o.date, "get": _get_journal,
        "label": lambda o: f"journal {o.date}", "link": lambda ref: f"/?app=journal#{ref}",
    },
    "contact": {
        "text": _contact_text, "ref": lambda o: o.id, "get": _get_contact,
        "label": lambda o: o.name or "(no name)", "link": lambda ref: f"/?app=contacts#{ref}",
    },
    "read": {
        "text": _read_text, "ref": lambda o: o.id, "get": _get_read,
        "label": lambda o: o.title or o.url or "(saved item)", "link": lambda ref: f"/?app=read#{ref}",
    },
    "book": {
        "text": _book_text, "ref": lambda o: o.id, "get": _get_book,
        "label": lambda o: o.title or "(book)", "link": lambda ref: f"/?app=books#{ref}",
    },
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add services/personal_index.py tests/test_personal_index.py
git commit -m "personal index: journal/contact/read/book adapters"
```

---

### Task A3: privacy gates (journal lock, per-source disable, vault exclusion)

**Files:**
- Modify: `services/personal_index.py` (gates already exist; this task proves + hardens them)
- Test: `tests/test_personal_index.py` (add cases)

**Interfaces:**
- Consumes: `index_record`, `search`, `_source_enabled`, `_journal_locked` from A1.
- Produces: guaranteed behaviour: locked journal -> not indexed + existing dropped; disabled source -> not indexed; no adapter for any vault kind.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_index.py (append)
import services.personal_index as pixmod

def test_journal_lock_blocks_and_drops(monkeypatch):
    db = _db()
    e = JournalEntry(id="j9", date="2026-01-01", content="secret thoughts")
    db.add(e); db.commit()
    pix.index_record(db, "journal", e)
    assert pix.search(db, "secret thoughts", kinds=["journal"], k=5)
    monkeypatch.setattr(pixmod, "_journal_locked", lambda: True)
    # re-indexing a locked journal removes it instead of indexing
    pix.index_record(db, "journal", e)
    assert not pix.search(db, "secret thoughts", kinds=["journal"], k=5)

def test_disabled_source_not_indexed(monkeypatch):
    db = _db()
    n = Note(id="nz", title="hidden", content="should not index")
    db.add(n); db.commit()
    monkeypatch.setattr(pixmod, "_source_enabled", lambda k: k != "note")
    assert pix.index_record(db, "note", n) == 0
    assert not pix.search(db, "hidden", kinds=["note"], k=5)

def test_no_vault_adapter():
    assert "vault" not in pix._ADAPTERS
    assert "vault" not in pix.PERSONAL_KINDS
    # indexing an unknown kind is a no-op
    db = _db()
    assert pix.index_record(db, "vault", object()) == 0
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_index.py -k "lock or disabled or vault" -q`
Expected: FAIL only if gates are wrong. (If A1/A2 implemented the gates as written, `test_no_vault_adapter` passes already; the monkeypatched ones confirm `index_record` consults the gates - they should pass. If any fail, the gate wiring in `index_record` is the bug to fix.)

- [ ] **Step 3: Implement**

The gates are already wired in `index_record` (A1). If `test_disabled_source_not_indexed` fails because `index_record` returned a remove-count > 0, make the disabled/locked branch return `0` when there was nothing to remove - it already calls `textindex.remove` which returns the deleted count (0 when absent), so no change needed. No code change expected; this task locks the behaviour with tests. If a test reveals a gap, fix `index_record` so the gate check happens BEFORE computing text.

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tests/test_personal_index.py services/personal_index.py
git commit -m "personal index: lock + per-source + vault-exclusion gates (tested)"
```

---

### Task A4: on-write hooks in the five app routes

**Files:**
- Modify: `routes/notes.py`, `routes/journal.py`, `routes/contacts.py`, `routes/read.py`, `routes/books.py`
- Test: `tests/test_personal_hooks.py`

**Interfaces:**
- Consumes: `personal_index.index_record(db, kind, obj)`, `personal_index.remove_record(db, kind, ref)`.
- Produces: each create/update re-indexes that record; each delete removes it. all best-effort.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_hooks.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from services import personal_index as pix

def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()

def test_note_route_hooks():
    import routes.notes as R
    db = _db()
    created = R.create_note(R.NoteBody(title="ski trip", content="booked the cabin"), db=db)
    nid = created["id"] if isinstance(created, dict) else created.id
    assert pix.search(db, "cabin booked", kinds=["note"], k=5)
    R.update_note(nid, R.NoteBody(title="ski trip", content="cancelled the cabin"), db=db)
    assert pix.search(db, "cancelled", kinds=["note"], k=5)
    R.delete_note(nid, db=db)
    assert not pix.search(db, "ski trip", kinds=["note"], k=5)
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_hooks.py -q`
Expected: FAIL - after delete the note is still found (no hook yet). (Adjust the `NoteBody` field names / return shape to match the real `routes/notes.py` when you read it.)

- [ ] **Step 3: Implement**

Add a tiny best-effort helper call after each commit. In `routes/notes.py`, after `db.commit()` in `create_note` and `update_note`:

```python
    try:
        from services import personal_index
        personal_index.index_record(db, "note", n)
    except Exception:
        pass
```

In `delete_note`, capture the id before delete and after `db.commit()`:

```python
    try:
        from services import personal_index
        personal_index.remove_record(db, "note", nid)
    except Exception:
        pass
```

Repeat the same pattern in the other routes, using the right kind/object/ref:
- `routes/journal.py` `upsert_entry`: `personal_index.index_record(db, "journal", e)`; `delete_entry`: `personal_index.remove_record(db, "journal", day)`.
- `routes/contacts.py` `create_contact`/`patch_contact`: `index_record(db, "contact", c)`; `delete_contact`: `remove_record(db, "contact", cid)`; `add_field`/`delete_field`: re-index the parent contact `index_record(db, "contact", db.query(Contact).filter_by(id=cid).first())`.
- `routes/read.py` `save_item`/`patch_item`/`toggle_read`: `index_record(db, "read", it)`; `delete_item`: `remove_record(db, "read", rid)`.
- `routes/books.py` `create_book`/`update_book`: `index_record(db, "book", b)`; `delete_book`: `remove_record(db, "book", bid)`.

Each call is wrapped in `try/except Exception: pass` so indexing never breaks a save.

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_hooks.py -q`
Expected: PASS. Also run the existing route tests to confirm no regression: `python -m pytest tests/test_api_notes.py tests/test_api_contacts*.py -q`.

- [ ] **Step 5: Commit**

```bash
git add routes/notes.py routes/journal.py routes/contacts.py routes/read.py routes/books.py tests/test_personal_hooks.py
git commit -m "personal index: best-effort on-write hooks in note/journal/contact/read/book routes"
```

---

### Task A5: backfill + reconcile job

**Files:**
- Modify: `services/personal_index.py` (add `reindex_source`, `reindex_all`, `reconcile`, `stats`, `clear`, `_last_reconcile`)
- Modify: `app.py` (register the reconcile job in `_register_jobs()`)
- Test: `tests/test_personal_index.py` (reconcile cases)

**Interfaces:**
- Consumes: `_ADAPTERS`, `textindex.reindex_kind(db, kind, items)`, `textindex.stats(db)`, `IndexChunk`.
- Produces: `reindex_source(db, kind) -> int`, `reindex_all(db) -> dict`, `reconcile(db) -> dict`, `stats(db) -> dict`, `clear(db) -> int`. Each adapter gains an `iter(db)` iterator.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_index.py (append)
from core.database import IndexChunk

def test_backfill_and_reconcile_orphans():
    db = _db()
    db.add(Note(id="a", title="alpha note", content="keep me")); db.commit()
    db.add(Note(id="b", title="beta note", content="delete me")); db.commit()
    assert pix.reindex_source(db, "note") == 2 or pix.reindex_source(db, "note") > 0
    # delete row b at the table level WITHOUT a hook -> index now has an orphan
    db.query(Note).filter_by(id="b").delete(); db.commit()
    res = pix.reconcile(db)
    assert res["orphans"] >= 1
    refs = {c.ref for c in db.query(IndexChunk).filter_by(kind="note").all()}
    assert "b" not in refs and "a" in refs

def test_stats_and_clear():
    db = _db()
    db.add(Note(id="s1", title="x", content="hello world")); db.commit()
    pix.reindex_source(db, "note")
    st = pix.stats(db)
    assert st["by_kind"].get("note", 0) >= 1
    assert pix.clear(db) >= 1
    assert pix.stats(db)["by_kind"].get("note", 0) == 0
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_index.py -k "reconcile or stats" -q`
Expected: FAIL with `AttributeError: module 'services.personal_index' has no attribute 'reindex_source'`.

- [ ] **Step 3: Implement**

Add an `iter` to each adapter entry (note example: `"iter": lambda db: db.query(Note).all()`; journal `JournalEntry`; contact `Contact`; read `ReadItem`; book `Book`; mail handled in A6). Then add to `services/personal_index.py`:

```python
import time as _time

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
    mailed = _index_mail_batch(db)  # defined in A6; returns 0 until then
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
```

Add a stub for the mail batch so A5 runs before A6:

```python
def _index_mail_batch(db, limit=20) -> int:
    return 0  # real implementation in A6
```

Register the job in `app.py` inside `_register_jobs()` (mirror `jobs.register("subscriptions", _subs, 30)`):

```python
    async def _reconcile():
        from core.database import SessionLocal
        from services import personal_index
        db = SessionLocal()
        try:
            personal_index.reconcile(db)
        finally:
            db.close()

    jobs.register("personal_reconcile", _reconcile, 120, run_at_start=False)
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add services/personal_index.py app.py tests/test_personal_index.py
git commit -m "personal index: backfill, reconcile (orphan-drop), stats, clear + job"
```

---

### Task A6: mail adapter + incremental body indexer

**Files:**
- Modify: `core/database.py` (`CachedMessage.body_indexed` column + migration)
- Modify: `services/personal_index.py` (mail adapter + real `_index_mail_batch`)
- Test: `tests/test_personal_index.py` (mail cases, faked fetch)

**Interfaces:**
- Consumes: `CachedMessage(account_id, uid, sender, subject, body_indexed)`, `services.mail` body fetch.
- Produces: `mail` adapter (ref `f"{account_id}:{uid}"`, immediate text = subject+sender), `_index_mail_batch(db, limit=20) -> int` that indexes bodies for `body_indexed=False` rows and flips the flag.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personal_index.py (append)
from core.database import CachedMessage

def test_mail_subject_indexed_and_body_batch(monkeypatch):
    db = _db()
    m = CachedMessage(id="m1", account_id="acc", uid="42", sender="sam@acme.com", subject="trip plans")
    db.add(m); db.commit()
    # subject/sender searchable immediately via the adapter
    pix.index_record(db, "mail", m)
    assert pix.search(db, "trip plans sam", kinds=["mail"], k=5)
    # body indexer pulls the body and re-indexes, flips body_indexed
    monkeypatch.setattr(pix, "_fetch_mail_body", lambda db, msg: "we leave friday from the north station")
    n = pix._index_mail_batch(db, limit=10)
    assert n == 1
    assert db.query(CachedMessage).filter_by(id="m1").first().body_indexed is True
    assert pix.search(db, "north station friday", kinds=["mail"], k=5)
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_personal_index.py::test_mail_subject_indexed_and_body_batch -q`
Expected: FAIL - `mail` not in `_ADAPTERS` / `_fetch_mail_body` missing.

- [ ] **Step 3: Implement**

In `core/database.py`, add to `class CachedMessage`:

```python
    body_indexed = Column(Boolean, default=False)  # personal-rag: body pulled into the recall index
```

and in `init_db()` migrations block:

```python
        _add_col(conn, "cached_messages", "body_indexed", "BOOLEAN DEFAULT 0")
```

In `services/personal_index.py`, add the mail helpers + adapter entry + replace the `_index_mail_batch` stub:

```python
def _mail_text(db, m):
    return " ".join(x for x in (m.subject, m.sender) if x)

def _get_mail(db, ref):
    from core.database import CachedMessage
    acct, _, uid = (ref or "").partition(":")
    return db.query(CachedMessage).filter_by(account_id=acct, uid=uid).first()

# add inside _ADAPTERS:
    "mail": {
        "text": _mail_text, "ref": lambda o: f"{o.account_id}:{o.uid}", "get": _get_mail,
        "iter": lambda db: db.query(_cm()).all(),
        "label": lambda o: o.subject or "(no subject)", "link": lambda ref: "/?app=mail",
    },

def _cm():
    from core.database import CachedMessage
    return CachedMessage

def _fetch_mail_body(db, msg):
    """best-effort body fetch; isolated so tests can monkeypatch it."""
    try:
        from core.database import MailAccount
        from services import mail as mailsvc
        acct = db.query(MailAccount).filter_by(id=msg.account_id).first()
        if not acct:
            return ""
        full = mailsvc.fetch_message(acct, msg.uid)  # adjust to the real body-fetch signature when wiring
        return (full or {}).get("text") or (full or {}).get("body") or ""
    except Exception:
        return ""

def _index_mail_batch(db, limit=20) -> int:
    from core.database import CachedMessage
    if not _source_enabled("mail"):
        return 0
    rows = db.query(CachedMessage).filter_by(body_indexed=False).limit(limit).all()
    done = 0
    for m in rows:
        body = _fetch_mail_body(db, m)
        text = " ".join(x for x in (m.subject, m.sender, body) if x)
        if text.strip():
            textindex.index(db, "mail", f"{m.account_id}:{m.uid}", text)
        m.body_indexed = True
        done += 1
    if done:
        db.commit()
    return done
```

(When wiring `_fetch_mail_body`, confirm the real body-fetch function in `services/mail.py` - the explore notes show `fetch_inbox(acct, folder, limit)`; use the message-body fetch the Mail route uses to open a single message, and back off on imap errors by returning "".)

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_personal_index.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add core/database.py services/personal_index.py tests/test_personal_index.py
git commit -m "personal index: mail subject + incremental body indexer"
```

---

# PHASE B - the blend (agent tools)

### Task B1: the `recall` agent tool

**Files:**
- Modify: `services/agent_tools.py` (schema in `APP_TOOL_DEFS`, `TOOL_PERMISSION`, `UNTRUSTED_TOOLS`, dispatch in `execute`, handler `_recall`)
- Test: `tests/test_recall_tools.py`

**Interfaces:**
- Consumes: `personal_index.search(db, query, k)`; the `_tool(name, desc, props, required)` helper; `execute(name, args)` dispatch.
- Produces: tool `recall` returning `{"output": str, "error": bool}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recall_tools.py
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import core.database as DB
from core.database import Base, Note
from services import personal_index as pix
from services import agent_tools

def _bind_memory_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    DB.SessionLocal = sessionmaker(bind=eng)  # tools open their own SessionLocal
    return DB.SessionLocal()

def test_recall_tool_finds_note():
    db = _bind_memory_db()
    db.add(Note(id="n1", title="garage code", content="the side door code is 4417")); db.commit()
    pix.index_record(db, "note", db.query(Note).filter_by(id="n1").first())
    out = asyncio.run(agent_tools.execute("recall", {"query": "garage door code"}))
    assert not out.get("error")
    assert "garage code" in out["output"]
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_recall_tools.py::test_recall_tool_finds_note -q`
Expected: FAIL - `execute` returns `unknown tool: recall`.

- [ ] **Step 3: Implement**

In `services/agent_tools.py`:

Add to `APP_TOOL_DEFS`:

```python
    _tool(
        "recall",
        "Semantically recall the user's own saved text - their notes, journal, mail, contacts, "
        "saved articles, and books. Use for 'find / what did / remember / which' questions about "
        "the user's life. Cite each fact with the returned source link; if nothing comes back, say "
        "you found nothing rather than guessing.",
        {
            "query": {"type": "string", "description": "what to look for"},
            "top_k": {"type": "integer", "default": 8},
        },
        ["query"],
    ),
```

Add to `TOOL_PERMISSION`: `"recall": "read",`. Add `"recall"` to the `UNTRUSTED_TOOLS` set (its output is the user's own text but may contain pasted/forwarded content). Do NOT add it to `MUTATING_TOOLS`.

Add the dispatch line in `execute`, before the final return:

```python
    if name == "recall":
        return await _recall(args.get("query", ""), int(args.get("top_k") or 8))
```

Add the handler:

```python
async def _recall(query, top_k):
    from core.database import SessionLocal
    from services import personal_index
    db = SessionLocal()
    try:
        hits = personal_index.search(db, query, k=int(top_k or 8))
        if not hits:
            return {"output": "no matches in your indexed data", "error": False}
        lines = []
        for h in hits:
            snip = (h.get("chunk") or "")[:200].replace("\n", " ")
            lines.append(f"[{h['score']}] {h['label']} ({h['link']}): {snip}")
        return {"output": "\n".join(lines), "error": False}
    finally:
        db.close()
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_recall_tools.py::test_recall_tool_finds_note -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/agent_tools.py tests/test_recall_tools.py
git commit -m "agent: recall tool over the personal index"
```

---

### Task B2: the `money_query` analytics tool

**Files:**
- Modify: `services/agent_tools.py` (schema, permission, dispatch, handler `_money_query`)
- Test: `tests/test_recall_tools.py` (add case)

**Interfaces:**
- Consumes: `Account(id,name,kind,currency,opening,archived)`, `Transaction(id,account_id,date,amount,category,payee,notes)`.
- Produces: tool `money_query` returning a read-only text summary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recall_tools.py (append)
from core.database import Account, Transaction
from datetime import date

def test_money_query_totals():
    db = _bind_memory_db()
    db.add(Account(id="ac", name="Checking", kind="checking", currency="$", opening=100.0)); db.commit()
    mo = date.today().strftime("%Y-%m")
    db.add(Transaction(id="t1", account_id="ac", date=f"{mo}-05", amount=-12.5, category="coffee", payee="Blue Bottle")); db.commit()
    db.add(Transaction(id="t2", account_id="ac", date=f"{mo}-06", amount=-7.5, category="coffee", payee="Local Cafe")); db.commit()
    out = asyncio.run(agent_tools.execute("money_query", {"query": "coffee"}))
    assert not out.get("error")
    assert "Checking" in out["output"]
    assert "coffee" in out["output"].lower()
    assert "20.0" in out["output"] or "20.00" in out["output"]  # matched 'coffee' spend
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_recall_tools.py::test_money_query_totals -q`
Expected: FAIL - `unknown tool: money_query`.

- [ ] **Step 3: Implement**

Add the schema to `APP_TOOL_DEFS`:

```python
    _tool(
        "money_query",
        "Read-only money analytics: account balances, net worth, this-month income/spend, spend by "
        "category, and the total matching a payee/category term. Use for 'how much did I spend / "
        "what's my balance' questions.",
        {"query": {"type": "string", "description": "optional payee/category to total, e.g. 'coffee'"}},
        [],
    ),
```

Add `"money_query": "read"` to `TOOL_PERMISSION` (not mutating, not untrusted - it's our own structured data). Add dispatch before the final return in `execute`:

```python
    if name == "money_query":
        return await _money_query(args.get("query", ""))
```

Add the handler:

```python
async def _money_query(query):
    from core.database import SessionLocal, Account, Transaction
    from datetime import date
    db = SessionLocal()
    try:
        accts = db.query(Account).filter_by(archived=False).all()
        txns = db.query(Transaction).all()
        bal = {a.id: (a.opening or 0.0) for a in accts}
        for t in txns:
            if t.account_id in bal:
                bal[t.account_id] += (t.amount or 0.0)
        lines = [f"{a.name} ({a.kind}): {a.currency}{bal[a.id]:.2f}" for a in accts]
        net = sum(bal.values())
        mo = date.today().strftime("%Y-%m")
        cats, inc, exp = {}, 0.0, 0.0
        for t in txns:
            if (t.date or "").startswith(mo):
                amt = t.amount or 0.0
                if amt >= 0:
                    inc += amt
                else:
                    exp += -amt
                    c = t.category or "uncategorized"
                    cats[c] = cats.get(c, 0.0) + (-amt)
        top = sorted(cats.items(), key=lambda x: -x[1])[:8]
        out = (
            "accounts:\n" + "\n".join(lines) +
            f"\nnet worth: {net:.2f}\n\nthis month ({mo}): income {inc:.2f}, spent {exp:.2f}\n" +
            "by category:\n" + "\n".join(f"  {c}: {v:.2f}" for c, v in top)
        )
        q = (query or "").lower().strip()
        if q:
            match = [t for t in txns if q in ((t.payee or "") + " " + (t.category or "") + " " + (t.notes or "")).lower()]
            spent = sum(-(t.amount or 0.0) for t in match if (t.amount or 0.0) < 0)
            out += f"\n\nmatching '{query}': {len(match)} txns, spent {spent:.2f}"
        return {"output": out, "error": False}
    finally:
        db.close()
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_recall_tools.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add services/agent_tools.py tests/test_recall_tools.py
git commit -m "agent: money_query read-only analytics tool"
```

---

# PHASE C - the control surface (settings)

### Task C1: settings keys + patch model

**Files:**
- Modify: `core/settings.py` (`_defaults`)
- Modify: `routes/settings.py` (`SettingsPatch`)
- Test: `tests/test_api_recall.py`

**Interfaces:**
- Consumes: `load_settings`/`save_settings`, the settings GET/PATCH endpoints.
- Produces: settings keys `pidx_enabled`, `pidx_mail`, `pidx_note`, `pidx_journal`, `pidx_contact`, `pidx_read`, `pidx_book` (default True), patchable + readable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_recall.py
from core.settings import load_settings, save_settings

def test_pidx_settings_defaults_and_patch():
    s = load_settings()
    for k in ("pidx_enabled", "pidx_mail", "pidx_note", "pidx_journal", "pidx_contact", "pidx_read", "pidx_book"):
        assert s.get(k) is True
    save_settings({"pidx_mail": False})
    assert load_settings().get("pidx_mail") is False
    save_settings({"pidx_mail": True})  # restore
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_api_recall.py::test_pidx_settings_defaults_and_patch -q`
Expected: FAIL - the keys aren't in `_defaults` so `.get` is `None`.

- [ ] **Step 3: Implement**

Add to the `_defaults` dict in `core/settings.py`:

```python
    "pidx_enabled": True,
    "pidx_mail": True,
    "pidx_note": True,
    "pidx_journal": True,
    "pidx_contact": True,
    "pidx_read": True,
    "pidx_book": True,
```

Add the optional fields to `SettingsPatch` in `routes/settings.py`:

```python
    pidx_enabled: bool | None = None
    pidx_mail: bool | None = None
    pidx_note: bool | None = None
    pidx_journal: bool | None = None
    pidx_contact: bool | None = None
    pidx_read: bool | None = None
    pidx_book: bool | None = None
```

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_api_recall.py::test_pidx_settings_defaults_and_patch -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/settings.py routes/settings.py tests/test_api_recall.py
git commit -m "recall settings: pidx_* keys + patch fields"
```

---

### Task C2: management endpoints (reindex / stats / clear)

**Files:**
- Create: `routes/recall.py`
- Modify: `app.py` (include the router)
- Test: `tests/test_api_recall.py` (add cases)

**Interfaces:**
- Consumes: `personal_index.reindex_source/reindex_all/stats/clear`, `SessionLocal`.
- Produces: `POST /api/recall/reindex`, `GET /api/recall/stats`, `POST /api/recall/clear`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_recall.py (append)
from fastapi.testclient import TestClient

def test_recall_endpoints():
    from app import app
    c = TestClient(app)
    r = c.get("/api/recall/stats")
    assert r.status_code == 200
    assert "by_kind" in r.json()
    r = c.post("/api/recall/reindex", json={})
    assert r.status_code == 200
    r = c.post("/api/recall/clear", json={})
    assert r.status_code == 200
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `python -m pytest tests/test_api_recall.py::test_recall_endpoints -q`
Expected: FAIL - 404 (routes not registered).

- [ ] **Step 3: Implement**

Create `routes/recall.py`:

```python
from fastapi import APIRouter
from pydantic import BaseModel

from core.database import SessionLocal
from services import personal_index

router = APIRouter(prefix="/api/recall")


class ReindexBody(BaseModel):
    kind: str | None = None


@router.get("/stats")
def stats():
    db = SessionLocal()
    try:
        return personal_index.stats(db)
    finally:
        db.close()


@router.post("/reindex")
def reindex(body: ReindexBody):
    db = SessionLocal()
    try:
        if body.kind:
            return {"kind": body.kind, "indexed": personal_index.reindex_source(db, body.kind)}
        return {"indexed": personal_index.reindex_all(db)}
    finally:
        db.close()


@router.post("/clear")
def clear():
    db = SessionLocal()
    try:
        return {"removed": personal_index.clear(db)}
    finally:
        db.close()
```

Register it in `app.py` next to the other `app.include_router(...)` calls:

```python
from routes import recall as recall_routes
app.include_router(recall_routes.router)
```

(match the existing router-import style in `app.py` - some are imported in the big `from routes import (...)` block; add `recall` there and `app.include_router(recall.router)` alongside the rest.)

- [ ] **Step 4: Run it, expect PASS**

Run: `python -m pytest tests/test_api_recall.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add routes/recall.py app.py tests/test_api_recall.py
git commit -m "recall api: reindex / stats / clear endpoints"
```

---

### Task C3: settings UI pane + cache bump

**Files:**
- Modify: `static/index.html` (nav item + `s-pane-recall`)
- Modify: `static/js/settings.js` (`loadRecallPane` + `_onPaneOpen` wiring)
- Modify: `static/sw.js` (cache bump)
- Test: `tests/pw_recall_settings.py`

**Interfaces:**
- Consumes: `_patchSetting(key, val)`, `_bindSwitch(el, getter, setter)`, `/api/recall/*`, `/api/settings`.
- Produces: a "recall" settings pane with master + per-source toggles, reindex button, stats line, clear button.

- [ ] **Step 1: Write the failing test**

```python
# tests/pw_recall_settings.py
import sys
from playwright.sync_api import sync_playwright

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8155"
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(f"http://aide.localhost:{port}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("body", "() => window._openSettings && window._openSettings('recall')")
        pg.wait_for_timeout(500)
        r["pane_renders"] = pg.eval_on_selector("#s-pane-recall", "el => !!el") or False
        r["master_toggle"] = pg.eval_on_selector("#s-pidx-enabled", "el => !!el") or False
        r["stats_shows"] = pg.eval_on_selector("#s-pidx-stats", "el => !!el") or False
        r["no_console_errors"] = len([e for e in errs if "favicon" not in e]) == 0
    for k, v in r.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(r.values()) else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it, expect FAIL**

Boot a throwaway server, then run it:

```bash
PORT=8155 AUTH_ENABLED=false ALLES_DATA=.tmp_recall_pw python app.py &  # then:
python tests/pw_recall_settings.py 8155
```
Expected: FAIL - `#s-pane-recall` doesn't exist yet.

- [ ] **Step 3: Implement**

In `static/index.html`, add a settings nav item (mirror an existing one in the settings nav list) pointing at pane `recall`, and add the pane (mirror the backup pane's `s-card` structure):

```html
<div class="s-pane" id="s-pane-recall">
  <div class="s-card">
    <div class="s-card-head">personal recall</div>
    <div class="s-card-body">
      <p style="font-size:0.75rem;color:var(--muted);margin-bottom:0.6rem">
        let aide search your own notes, journal, mail, contacts, saved articles and books.
        the vault is never indexed; the journal honours its lock. answering sends matched snippets
        to your chosen model - use a local model for fully offline recall.
      </p>
      <div class="s-toggle-row"><div><div class="s-toggle-label">enable recall index</div></div><div class="s-switch" id="s-pidx-enabled"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">mail</div></div><div class="s-switch" id="s-pidx-mail"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">notes</div></div><div class="s-switch" id="s-pidx-note"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">journal</div></div><div class="s-switch" id="s-pidx-journal"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">contacts</div></div><div class="s-switch" id="s-pidx-contact"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">read-later</div></div><div class="s-switch" id="s-pidx-read"></div></div>
      <div class="s-toggle-row"><div><div class="s-toggle-label">books</div></div><div class="s-switch" id="s-pidx-book"></div></div>
      <div id="s-pidx-stats" style="font-size:0.7rem;color:var(--muted);margin:0.6rem 0"></div>
      <button class="btn" id="s-pidx-reindex">reindex now</button>
      <button class="btn danger" id="s-pidx-clear">clear index</button>
    </div>
  </div>
</div>
```

In `static/js/settings.js`, add `loadRecallPane` and wire it into `_onPaneOpen`:

```javascript
async function loadRecallPane() {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const keys = ['enabled', 'mail', 'note', 'journal', 'contact', 'read', 'book'];
  for (const k of keys) {
    const el = document.getElementById('s-pidx-' + k);
    if (el) _bindSwitch(el, () => s['pidx_' + k] !== false, v => _patchSetting('pidx_' + k, v));
  }
  const stats = await fetch('/api/recall/stats').then(r => r.json()).catch(() => null);
  const el = document.getElementById('s-pidx-stats');
  if (el && stats) {
    const total = Object.values(stats.by_kind || {}).reduce((a, b) => a + b, 0);
    el.textContent = `${total} chunks indexed · ${stats.mail_pending || 0} mail bodies pending`;
  }
  const rb = document.getElementById('s-pidx-reindex');
  if (rb && !rb.dataset.bound) { rb.dataset.bound = '1'; rb.addEventListener('click', async () => { rb.disabled = true; await fetch('/api/recall/reindex', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); rb.disabled = false; loadRecallPane(); }); }
  const cb = document.getElementById('s-pidx-clear');
  if (cb && !cb.dataset.bound) { cb.dataset.bound = '1'; cb.addEventListener('click', async () => { if (!await _dlgConfirm('clear the recall index?')) return; await fetch('/api/recall/clear', { method: 'POST' }); loadRecallPane(); }); }
}
```

Add to `_onPaneOpen`: `if (name === 'recall') loadRecallPane();`

Bump cache stamps: `static/sw.js` `VERSION = 'v94'` + comment "personal recall settings", `STAMP = '120'`; `static/index.html` `style.css?v=120` and `const _v = '120'`.

- [ ] **Step 4: Run it, expect PASS**

```bash
PORT=8155 AUTH_ENABLED=false ALLES_DATA=.tmp_recall_pw python app.py &
python tests/pw_recall_settings.py 8155
```
Expected: PASS (4/4). Clean up: stop the server, `rm -rf .tmp_recall_pw`.

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/js/settings.js static/sw.js tests/pw_recall_settings.py
git commit -m "recall settings ui: pane, toggles, reindex/clear, stats + cache bump"
```

---

## Notes for the executor

- **Read each route before hooking it.** The line numbers above are from exploration; confirm the exact function names (`NoteBody`, `create_note`, etc.) and the commit points before editing. The hook is always: `index_record` after a create/update commit, `remove_record` after a delete commit, wrapped in `try/except`.
- **`_fetch_mail_body` (A6)** is the one place that depends on the real `services/mail.py` body-fetch signature - wire it to the same call the Mail route uses to open a single message, keep the `try/except -> ""` so imap errors never break the reconcile.
- **`memory_store._embed`** may be slow on first call (model load) or absent; tests rely on the jaccard fallback in `textindex`, so they pass with or without fastembed.
- after Phase C, do a clean-machine sanity boot (`ALLES_RELOAD=1`) and confirm `/api/recall/stats` returns and the settings pane works.
