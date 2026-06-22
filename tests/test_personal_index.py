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
