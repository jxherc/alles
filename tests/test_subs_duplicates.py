from datetime import date

from core.database import Subscription
from tests._client import ApiTest


class SubDuplicatesTests(ApiTest):
    def _sub(self, name, url="", price=10.0):
        d = self.db()
        s = Subscription(
            name=name,
            url=url,
            price=price,
            cycle="monthly",
            next_due=date.today().isoformat(),
            active=True,
        )
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        return sid

    def _dupes(self):
        return self.client.get("/api/subscriptions/duplicates").json()

    def test_same_name_grouped(self):
        self._sub("Netflix")
        self._sub("Netflix")
        groups = self._dupes()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["subs"]), 2)

    def test_normalized_name_match(self):
        self._sub("Netflix")
        self._sub("  netflix ")
        self.assertEqual(len(self._dupes()["groups"]), 1)

    def test_different_names_not_grouped(self):
        self._sub("Netflix")
        self._sub("Spotify")
        self.assertEqual(self._dupes()["groups"], [])

    def test_same_url_host_grouped(self):
        self._sub("NF", url="https://netflix.com/account")
        self._sub("Flix", url="http://netflix.com/plan")
        self.assertEqual(len(self._dupes()["groups"]), 1)

    def test_www_stripped(self):
        self._sub("A", url="https://www.netflix.com")
        self._sub("B", url="https://netflix.com/x")
        self.assertEqual(len(self._dupes()["groups"]), 1)

    def test_three_way_group(self):
        for _ in range(3):
            self._sub("Netflix")
        groups = self._dupes()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["subs"]), 3)

    def test_name_and_host_union(self):
        self._sub("Netflix")  # A: name
        self._sub("Netflix", url="https://netflix.com")  # B: name + host
        self._sub("MyFlix", url="https://netflix.com/acct")  # C: host only
        groups = self._dupes()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["subs"]), 3)

    def test_no_duplicates_empty(self):
        self._sub("Netflix")
        self._sub("Spotify")
        self._sub("Hulu")
        self.assertEqual(self._dupes()["groups"], [])

    def test_group_shape(self):
        self._sub("Netflix")
        self._sub("Netflix")
        g = self._dupes()["groups"][0]
        self.assertIn("subs", g)
        self.assertTrue(all("id" in s and "name" in s for s in g["subs"]))

    def test_empty_no_subs(self):
        self.assertEqual(self._dupes()["groups"], [])
