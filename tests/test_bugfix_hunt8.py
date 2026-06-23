"""regression tests for the 10th bug-hunt iteration (correctness):
transfer legs (inter-account moves) must NOT be counted as spending in forecast/merchant stats,
consistent with routes/money._spending_by_cat.
"""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import forecast, money_stats

TODAY = datetime.date(2026, 6, 23)


class TransferExclusionTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.a = db.Account(name="chk", kind="checking", opening=0.0)
        self.s.add(self.a)
        self.s.commit()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _txn(self, d, amt, cat="groceries", payee="", transfer_id=""):
        self.s.add(
            db.Transaction(
                account_id=self.a.id,
                date=d,
                amount=amt,
                category=cat,
                payee=payee,
                transfer_id=transfer_id,
            )
        )
        self.s.commit()

    def test_category_averages_excludes_transfer(self):
        # a real expense in a baseline month + a transfer leg in the same month
        self._txn("2026-05-10", -100, "groceries")
        self._txn("2026-05-12", -200, "transfer", payee="-> savings", transfer_id="xfer1")
        avg = forecast.category_averages(self.s, months=3, as_of=TODAY)
        self.assertIn("groceries", avg)
        self.assertNotIn("transfer", avg)  # the transfer leg must not project as spending

    def test_new_merchants_excludes_transfer(self):
        self._txn("2026-06-10", -40, "shopping", payee="NEW STORE")
        self._txn("2026-06-12", -40, "transfer", payee="-> savings", transfer_id="xfer2")
        nm = money_stats.new_merchants(self.s, as_of=TODAY)
        merchants = {x["merchant"] for x in nm}
        self.assertIn("new store", merchants)
        self.assertFalse(
            any("saving" in m for m in merchants)
        )  # transfer dest not a "new merchant"


if __name__ == "__main__":
    unittest.main()
