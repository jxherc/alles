from datetime import date, timedelta

from core.database import Subscription
from tests._client import ApiTest


class SubTrialTests(ApiTest):
    def test_create_without_currency_uses_the_ledger_base_currency(self):
        response = self.client.post(
            "/api/subscriptions",
            json={"name": "base default", "price": 9, "next_due": "2026-08-01"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["currency"], "CAD")
        self.assertEqual(response.json()["original_currency_code"], "CAD")
        self.assertEqual(response.json()["base_currency_code"], "CAD")

    def test_create_rejects_an_ambiguous_currency_symbol(self):
        response = self.client.post(
            "/api/subscriptions",
            json={
                "name": "ambiguous",
                "price": 9,
                "currency": "$",
                "next_due": "2026-08-01",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("unambiguous ISO currency code", response.text)

    def test_create_with_trial_end(self):
        end = (date.today() + timedelta(days=5)).isoformat()
        r = self.client.post(
            "/api/subscriptions",
            json={
                "name": "Spotify",
                "price": 0,
                "cycle": "monthly",
                "next_due": "2026-07-01",
                "trial_end": end,
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["trial_end"], end)

    def test_trial_days_left_computed(self):
        end = (date.today() + timedelta(days=5)).isoformat()
        r = self.client.post(
            "/api/subscriptions",
            json={
                "name": "T",
                "price": 0,
                "cycle": "monthly",
                "next_due": "2026-07-01",
                "trial_end": end,
            },
        )
        self.assertEqual(r.json()["trial_days_left"], 5)

    def test_no_trial_is_none(self):
        r = self.client.post(
            "/api/subscriptions",
            json={"name": "NoTrial", "price": 9, "cycle": "monthly", "next_due": "2026-07-01"},
        )
        self.assertIsNone(r.json()["trial_days_left"])

    def test_patch_trial_end(self):
        sid = self.client.post(
            "/api/subscriptions",
            json={"name": "P", "price": 9, "cycle": "monthly", "next_due": "2026-07-01"},
        ).json()["id"]
        end = (date.today() + timedelta(days=10)).isoformat()
        self.client.patch(f"/api/subscriptions/{sid}", json={"trial_end": end})
        got = [
            s
            for s in self.client.get("/api/subscriptions").json()["subscriptions"]
            if s["id"] == sid
        ][0]
        self.assertEqual(got["trial_end"], end)
        self.assertEqual(got["trial_days_left"], 10)

    def test_trials_ending_endpoint(self):
        d = self.db()
        d.add(
            Subscription(
                name="Soon",
                cycle="monthly",
                next_due="2026-07-01",
                trial_end=(date.today() + timedelta(days=3)).isoformat(),
            )
        )
        d.add(
            Subscription(
                name="Far",
                cycle="monthly",
                next_due="2026-07-01",
                trial_end=(date.today() + timedelta(days=40)).isoformat(),
            )
        )
        d.add(Subscription(name="None", cycle="monthly", next_due="2026-07-01"))
        d.commit()
        d.close()
        names = [
            t["name"]
            for t in self.client.get("/api/subscriptions/trials", params={"days": 7}).json()
        ]
        self.assertIn("Soon", names)
        self.assertNotIn("Far", names)
        self.assertNotIn("None", names)

    def test_trials_sorted_by_days_left(self):
        d = self.db()
        d.add(
            Subscription(
                name="B",
                cycle="monthly",
                next_due="2026-07-01",
                trial_end=(date.today() + timedelta(days=6)).isoformat(),
            )
        )
        d.add(
            Subscription(
                name="A",
                cycle="monthly",
                next_due="2026-07-01",
                trial_end=(date.today() + timedelta(days=2)).isoformat(),
            )
        )
        d.commit()
        d.close()
        names = [
            t["name"]
            for t in self.client.get("/api/subscriptions/trials", params={"days": 30}).json()
        ]
        self.assertEqual(names[:2], ["A", "B"])

    def test_past_trial_excluded_default_window(self):
        d = self.db()
        d.add(
            Subscription(
                name="Expired",
                cycle="monthly",
                next_due="2026-07-01",
                trial_end=(date.today() - timedelta(days=5)).isoformat(),
            )
        )
        d.commit()
        d.close()
        names = [
            t["name"]
            for t in self.client.get("/api/subscriptions/trials", params={"days": 30}).json()
        ]
        self.assertNotIn("Expired", names)

    def test_trial_days_left_in_list(self):
        end = (date.today() + timedelta(days=8)).isoformat()
        self.client.post(
            "/api/subscriptions",
            json={
                "name": "L",
                "price": 0,
                "cycle": "monthly",
                "next_due": "2026-07-01",
                "trial_end": end,
            },
        )
        s = [
            x
            for x in self.client.get("/api/subscriptions").json()["subscriptions"]
            if x["name"] == "L"
        ][0]
        self.assertEqual(s["trial_days_left"], 8)
