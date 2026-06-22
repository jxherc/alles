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
    # create returns _fmt(n) which is a dict
    created = R.create_note(R.NoteBody(title="ski trip", content="booked the cabin"), db=db)
    nid = created["id"]
    assert pix.search(db, "cabin booked", kinds=["note"], k=5), "note not indexed after create"
    R.update_note(nid, R.NoteBody(title="ski trip", content="cancelled the cabin"), db=db)
    assert pix.search(db, "cancelled", kinds=["note"], k=5), "note not reindexed after update"
    R.delete_note(nid, db=db)
    assert not pix.search(db, "ski trip", kinds=["note"], k=5), "note still in index after delete"
