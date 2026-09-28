from datetime import date, timedelta
from unittest.mock import patch

from core.database import (
    Account,
    Budget,
    CachedMessage,
    FinanceLedgerState,
    JournalEntry,
    Subscription,
    Task,
    Transaction,
)
from services import actual_finance, signals
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class FinanceCutoverSignalsTests(ApiTest):
    def _cutover(self):
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                active_run_id="run-signals",
                actual_budget_id="budget-signals",
                actual_sync_id="sync-signals",
                legacy_read_only=True,
            )
        )
        db.commit()
        db.close()

    def test_cutover_does_not_surface_frozen_budget_or_balance_signals(self):
        db = self.db()
        account = Account(name="old account", opening=20, low_balance=100)
        db.add(account)
        db.flush()
        db.add_all(
            [
                Transaction(account_id=account.id, date=_iso(0), amount=-150, category="food"),
                Budget(category="food", limit_amt=100),
                Task(title="keep this task", due_date=_iso(0)),
            ]
        )
        db.commit()
        before = signals.gather(db, categories={"task", "budget", "account"})
        self.assertEqual({item["category"] for item in before}, {"task", "budget", "account"})
        db.close()

        self._cutover()
        db = self.db()
        after = signals.gather(db, categories={"task", "budget", "account"})
        self.assertEqual([item["category"] for item in after], ["task"])
        db.close()

    def test_today_uses_canonical_subscription_schedule_after_cutover(self):
        today = signals.calendar_today("UTC")
        db = self.db()
        old = Subscription(name="old plan", next_due=today.isoformat(), price=8, currency="CAD")
        db.add(old)
        db.commit()
        subscription_id = old.id
        db.close()
        self._cutover()

        schedule = {
            "id": subscription_id,
            "name": "current plan",
            "next_due": (today + timedelta(days=2)).isoformat(),
            "price": 12,
            "currency": "CAD",
            "active": True,
            "metadata": {},
        }
        with patch.object(actual_finance, "subscription_schedules", return_value=[schedule]):
            response = self.client.get(
                "/api/today", params={"date": today.isoformat(), "timezone": "UTC"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["renewing"],
            [
                {
                    "id": subscription_id,
                    "name": "current plan",
                    "in_days": 2,
                    "price": 12,
                    "currency": "CAD",
                }
            ],
        )

    def test_unavailable_canonical_schedule_never_replays_legacy_renewal(self):
        db = self.db()
        db.add(Subscription(name="stale plan", next_due=_iso(0), price=8))
        db.add(Task(title="keep this task", due_date=_iso(0)))
        db.commit()
        db.close()
        self._cutover()

        with patch.object(
            actual_finance,
            "subscription_schedules",
            side_effect=actual_finance.ActualFinanceUnavailable("offline"),
        ):
            db = self.db()
            unavailable = set()
            rows = signals.gather(db, categories={"sub", "task"}, unavailable=unavailable)
            db.close()
            response = self.client.get("/api/today")
        self.assertEqual([item["category"] for item in rows], ["task"])
        self.assertEqual(unavailable, {"subscriptions"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("subscriptions", response.json()["partial_sources"])
        self.assertEqual(response.json()["renewing"], [])

    def test_unreadable_authority_suppresses_only_finance_signals(self):
        db = self.db()
        db.add(Account(name="old account", opening=20, low_balance=100))
        db.add(Task(title="keep this task", due_date=_iso(0)))
        db.commit()
        unavailable = set()
        with patch.object(
            actual_finance,
            "is_canonical",
            side_effect=actual_finance.ActualFinanceError("state unavailable"),
        ):
            rows = signals.gather(db, categories={"account", "task"}, unavailable=unavailable)
        db.close()
        self.assertEqual([item["category"] for item in rows], ["task"])
        self.assertEqual(unavailable, {"finance"})


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
        defaults = dict(
            account_id="a1", folder="INBOX", seen=False, flagged=False, muted=False, date_ts=1000
        )
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
