from core.database import Account
from tests._client import ApiTest


class SubsIntelTests(ApiTest):
    def _sub(self, name, cycle="monthly", next_due="2026-07-01", cancel_url="", active=True):
        s = self.client.post(
            "/api/subscriptions",
            json={
                "name": name,
                "price": 9.99,
                "cycle": cycle,
                "next_due": next_due,
                "cancel_url": cancel_url,
            },
        ).json()
        if not active:
            self.client.patch(f"/api/subscriptions/{s['id']}", json={"active": False})
        return s

    def _acct(self, opening=0.0, low_balance=0.0):
        db = self.db()
        a = Account(name="Checking", kind="checking", opening=opening, low_balance=low_balance)
        db.add(a)
        db.commit()
        aid = a.id
        db.close()
        return aid

    def _txn(self, aid, amount, payee="", notes="", category="", date="2026-06-10"):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": aid,
                "date": date,
                "amount": amount,
                "payee": payee,
                "notes": notes,
                "category": category,
            },
        ).json()

    # ---- cancel_url ----
    def test_create_with_cancel_url(self):
        s = self._sub("Netflix", cancel_url="https://netflix.com/cancel")
        self.assertEqual(s["cancel_url"], "https://netflix.com/cancel")

    def test_patch_cancel_url(self):
        s = self._sub("Netflix")
        self.client.patch(
            f"/api/subscriptions/{s['id']}", json={"cancel_url": "https://x.com/cancel"}
        )
        subs = self.client.get("/api/subscriptions").json()["subscriptions"]
        got = next(x for x in subs if x["id"] == s["id"])
        self.assertEqual(got["cancel_url"], "https://x.com/cancel")

    def test_sub_fmt_has_cancel_url(self):
        self._sub("Spotify")
        self.assertIn(
            "cancel_url", self.client.get("/api/subscriptions").json()["subscriptions"][0]
        )

    # ---- unused detection ----
    def test_unused_flags_no_charge(self):
        self._acct()
        self._sub("Netflix")
        d = self.client.get(
            "/api/subscriptions/unused", params={"cycles": 2, "as_of": "2026-06-15"}
        ).json()
        self.assertTrue(any(s["name"] == "Netflix" for s in d["unused"]))

    def test_unused_junk_as_of_doesnt_crash(self):
        self._acct()
        self._sub("Netflix")
        r = self.client.get("/api/subscriptions/unused", params={"as_of": "garbage"})
        self.assertEqual(r.status_code, 200)  # falls back to today instead of 500

    def test_unused_excludes_recent_charge(self):
        aid = self._acct()
        self._sub("Spotify")
        self._txn(aid, -9.99, payee="Spotify Premium", date="2026-06-10")
        d = self.client.get(
            "/api/subscriptions/unused", params={"cycles": 2, "as_of": "2026-06-15"}
        ).json()
        self.assertFalse(any(s["name"] == "Spotify" for s in d["unused"]))

    def test_unused_respects_cycles(self):
        aid = self._acct()
        self._sub("Hulu", cycle="monthly")
        # a charge 100 days ago is outside a 2*30=60 day window → still unused
        self._txn(aid, -9.99, payee="Hulu", date="2026-03-07")
        d = self.client.get(
            "/api/subscriptions/unused", params={"cycles": 2, "as_of": "2026-06-15"}
        ).json()
        self.assertTrue(any(s["name"] == "Hulu" for s in d["unused"]))

    def test_unused_only_active(self):
        self._acct()
        self._sub("Paused", active=False)
        d = self.client.get(
            "/api/subscriptions/unused", params={"cycles": 2, "as_of": "2026-06-15"}
        ).json()
        self.assertFalse(any(s["name"] == "Paused" for s in d["unused"]))

    def test_unused_matches_notes(self):
        aid = self._acct()
        self._sub("Disney")
        self._txn(aid, -9.99, payee="DIS*STORE", notes="disney plus monthly", date="2026-06-10")
        d = self.client.get(
            "/api/subscriptions/unused", params={"cycles": 2, "as_of": "2026-06-15"}
        ).json()
        self.assertFalse(any(s["name"] == "Disney" for s in d["unused"]))

    # ---- low-balance alerts ----
    def test_account_low_balance_settable(self):
        aid = self._acct(opening=50)
        self.client.patch(f"/api/money/accounts/{aid}", json={"low_balance": 100})
        got = next(a for a in self.client.get("/api/money/accounts").json() if a["id"] == aid)
        self.assertEqual(got["low_balance"], 100.0)

    def test_alerts_low_balance(self):
        self._acct(opening=50, low_balance=100)  # 50 < 100 → alert
        d = self.client.get("/api/money/alerts", params={"month": "2026-06"}).json()
        self.assertTrue(d["low_balance"])

    def test_alerts_low_balance_off_when_zero(self):
        self._acct(opening=5, low_balance=0)  # threshold 0 = off
        d = self.client.get("/api/money/alerts", params={"month": "2026-06"}).json()
        self.assertFalse(d["low_balance"])

    def test_alerts_no_low_balance_when_above(self):
        self._acct(opening=500, low_balance=100)  # 500 > 100 → no alert
        d = self.client.get("/api/money/alerts", params={"month": "2026-06"}).json()
        self.assertFalse(d["low_balance"])
