from datetime import UTC, datetime, timedelta
from unittest import mock

from core.database import Account, FinanceLedgerState, SubPayment, Subscription, Task, Transaction
from services import actual_finance
from tests._client import ApiTest


class TimelineFinanceCutoverTests(ApiTest):
    def _cutover(self):
        db = self.db()
        db.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                active_run_id="run-timeline",
                actual_budget_id="budget-timeline",
                actual_sync_id="sync-timeline",
                base_currency_code="CAD",
                legacy_read_only=True,
            )
        )
        db.commit()
        db.close()

    def test_canonical_events_replace_frozen_money_and_renewal(self):
        today = datetime.now(UTC).date().isoformat()
        db = self.db()
        account = Account(name="old account", opening=0)
        subscription = Subscription(
            name="old plan",
            price=9,
            next_due=(datetime.now(UTC).date() + timedelta(days=30)).isoformat(),
            last_posted_due=today,
        )
        db.add_all([account, subscription])
        db.flush()
        db.add(Transaction(account_id=account.id, date=today, amount=-9, payee="old charge"))
        sub_id = subscription.id
        db.commit()
        db.close()
        self._cutover()

        snapshot = {"transactions": [{"id": "current"}], "schedules": [{"id": "current"}]}
        current = {"id": "current-charge", "date": today, "amount": -12.5, "payee": "new charge"}
        schedule = {"id": sub_id, "name": "new plan", "currency": "CAD", "price": 12.5}
        payment = {
            "id": "actual-payment:new",
            "date": today,
            "amount": 12.5,
            "txn_id": "current-charge",
            "source_payment_id": "",
        }
        with (
            mock.patch.object(actual_finance, "inspect", return_value=snapshot) as inspect,
            mock.patch.object(
                actual_finance, "transactions", return_value=[current]
            ) as transactions,
            mock.patch.object(
                actual_finance, "subscription_schedules", return_value=[schedule]
            ) as schedules,
            mock.patch.object(
                actual_finance, "subscription_payments", return_value={sub_id: [payment]}
            ) as payments,
        ):
            response = self.client.get("/api/timeline", params={"types": "money,sub", "days": 7})

        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()["events"]
        self.assertEqual([event["title"] for event in events], ["new charge", "new plan renewed"])
        self.assertEqual([event["id"] for event in events], ["current-charge", sub_id])
        self.assertEqual(response.json()["partial_sources"], [])
        inspect.assert_called_once()
        transactions.assert_called_once_with(mock.ANY, actual=snapshot)
        schedules.assert_called_once_with(mock.ANY, actual=snapshot)
        payments.assert_called_once_with(mock.ANY, actual=snapshot)

    def test_historical_payment_sidecar_is_preserved_without_duplicate(self):
        today = datetime.now(UTC).date().isoformat()
        db = self.db()
        subscription = Subscription(
            name="historic plan", price=8, next_due=today, last_posted_due=today
        )
        db.add(subscription)
        db.flush()
        sidecar = SubPayment(sub_id=subscription.id, date=today, amount=8)
        unmatched = SubPayment(
            sub_id=subscription.id,
            date=(datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
            amount=7,
            base_amount_text="7",
            base_currency_code="CAD",
        )
        db.add_all([sidecar, unmatched])
        db.commit()
        sub_id, sidecar_id = subscription.id, sidecar.id
        db.close()
        self._cutover()

        schedule = {"id": sub_id, "name": "current plan", "currency": "CAD", "price": 10}
        canonical = [
            {
                "id": "actual-payment:old",
                "date": today,
                "amount": 8,
                "txn_id": "old-txn",
                "source_payment_id": sidecar_id,
            },
            {
                "id": "actual-payment:new",
                "date": today,
                "amount": 10,
                "txn_id": "new-txn",
                "source_payment_id": "",
            },
        ]
        with (
            mock.patch.object(actual_finance, "inspect", return_value={"schedules": [schedule]}),
            mock.patch.object(actual_finance, "subscription_schedules", return_value=[schedule]),
            mock.patch.object(
                actual_finance, "subscription_payments", return_value={sub_id: canonical}
            ),
        ):
            response = self.client.get("/api/timeline", params={"types": "sub", "days": 7})
        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()["events"]
        self.assertEqual(len(events), 3)
        self.assertTrue(all(event["title"] == "current plan renewed" for event in events))
        self.assertEqual({event["subtitle"] for event in events}, {"CAD 7", "CAD 8", "CAD 10"})

    def test_missing_canonical_schedule_keeps_current_money_visible(self):
        today = datetime.now(UTC).date().isoformat()
        self._cutover()
        snapshot = {"transactions": [{"id": "current"}]}
        with (
            mock.patch.object(actual_finance, "inspect", return_value=snapshot),
            mock.patch.object(
                actual_finance,
                "transactions",
                return_value=[
                    {"id": "current", "date": today, "payee": "current charge", "amount": -3}
                ],
            ),
            mock.patch.object(
                actual_finance,
                "subscription_schedules",
                side_effect=actual_finance.ActualFinanceUnavailable("offline"),
            ),
        ):
            response = self.client.get("/api/timeline", params={"types": "money,sub"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [event["title"] for event in response.json()["events"]], ["current charge"]
        )
        self.assertEqual(response.json()["partial_sources"], ["sub"])

    def test_finance_outage_keeps_other_activity_and_marks_partial_totals(self):
        today = datetime.now(UTC).date().isoformat()
        db = self.db()
        account = Account(name="old account", opening=0)
        db.add_all([account, Task(title="keep this task", completed_at=datetime.now(UTC))])
        db.flush()
        db.add(Transaction(account_id=account.id, date=today, amount=-9, payee="old charge"))
        db.commit()
        db.close()
        self._cutover()

        with mock.patch.object(
            actual_finance,
            "inspect",
            side_effect=actual_finance.ActualFinanceUnavailable("offline"),
        ):
            feed = self.client.get("/api/timeline", params={"types": "task,money,sub"})
            summary = self.client.get("/api/timeline/summary", params={"types": "task,money,sub"})
        self.assertEqual(feed.status_code, 200, feed.text)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual([event["type"] for event in feed.json()["events"]], ["task"])
        self.assertEqual(feed.json()["partial_sources"], ["money", "sub"])
        self.assertEqual(summary.json()["total"], 1)
        self.assertEqual(summary.json()["partial_sources"], ["money", "sub"])

    def test_unreadable_authority_never_replays_frozen_money(self):
        db = self.db()
        account = Account(name="old account", opening=0)
        db.add(account)
        db.flush()
        db.add(
            Transaction(
                account_id=account.id,
                date=datetime.now(UTC).date().isoformat(),
                amount=-9,
                payee="old charge",
            )
        )
        db.commit()
        db.close()

        with mock.patch.object(
            actual_finance,
            "is_canonical",
            side_effect=actual_finance.ActualFinanceError("authority unavailable"),
        ):
            response = self.client.get("/api/timeline", params={"types": "money"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["events"], [])
        self.assertEqual(response.json()["partial_sources"], ["money"])
