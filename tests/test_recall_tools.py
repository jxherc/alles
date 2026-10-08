import asyncio
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as DB
from core.database import Account, Base, Transaction
from services import agent_tools, vault_md
from services import personal_index as pix

# these tests rebind the GLOBAL DB.SessionLocal so the agent tools (which open their own
# SessionLocal internally) hit an in-memory db. capture the real one at import and put it
# back after every test, or it leaks and breaks every later test that opens a session.
_ORIG_SESSIONLOCAL = DB.SessionLocal


class RecallToolsTests(unittest.TestCase):
    def tearDown(self):
        DB.SessionLocal = _ORIG_SESSIONLOCAL
        if hasattr(self, "db"):
            self.db.close()
        if hasattr(self, "eng"):
            self.eng.dispose()

    def _bind_memory_db(self):
        self.eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.eng)
        DB.SessionLocal = sessionmaker(bind=self.eng)  # tools open their own SessionLocal
        self.db = DB.SessionLocal()
        return self.db

    def test_recall_tool_finds_note(self):
        from services import notes_vault

        tmp = tempfile.mkdtemp()
        orig_vault = vault_md.vault_dir
        vault_md.vault_dir = lambda: Path(tmp).resolve()
        try:
            db = self._bind_memory_db()
            n = notes_vault.create(title="garage code", content="the side door code is 4417")
            pix.index_record(db, "note", n["id"])
            out = asyncio.run(agent_tools.execute("recall", {"query": "garage door code"}))
            self.assertFalse(out.get("error"))
            self.assertIn("garage code", out["output"])
        finally:
            vault_md.vault_dir = orig_vault
            shutil.rmtree(tmp, ignore_errors=True)

    def test_money_query_totals(self):
        db = self._bind_memory_db()
        db.add(Account(id="ac", name="Checking", kind="checking", currency="$", opening=100.0))
        db.commit()
        mo = date.today().strftime("%Y-%m")
        db.add(
            Transaction(
                id="t1",
                account_id="ac",
                date=f"{mo}-05",
                amount=-12.5,
                category="coffee",
                payee="Blue Bottle",
            )
        )
        db.commit()
        db.add(
            Transaction(
                id="t2",
                account_id="ac",
                date=f"{mo}-06",
                amount=-7.5,
                category="coffee",
                payee="Local Cafe",
            )
        )
        db.commit()
        out = asyncio.run(agent_tools.execute("money_query", {"query": "coffee"}))
        self.assertFalse(out.get("error"))
        self.assertIn("Checking", out["output"])
        self.assertIn("coffee", out["output"].lower())
        self.assertTrue(
            "20.0" in out["output"] or "20.00" in out["output"]
        )  # matched 'coffee' spend


if __name__ == "__main__":
    unittest.main()
