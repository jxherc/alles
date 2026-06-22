from datetime import date, timedelta

from core.database import (
    Account,
    Budget,
    CachedMessage,
    JournalEntry,
    Transaction,
)
from services import signals
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class BudgetSignalTests(ApiTest):
    def test_over_budget(self):
        d = self.db()
        a = Account(name="checking", opening=0.0, currency="$")
        d.add(a)
        d.commit()
        d.add(Transaction(account_id=a.id, date=_iso(0), amount=-120.0, category="food"))
        d.add(Budget(category="food", limit_amt=100.0))
        d.commit()
        d.close()
        sigs = [s for s in signals.gather(self.db(), categories={"budget"})]
        self.assertEqual(len(sigs), 1)
        self.assertTrue(sigs[0]["key"].startswith("budget_over:food:"))
        self.assertEqual(sigs[0]["data"]["spent"], 120.0)

    def test_under_budget_excluded(self):
        d = self.db()
        a = Account(name="checking", opening=0.0, currency="$")
        d.add(a)
        d.commit()
        d.add(Transaction(account_id=a.id, date=_iso(0), amount=-40.0, category="food"))
        d.add(Budget(category="food", limit_amt=100.0))
        d.commit()
        d.close()
        self.assertEqual(signals.gather(self.db(), categories={"budget"}), [])


class LowBalanceTests(ApiTest):
    def test_low_balance_flagged(self):
        d = self.db()
        d.add(Account(name="wallet", opening=20.0, currency="$", low_balance=100.0))
        d.commit()
        d.close()
        sigs = signals.gather(self.db(), categories={"account"})
        self.assertEqual(len(sigs), 1)
        self.assertTrue(sigs[0]["key"].startswith("account_low:"))

    def test_healthy_balance_excluded(self):
        d = self.db()
        d.add(Account(name="wallet", opening=500.0, currency="$", low_balance=100.0))
        d.commit()
        d.close()
        self.assertEqual(signals.gather(self.db(), categories={"account"}), [])

    def test_no_threshold_excluded(self):
        d = self.db()
        d.add(Account(name="wallet", opening=5.0, currency="$", low_balance=0.0))
        d.commit()
        d.close()
        self.assertEqual(signals.gather(self.db(), categories={"account"}), [])


class MailSignalTests(ApiTest):
    def _msg(self, **kw):
        d = self.db()
        defaults = dict(account_id="a1", folder="INBOX", seen=False, flagged=False,
                        muted=False, date_ts=1000)
        defaults.update(kw)
        d.add(CachedMessage(**defaults))
        d.commit()
        d.close()

    def test_flagged_unread_surfaces(self):
        self._msg(uid="1", sender="Boss <boss@x.com>", subject="urgent", flagged=True)
        sigs = signals.gather(self.db(), categories={"mail"})
        self.assertEqual(len(sigs), 1)
        self.assertIn("flagged", sigs[0]["title"])

    def test_plain_unread_excluded(self):
        self._msg(uid="2", sender="rando <rando@nowhere.test>", subject="sale", flagged=False)
        self.assertEqual(signals.gather(self.db(), categories={"mail"}), [])

    def test_read_excluded(self):
        self._msg(uid="3", sender="Boss <boss@x.com>", subject="x", flagged=True, seen=True)
        self.assertEqual(signals.gather(self.db(), categories={"mail"}), [])


class JournalStaleTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._orig = signals._journal_locked
        signals._journal_locked = lambda: False

    def tearDown(self):
        signals._journal_locked = self._orig
        super().tearDown()

    def test_stale_journal(self):
        d = self.db()
        d.add(JournalEntry(date=_iso(-5), content="old"))
        d.commit()
        d.close()
        sigs = signals.gather(self.db(), categories={"journal"})
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["data"]["gap_days"], 5)

    def test_recent_journal_excluded(self):
        d = self.db()
        d.add(JournalEntry(date=_iso(0), content="today"))
        d.commit()
        d.close()
        self.assertEqual(signals.gather(self.db(), categories={"journal"}), [])

    def test_no_entries_excluded(self):
        self.assertEqual(signals.gather(self.db(), categories={"journal"}), [])

    def test_locked_journal_excluded(self):
        signals._journal_locked = lambda: True
        d = self.db()
        d.add(JournalEntry(date=_iso(-9), content="old"))
        d.commit()
        d.close()
        self.assertEqual(signals.gather(self.db(), categories={"journal"}), [])
