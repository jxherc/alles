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

from core.database import JournalEntry, Contact, ContactField, ReadItem, Book

def test_journal_contact_read_book(monkeypatch):
    import services.personal_index as pixmod
    monkeypatch.setattr(pixmod, "_journal_locked", lambda: False)
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

import services.personal_index as pixmod

def test_journal_lock_blocks_and_drops(monkeypatch):
    db = _db()
    e = JournalEntry(id="j9", date="2026-01-01", content="secret thoughts")
    db.add(e); db.commit()
    # index while unlocked
    monkeypatch.setattr(pixmod, "_journal_locked", lambda: False)
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

from core.database import IndexChunk, CachedMessage

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
