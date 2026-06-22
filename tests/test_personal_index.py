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
