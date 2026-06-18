from datetime import date

from core.database import Subscription
from tests._client import ApiTest


class SubPriceHistoryTests(ApiTest):
    def _sub(self, price=10.0):
        d = self.db()
        s = Subscription(
            name="Svc", price=price, cycle="monthly", next_due=date.today().isoformat(), active=True
        )
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        return sid

    def _patch(self, sid, **body):
        return self.client.patch(f"/api/subscriptions/{sid}", json=body)

    def _item(self, sid):
        rows = self.client.get("/api/subscriptions").json()["subscriptions"]
        return [s for s in rows if s["id"] == sid][0]

    def _hist(self, sid):
        return self.client.get(f"/api/subscriptions/{sid}/price-history").json()

    def test_patch_price_records_change(self):
        sid = self._sub(10.0)
        self._patch(sid, price=15.0)
        h = self._hist(sid)
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["old"], h[0]["new"]), (10.0, 15.0))

    def test_patch_same_price_no_record(self):
        sid = self._sub(10.0)
        self._patch(sid, price=10.0)
        self.assertEqual(self._hist(sid), [])

    def test_patch_non_price_no_record(self):
        sid = self._sub(10.0)
        self._patch(sid, name="Renamed")
        self.assertEqual(self._hist(sid), [])

    def test_price_increase_sets_flag(self):
        sid = self._sub(10.0)
        self._patch(sid, price=12.0)
        self.assertTrue(self._item(sid)["price_increased"])

    def test_price_decrease_not_hike(self):
        sid = self._sub(20.0)
        self._patch(sid, price=12.0)
        self.assertFalse(self._item(sid)["price_increased"])
        self.assertEqual(len(self._hist(sid)), 1)  # still recorded

    def test_last_price_change_exposed(self):
        sid = self._sub(10.0)
        self._patch(sid, price=18.0)
        lc = self._item(sid)["last_price_change"]
        self.assertEqual((lc["old"], lc["new"]), (10.0, 18.0))
        self.assertEqual(lc["date"], date.today().isoformat())

    def test_multiple_changes_history_newest_first(self):
        sid = self._sub(10.0)
        self._patch(sid, price=12.0)
        self._patch(sid, price=14.0)
        h = self._hist(sid)
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["new"], 14.0)  # newest first

    def test_no_changes_flag_false(self):
        sid = self._sub(10.0)
        it = self._item(sid)
        self.assertFalse(it["price_increased"])
        self.assertIsNone(it["last_price_change"])

    def test_price_history_unknown_404(self):
        self.assertEqual(self.client.get("/api/subscriptions/nope/price-history").status_code, 404)

    def test_actual_price_updated(self):
        sid = self._sub(10.0)
        self._patch(sid, price=16.0)
        self.assertEqual(self._item(sid)["price"], 16.0)
