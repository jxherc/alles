"""stage 2d - holdings price-fetch + price history + return. tests first (RED)."""

import datetime
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db
from services import price_fetch

T0 = datetime.datetime(2026, 6, 20, 9, 0, 0)
T1 = datetime.datetime(2026, 6, 23, 9, 0, 0)


class PriceFetchTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def _hold(self, sym, qty=1.0, cost=10.0, price=0.0):
        h = db.Holding(symbol=sym, qty=qty, cost_basis=cost, price=price)
        self.s.add(h)
        self.s.commit()
        return h

    def test_refresh_updates_price(self):
        h = self._hold("AAPL", price=100.0)
        out = price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 150.0})
        self.s.refresh(h)
        self.assertEqual(h.price, 150.0)
        self.assertEqual(out["updated"], 1)

    def test_refresh_writes_history(self):
        self._hold("AAPL", price=100.0)
        price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 150.0}, now=T1)
        rows = self.s.query(db.PriceHistory).filter_by(symbol="AAPL").all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].price, 150.0)
        self.assertEqual(rows[0].ts, T1)

    def test_refresh_skips_unpriced_symbol(self):
        h = self._hold("ZZZZ", price=42.0)
        out = price_fetch.refresh(self.s, fetcher=lambda syms: {})  # fetcher returns nothing
        self.s.refresh(h)
        self.assertEqual(h.price, 42.0)  # untouched
        self.assertEqual(out["updated"], 0)
        self.assertEqual(self.s.query(db.PriceHistory).count(), 0)

    def test_refresh_only_queries_held_symbols(self):
        self._hold("AAPL")
        self._hold("MSFT")
        seen = {}

        def fetch(syms):
            seen["syms"] = sorted(syms)
            return {}

        price_fetch.refresh(self.s, fetcher=fetch)
        self.assertEqual(seen["syms"], ["AAPL", "MSFT"])

    def test_refresh_dedupes_symbols(self):
        self._hold("AAPL", qty=1)
        self._hold("AAPL", qty=2)  # two lots, same symbol
        seen = {}

        def fetch(syms):
            seen["syms"] = list(syms)
            return {"AAPL": 200.0}

        out = price_fetch.refresh(self.s, fetcher=fetch)
        self.assertEqual(len(seen["syms"]), 1)  # asked once
        self.assertEqual(out["updated"], 2)  # both lots repriced

    def test_refresh_empty_portfolio(self):
        out = price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 1.0})
        self.assertEqual(out["updated"], 0)

    def test_history_returns_recent_first(self):
        self._hold("AAPL")
        price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 100.0}, now=T0)
        price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 120.0}, now=T1)
        hist = price_fetch.history(self.s, "AAPL")
        self.assertEqual([r["price"] for r in hist], [120.0, 100.0])

    def test_history_limit(self):
        self._hold("AAPL")
        for i, p in enumerate((10.0, 20.0, 30.0)):
            price_fetch.refresh(
                self.s,
                fetcher=lambda syms, _p=p: {"AAPL": _p},
                now=T0 + datetime.timedelta(days=i),
            )
        self.assertEqual(len(price_fetch.history(self.s, "AAPL", limit=2)), 2)

    def test_return_since_first(self):
        self._hold("AAPL")
        price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 100.0}, now=T0)
        price_fetch.refresh(self.s, fetcher=lambda syms: {"AAPL": 125.0}, now=T1)
        self.assertEqual(price_fetch.return_since_first(self.s, "AAPL"), 25.0)

    def test_return_since_first_no_history(self):
        self.assertIsNone(price_fetch.return_since_first(self.s, "NOPE"))


class RefreshEndpointTests(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        from fastapi.testclient import TestClient

        from app import app

        self.c = TestClient(app)
        s = db.SessionLocal()
        s.add(db.Holding(symbol="AAPL", qty=1, cost_basis=10.0, price=10.0))
        s.commit()
        s.close()

    def tearDown(self):
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()

    def test_refresh_endpoint_runs(self):
        # no network in tests -> default fetcher best-effort returns {}; endpoint must still 200
        r = self.c.post("/api/money/holdings/refresh")
        self.assertEqual(r.status_code, 200)
        self.assertIn("updated", r.json())

    def test_history_endpoint(self):
        s = db.SessionLocal()
        price_fetch.refresh(s, fetcher=lambda syms: {"AAPL": 99.0}, now=T1)
        s.close()
        r = self.c.get("/api/money/holdings/AAPL/history")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(row["price"] == 99.0 for row in r.json()["history"]))


if __name__ == "__main__":
    unittest.main()
