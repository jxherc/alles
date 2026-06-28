"""money's 'current month / today' defaults must use LOCAL date.today() (like the rest of the app
+ money's own recurring poster), not datetime.utcnow() — otherwise budget/alert defaults are off by
a day/month near midnight on a non-UTC server. these patch money.date and would fail if the code
went back to utcnow() (which the patch can't touch)."""

from datetime import date as _date
from unittest import mock

from core.database import Account
from routes import money
from tests._client import ApiTest


class FakeDate(_date):
    @classmethod
    def today(cls):
        return _date(2026, 3, 15)  # a month that is NOT the real current month


class MoneyLocalDateTests(ApiTest):
    def test_ym_fallback_uses_local_today(self):
        with mock.patch.object(money, "date", FakeDate):
            self.assertEqual(money._ym(""), (2026, 3))
            self.assertEqual(money._ym("garbage"), (2026, 3))

    def test_alerts_default_month_is_local_today(self):
        db = self.db()
        db.add(Account(name="Checking", kind="checking", currency="$", opening=1000.0))
        db.commit()
        aid = db.query(Account).first().id
        db.close()
        # a big expense in march; only found if the default month resolves to the patched local today
        self.client.post("/api/money/transactions",
                         json={"account_id": aid, "date": "2026-03-20", "amount": -500.0, "payee": "rent"})
        with mock.patch.object(money, "date", FakeDate):
            r = self.client.get("/api/money/alerts").json()  # no ?month → default
        self.assertTrue(any(x["payee"] == "rent" for x in r["large_purchases"]))
