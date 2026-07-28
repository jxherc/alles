import asyncio
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from core.database import CalendarEvent, DayEvent, FinanceLedgerState, Subscription
from routes.days import check_day_events
from routes.subscriptions import check_renewals
from services import cal_notify
from tests._client import ApiTest


class PushDeliveryBookkeepingTests(ApiTest):
    @staticmethod
    def _run_with_delivery(job, delivered):
        async def fake_broadcast(payload):
            return {
                "sent": delivered,
                "failed": 0,
                "uncertain": 0,
                "pruned": 0,
                "total": delivered,
            }

        with mock.patch("routes.push.broadcast_result", fake_broadcast):
            asyncio.run(job())

    @staticmethod
    def _run_uncertain(job, calls):
        async def fake_broadcast(payload):
            calls.append(payload)
            return {"sent": 0, "failed": 0, "uncertain": 1, "pruned": 0, "total": 1}

        with mock.patch("routes.push.broadcast_result", fake_broadcast):
            asyncio.run(job())

    def test_subscription_marker_waits_for_confirmed_delivery(self):
        today = date.today().isoformat()
        d = self.db()
        sub = Subscription(name="alles", next_due=today, remind_days=1)
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()

        self._run_with_delivery(check_renewals, delivered=0)
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, "")
        d.close()

        self._run_with_delivery(check_renewals, delivered=1)
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, today)
        d.close()

    def test_day_marker_waits_for_confirmed_delivery(self):
        today = date.today().isoformat()
        d = self.db()
        event = DayEvent(name="launch", date=today, notify_days=1)
        d.add(event)
        d.commit()
        eid = event.id
        d.close()

        self._run_with_delivery(check_day_events, delivered=0)
        d = self.db()
        self.assertEqual(d.get(DayEvent, eid).last_notified, "")
        d.close()

        self._run_with_delivery(check_day_events, delivered=1)
        d = self.db()
        self.assertEqual(d.get(DayEvent, eid).last_notified, today)
        d.close()

    def test_interrupted_pending_day_delivery_retries_with_the_same_occurrence(self):
        today = date.today().isoformat()
        d = self.db()
        event = DayEvent(
            name="interrupted launch",
            date=today,
            notify_days=1,
            last_notified=f"pending:{today}",
        )
        d.add(event)
        d.commit()
        eid = event.id
        d.close()

        self._run_with_delivery(check_day_events, delivered=1)
        d = self.db()
        self.assertEqual(d.get(DayEvent, eid).last_notified, today)
        d.close()

    def test_live_pending_day_delivery_lease_is_not_sent_twice(self):
        today = date.today().isoformat()
        d = self.db()
        event = DayEvent(
            name="live launch",
            date=today,
            notify_days=1,
            last_notified=f"pending:{today}:{int(time.time())}",
        )
        d.add(event)
        d.commit()
        eid = event.id
        d.close()

        calls = []
        self._run_uncertain(check_day_events, calls)
        self.assertEqual(calls, [])
        d = self.db()
        self.assertTrue(d.get(DayEvent, eid).last_notified.startswith(f"pending:{today}:"))
        d.close()

    def test_uncertain_subscription_delivery_is_not_retried(self):
        today = date.today().isoformat()
        d = self.db()
        sub = Subscription(name="alles", next_due=today, remind_days=1)
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()

        calls = []
        self._run_uncertain(check_renewals, calls)
        self._run_uncertain(check_renewals, calls)
        self.assertEqual(len(calls), 1)
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, f"uncertain:{today}")
        d.close()

    def test_legacy_mode_recovers_an_interrupted_pending_delivery_without_retrying_it(self):
        today = date.today().isoformat()
        d = self.db()
        sub = Subscription(
            name="interrupted legacy renewal",
            next_due=today,
            remind_days=1,
            last_notified_due=f"pending:{today}",
        )
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()

        calls = []
        self._run_uncertain(check_renewals, calls)
        self.assertEqual(calls, [])
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, f"uncertain:{today}")
        d.close()

    def test_cutover_reconciles_pending_subscription_delivery_without_using_frozen_schedule(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                base_currency_code="CAD",
                active_run_id="run-1",
                actual_budget_id="budget-1",
                legacy_read_only=True,
            )
        )
        sub = Subscription(
            name="cutover renewal",
            price=1,
            currency="CAD",
            next_due=today,
            remind_days=1,
            last_notified_due=f"pending:{today}",
            original_price_text="1",
            original_currency_code="CAD",
            base_price_text="1",
            base_currency_code="CAD",
            fx_rate_text="1",
            fx_source="legacy_identity",
        )
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()

        canonical = {
            "id": sid,
            "actual_id": "actual-schedule",
            "name": "cutover renewal",
            "price": 1,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": today,
            "active": True,
            "account_id": "",
            "metadata": {},
        }
        calls = []
        with mock.patch(
            "routes.subscriptions.actual_finance.subscription_schedules",
            return_value=[canonical],
        ):
            self._run_uncertain(check_renewals, calls)
        self.assertEqual(calls, [])
        with (
            mock.patch(
                "routes.subscriptions.actual_finance.subscription_schedules",
                return_value=[canonical],
            ),
            mock.patch(
                "routes.subscriptions.actual_finance.subscription_payments", return_value={}
            ),
        ):
            listed = self.client.get("/api/subscriptions").json()["subscriptions"][0]
        self.assertEqual(listed["notification_delivery"], {"state": "uncertain", "due": today})

        with mock.patch(
            "routes.subscriptions.actual_finance.subscription_schedules",
            return_value=[canonical],
        ):
            self._run_uncertain(check_renewals, calls)
        self.assertEqual(calls, [])
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, f"uncertain:{today}")
        d.close()

    def test_canonical_subscription_schedule_still_sends_a_claimed_renewal(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(
            FinanceLedgerState(
                id="primary",
                mode="actual",
                base_currency_code="CAD",
                active_run_id="run-1",
                actual_budget_id="budget-1",
                legacy_read_only=True,
            )
        )
        sub = Subscription(
            name="canonical renewal",
            price=3,
            currency="CAD",
            next_due=today,
            remind_days=1,
            original_price_text="3",
            original_currency_code="CAD",
            base_price_text="3",
            base_currency_code="CAD",
            fx_rate_text="1",
            fx_source="legacy_identity",
        )
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()
        canonical = {
            "id": sid,
            "actual_id": "actual-schedule",
            "name": "canonical renewal",
            "price": 3,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": today,
            "active": True,
            "account_id": "",
            "metadata": {},
        }
        with mock.patch(
            "routes.subscriptions.actual_finance.subscription_schedules",
            return_value=[canonical],
        ):
            self._run_with_delivery(check_renewals, delivered=1)
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, today)
        d.close()

    def test_subscription_delivery_does_not_finalize_across_an_authority_cutover(self):
        today = date.today().isoformat()
        d = self.db()
        state = d.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary")
            d.add(state)
        state.mode = "alles"
        state.legacy_read_only = False
        sub = Subscription(
            name="cutover race",
            price=3,
            currency="CAD",
            next_due=today,
            remind_days=1,
            original_price_text="3",
            original_currency_code="CAD",
            base_price_text="3",
            base_currency_code="CAD",
            fx_rate_text="1",
        )
        d.add(sub)
        d.commit()
        sid = sub.id
        d.close()

        async def cut_over_after_claim(_payload):
            other = self.db()
            other_state = other.get(FinanceLedgerState, "primary")
            other_state.mode = "actual"
            other_state.legacy_read_only = True
            other_state.active_run_id = "run-1"
            other_state.actual_budget_id = "budget-1"
            other.commit()
            other.close()
            return {"sent": 1, "failed": 0, "uncertain": 0, "pruned": 0, "total": 1}

        with mock.patch("routes.push.broadcast_result", cut_over_after_claim):
            asyncio.run(check_renewals())

        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, f"pending:{today}")
        d.close()
        canonical = {
            "id": sid,
            "actual_id": "actual-schedule",
            "name": "cutover race",
            "price": 3,
            "currency": "CAD",
            "cycle": "monthly",
            "cycle_days": 30,
            "next_due": today,
            "active": True,
            "account_id": "",
            "metadata": {},
        }
        provider = mock.AsyncMock()
        with (
            mock.patch(
                "routes.subscriptions.actual_finance.subscription_schedules",
                return_value=[canonical],
            ),
            mock.patch("routes.push.broadcast_result", provider),
        ):
            asyncio.run(check_renewals())
        provider.assert_not_awaited()
        d = self.db()
        self.assertEqual(d.get(Subscription, sid).last_notified_due, f"uncertain:{today}")
        d.close()

    def test_subscription_route_write_and_list_advancement_hold_authority_lock(self):
        class TrackingLock:
            depth = 0

            @property
            def held(self):
                return self.depth > 0

            def __enter__(self):
                self.depth += 1

            def __exit__(self, *_args):
                self.depth -= 1

        lock = TrackingLock()

        def validate(_body):
            self.assertTrue(lock.held)

        def roll(*_args):
            self.assertTrue(lock.held)
            return False

        with (
            mock.patch("routes.subscriptions.actual_finance.AUTHORITY_LOCK", lock),
            mock.patch("routes.subscriptions._validate", side_effect=validate),
            mock.patch("routes.subscriptions._roll_and_post", side_effect=roll),
        ):
            created = self.client.post(
                "/api/subscriptions",
                json={
                    "name": "serialized",
                    "price": 1,
                    "currency": "CAD",
                    "next_due": "2026-08-01",
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            listed = self.client.get("/api/subscriptions")
            self.assertEqual(listed.status_code, 200, listed.text)

    def test_subscription_renewal_mutation_holds_the_actual_authority_lock(self):
        d = self.db()
        d.add(
            Subscription(
                name="locked renewal",
                next_due=date.today().isoformat(),
                remind_days=0,
                active=True,
            )
        )
        d.commit()
        d.close()

        class TrackingLock:
            held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, *_args):
                self.held = False

        lock = TrackingLock()

        def roll(*_args):
            self.assertTrue(lock.held)
            return False

        with (
            mock.patch("routes.subscriptions.actual_finance.AUTHORITY_LOCK", lock),
            mock.patch("routes.subscriptions._roll_and_post", side_effect=roll),
        ):
            asyncio.run(check_renewals())

    def test_uncertain_day_delivery_is_not_retried(self):
        today = date.today().isoformat()
        d = self.db()
        event = DayEvent(name="launch", date=today, notify_days=1)
        d.add(event)
        d.commit()
        eid = event.id
        d.close()

        calls = []
        self._run_uncertain(check_day_events, calls)
        self._run_uncertain(check_day_events, calls)
        self.assertEqual(len(calls), 1)
        d = self.db()
        self.assertEqual(d.get(DayEvent, eid).last_notified, f"uncertain:{today}")
        d.close()

    def test_calendar_marker_waits_for_confirmed_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_fires = cal_notify._FIRES
            old_fired = cal_notify._fired
            old_path = cal_notify._fired_path
            cal_notify._FIRES = Path(tmp) / "cal_fires.json"
            cal_notify._fired = None
            cal_notify._fired_path = None
            try:
                start = datetime.now().replace(microsecond=0)
                d = self.db()
                event = CalendarEvent(
                    title="standup",
                    start_dt=start.isoformat(),
                    reminders="[0]",
                )
                d.add(event)
                d.commit()
                eid = event.id
                d.close()
                key = f"{eid}|{start.date().isoformat()}|0"

                self._run_with_delivery(cal_notify.fire_due, delivered=0)
                self.assertNotIn(key, cal_notify._load())

                self._run_with_delivery(cal_notify.fire_due, delivered=1)
                self.assertIn(key, cal_notify._load())
            finally:
                cal_notify._FIRES = old_fires
                cal_notify._fired = old_fired
                cal_notify._fired_path = old_path

    def test_uncertain_calendar_delivery_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_fires = cal_notify._FIRES
            old_fired = cal_notify._fired
            old_path = cal_notify._fired_path
            cal_notify._FIRES = Path(tmp) / "cal_fires.json"
            cal_notify._fired = None
            cal_notify._fired_path = None
            try:
                start = datetime.now().replace(microsecond=0)
                d = self.db()
                event = CalendarEvent(title="standup", start_dt=start.isoformat(), reminders="[0]")
                d.add(event)
                d.commit()
                eid = event.id
                d.close()
                key = f"{eid}|{start.date().isoformat()}|0"

                calls = []
                self._run_uncertain(cal_notify.fire_due, calls)
                self._run_uncertain(cal_notify.fire_due, calls)
                self.assertEqual(len(calls), 1)
                self.assertIn(f"uncertain:{key}", cal_notify._load())
            finally:
                cal_notify._FIRES = old_fires
                cal_notify._fired = old_fired
                cal_notify._fired_path = old_path
