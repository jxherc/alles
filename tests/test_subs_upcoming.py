from datetime import date, timedelta

from core.database import FinanceLedgerState, Subscription
from tests._client import ApiTest


def _due_in(n):
    return (date.today() + timedelta(days=n)).isoformat()


class SubUpcomingTests(ApiTest):
    def _seed(self, **kw):
        d = self.db()
        defaults = dict(name="X", price=5.0, currency="CAD", cycle="monthly", active=True)
        defaults.update(kw)
        defaults.setdefault("base_price_text", str(defaults["price"]))
        defaults.setdefault("base_currency_code", defaults["currency"])
        defaults.setdefault("fx_rate_text", "1")
        defaults.setdefault("fx_source", "test_identity")
        d.add(Subscription(**defaults))
        d.commit()
        d.close()

    def _get(self, days=None):
        params = {} if days is None else {"days": days}
        return self.client.get("/api/subscriptions/upcoming", params=params).json()

    def test_includes_due_within_window(self):
        self._seed(name="Soon", next_due=_due_in(3))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Soon", names)

    def test_excludes_beyond_window(self):
        self._seed(name="Far", next_due=_due_in(20))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Far", names)

    def test_excludes_paused(self):
        self._seed(name="Paused", next_due=_due_in(2), active=False)
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Paused", names)

    def test_excludes_overdue(self):
        self._seed(name="Overdue", next_due=_due_in(-3))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Overdue", names)

    def test_today_included(self):
        self._seed(name="Today", next_due=_due_in(0))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Today", names)

    def test_boundary_inclusive(self):
        self._seed(name="Edge", next_due=_due_in(7))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Edge", names)

    def test_sorted_soonest_first(self):
        self._seed(name="B", next_due=_due_in(5))
        self._seed(name="A", next_due=_due_in(1))
        names = [i["name"] for i in self._get(14)["items"]]
        self.assertEqual(names[:2], ["A", "B"])

    def test_total_sums_price(self):
        self._seed(name="One", price=10.0, next_due=_due_in(1))
        self._seed(name="Two", price=2.5, next_due=_due_in(2))
        self._seed(name="Out", price=99.0, next_due=_due_in(40))
        self.assertEqual(self._get(7)["total"], 12.5)

    def test_total_uses_reviewed_base_amounts(self):
        self._seed(
            name="Foreign",
            price=100,
            currency="CNY",
            base_price_text="20.00",
            base_currency_code="CAD",
            next_due=_due_in(1),
        )
        self._seed(
            name="Local",
            price=5,
            currency="CAD",
            base_price_text="5.00",
            base_currency_code="CAD",
            next_due=_due_in(2),
        )
        result = self._get(7)
        self.assertEqual(result["total"], 25)
        self.assertEqual(result["currency"], "CAD")

    def test_currency_from_first_item(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary")
            db.add(state)
        state.base_currency_code = "EUR"
        db.commit()
        db.close()
        self._seed(
            name="Eur",
            price=3.0,
            currency="€",
            base_currency_code="EUR",
            next_due=_due_in(1),
        )
        self.assertEqual(self._get(7)["currency"], "EUR")

    def test_empty_window(self):
        self._seed(name="Later", next_due=_due_in(60))
        r = self._get(7)
        self.assertEqual(r["items"], [])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["currency"], "CAD")

    def test_empty_window_uses_the_configured_ledger_currency(self):
        db = self.db()
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            state = FinanceLedgerState(id="primary")
            db.add(state)
        state.base_currency_code = "EUR"
        db.commit()
        db.close()
        self.assertEqual(self._get(7)["currency"], "EUR")

    def test_same_price_and_currency_patch_preserves_reviewed_conversion(self):
        self._seed(
            name="Foreign",
            price=100,
            currency="CNY",
            base_price_text="20.00",
            base_currency_code="CAD",
            fx_rate_text="0.2",
            fx_rate_date="2026-07-18",
            fx_source="owner statement",
            next_due=_due_in(2),
        )
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()

        response = self.client.patch(
            f"/api/subscriptions/{sid}",
            json={"name": "Foreign renamed", "price": 100, "currency": "CNY"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        sub = db.get(Subscription, sid)
        self.assertEqual(sub.base_price_text, "20.00")
        self.assertEqual(sub.fx_rate_text, "0.2")
        self.assertEqual(sub.fx_source, "owner statement")
        db.close()

    def test_reviewed_iso_currency_patch_preserves_ambiguous_display_evidence(self):
        self._seed(
            name="Dollar display",
            price=100,
            currency="$",
            original_currency_code="USD",
            base_price_text="136.00",
            base_currency_code="CAD",
            fx_rate_text="1.36",
            fx_source="owner statement",
            next_due=_due_in(2),
        )
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()

        response = self.client.patch(f"/api/subscriptions/{sid}", json={"currency": "USD"})

        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        sub = db.get(Subscription, sid)
        self.assertEqual(sub.base_price_text, "136.00")
        self.assertEqual(sub.fx_rate_text, "1.36")
        self.assertEqual(sub.fx_source, "owner statement")
        db.close()

    def test_unchanged_ambiguous_display_patch_preserves_reviewed_evidence(self):
        self._seed(
            name="Dollar display",
            price=100,
            currency="$",
            original_currency_code="USD",
            base_price_text="136.00",
            base_currency_code="CAD",
            fx_rate_text="1.36",
            fx_source="owner statement",
            next_due=_due_in(2),
        )
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()

        response = self.client.patch(
            f"/api/subscriptions/{sid}",
            json={"name": "Dollar display", "price": 100, "currency": "$"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        sub = db.get(Subscription, sid)
        self.assertEqual(sub.original_currency_code, "USD")
        self.assertEqual(sub.base_price_text, "136.00")
        self.assertEqual(sub.fx_rate_text, "1.36")
        self.assertEqual(sub.fx_source, "owner statement")
        db.close()

    def test_ambiguous_currency_patch_is_rejected_without_changing_evidence(self):
        self._seed(
            name="Dollar display",
            price=100,
            currency="$",
            original_currency_code="USD",
            base_price_text="136.00",
            base_currency_code="CAD",
            fx_rate_text="1.36",
            fx_source="owner statement",
            next_due=_due_in(2),
        )
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()

        response = self.client.patch(f"/api/subscriptions/{sid}", json={"currency": "¥"})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("unambiguous ISO currency code", response.text)
        db = self.db()
        sub = db.get(Subscription, sid)
        self.assertEqual(sub.currency, "$")
        self.assertEqual(sub.original_currency_code, "USD")
        self.assertEqual(sub.base_price_text, "136.00")
        self.assertEqual(sub.fx_rate_text, "1.36")
        self.assertEqual(sub.fx_source, "owner statement")
        db.close()

    def test_changed_foreign_price_requires_new_reviewed_conversion(self):
        self._seed(
            name="Foreign",
            price=100,
            currency="CNY",
            base_price_text="20.00",
            base_currency_code="CAD",
            fx_rate_text="0.2",
            next_due=_due_in(2),
        )
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()

        response = self.client.patch(f"/api/subscriptions/{sid}", json={"price": 110})

        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        sub = db.get(Subscription, sid)
        self.assertEqual(sub.original_price_text, "110.0")
        self.assertEqual(sub.original_currency_code, "CNY")
        self.assertEqual(sub.base_price_text, "")
        self.assertEqual(sub.base_currency_code, "CAD")
        self.assertEqual(sub.fx_rate_text, "")
        db.close()
        blocked = self.client.get("/api/subscriptions/upcoming?days=7")
        self.assertEqual(blocked.status_code, 409, blocked.text)

    def test_non_finite_prices_are_rejected_before_mutation(self):
        created = self.client.post(
            "/api/subscriptions",
            content=(f'{{"name":"bad","price":NaN,"currency":"CAD","next_due":"{_due_in(2)}"}}'),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(created.status_code, 400, created.text)
        self._seed(name="Stable", price=5, next_due=_due_in(2))
        db = self.db()
        sid = db.query(Subscription).one().id
        db.close()
        patched = self.client.patch(
            f"/api/subscriptions/{sid}",
            content='{"price":Infinity}',
            headers={"content-type": "application/json"},
        )
        self.assertEqual(patched.status_code, 400, patched.text)
        db = self.db()
        self.assertEqual(db.get(Subscription, sid).price, 5)
        db.close()
        self.assertEqual(self.client.get(f"/api/subscriptions/{sid}/price-history").json(), [])

    def test_default_days_window(self):
        # default window should exclude something 60 days out
        self._seed(name="Default", next_due=_due_in(60))
        self.assertEqual(self._get()["items"], [])

    def test_response_shape(self):
        self._seed(name="S", next_due=_due_in(2))
        r = self._get(7)
        for k in ("days", "count", "total", "currency", "items"):
            self.assertIn(k, r)
        self.assertEqual(r["count"], len(r["items"]))

    def test_basic_list_keeps_rows_visible_when_totals_need_conversion_review(self):
        self._seed(
            name="Needs review",
            next_due=_due_in(2),
            base_price_text="",
            base_currency_code="",
        )
        response = self.client.get("/api/subscriptions", params={"advance": False})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual([row["name"] for row in payload["subscriptions"]], ["Needs review"])
        self.assertFalse(payload["summary"]["totals_available"])
        self.assertIsNone(payload["summary"]["monthly_total"])
        self.assertIsNone(payload["summary"]["yearly_total"])

    def test_wrong_base_keeps_list_visible_but_blocks_aggregate_endpoints(self):
        self._seed(
            name="Wrong base",
            price=5,
            currency="USD",
            base_price_text="5",
            base_currency_code="USD",
            next_due=_due_in(1),
        )
        response = self.client.get("/api/subscriptions", params={"advance": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["summary"]["totals_available"])
        for path in (
            "/api/subscriptions/analytics",
            "/api/subscriptions/upcoming?days=7",
            "/api/subscriptions/forecast?months=1",
        ):
            blocked = self.client.get(path)
            self.assertEqual(blocked.status_code, 409, (path, blocked.text))

    def test_malformed_next_due_does_not_break_list_or_upcoming(self):
        self._seed(name="Bad", next_due="not-a-date")
        self._seed(name="Good", next_due=_due_in(2))

        lst = self.client.get("/api/subscriptions")
        self.assertEqual(lst.status_code, 200)
        bad = next(s for s in lst.json()["subscriptions"] if s["name"] == "Bad")
        self.assertIsNone(bad["days_until"])
        self.assertFalse(bad["payable"])

        up = self._get(7)
        self.assertEqual([i["name"] for i in up["items"]], ["Good"])
