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
