from datetime import date

from routes.days import _occurrence
from tests._client import ApiTest


class OccurrenceUnitTests(ApiTest):
    def test_yearly_future_orig_returns_orig(self):
        orig = date(2030, 6, 20)
        today = date(2026, 6, 18)
        occ, nth = _occurrence(orig, today, "yearly")
        self.assertEqual(occ, orig)
        self.assertEqual(nth, 0)

    def test_monthly_future_orig_returns_orig(self):
        orig = date(2026, 8, 10)
        today = date(2026, 6, 18)
        occ, nth = _occurrence(orig, today, "monthly")
        self.assertEqual(occ, orig)
        self.assertEqual(nth, 0)

    def test_yearly_never_negative_nth(self):
        orig = date(2031, 1, 1)
        today = date(2026, 6, 18)
        _, nth = _occurrence(orig, today, "yearly")
        self.assertGreaterEqual(nth, 0)

    def test_monthly_never_negative_nth(self):
        orig = date(2027, 3, 3)
        today = date(2026, 6, 18)
        _, nth = _occurrence(orig, today, "monthly")
        self.assertGreaterEqual(nth, 0)

    def test_yearly_past_unchanged(self):
        orig = date(1990, 6, 20)
        today = date(2026, 6, 18)
        occ, nth = _occurrence(orig, today, "yearly")
        self.assertEqual(occ, date(2026, 6, 20))
        self.assertEqual(nth, 36)

    def test_yearly_past_already_passed_this_year_rolls(self):
        orig = date(1990, 6, 10)
        today = date(2026, 6, 18)  # this year's 6/10 already passed
        occ, nth = _occurrence(orig, today, "yearly")
        self.assertEqual(occ, date(2027, 6, 10))
        self.assertEqual(nth, 37)

    def test_monthly_past_unchanged(self):
        orig = date(2020, 1, 15)
        today = date(2026, 6, 18)  # 15th already passed this month
        occ, nth = _occurrence(orig, today, "monthly")
        self.assertEqual(occ, date(2026, 7, 15))
        self.assertGreater(nth, 0)

    def test_orig_today_yearly(self):
        orig = date(2000, 6, 18)
        today = date(2026, 6, 18)
        occ, nth = _occurrence(orig, today, "yearly")
        self.assertEqual(occ, today)
        self.assertEqual(nth, 26)

    def test_future_orig_today_returns_orig_nth_zero(self):
        # orig is in the future but happens to equal today+0 only when not future;
        # a strictly-future orig (tomorrow) is the first occurrence
        orig = date(2026, 6, 19)
        today = date(2026, 6, 18)
        occ, nth = _occurrence(orig, today, "yearly")
        self.assertEqual(occ, orig)
        self.assertEqual(nth, 0)


class FutureRepeatApiTests(ApiTest):
    def _mk(self, name, dt, repeat):
        return self.client.post(
            "/api/days", json={"name": name, "date": dt, "repeat": repeat}
        ).json()

    def test_api_future_yearly_not_today(self):
        # 2 years out, yearly → must not be mode "today" with negative nth
        fut = date(date.today().year + 2, 1, 1).isoformat()
        d = self._mk("Wedding", fut, "yearly")
        self.assertNotEqual(d["mode"], "today")
        self.assertGreaterEqual(d["nth"], 0)
        self.assertEqual(d["target"], fut)

    def test_api_future_yearly_counts_down_to_orig(self):
        fut = date(date.today().year + 1, 12, 31).isoformat()
        d = self._mk("NYE party", fut, "yearly")
        self.assertEqual(d["target"], fut)
        self.assertGreater(d["days"], 0)
