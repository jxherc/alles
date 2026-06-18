from core.database import Contact
from tests._client import ApiTest


class ContactSearchFavTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        d.add_all(
            [
                Contact(
                    name="Ada Lovelace",
                    email="ada@math.org",
                    phone="555-1111",
                    company="Analytical",
                    favorite=True,
                ),
                Contact(
                    name="Bob Stone",
                    email="bob@stone.io",
                    phone="555-2222",
                    company="Quarry Co",
                    favorite=False,
                ),
                Contact(
                    name="Cara Diem",
                    email="cara@day.net",
                    phone="555-3333",
                    company="Analytical",
                    favorite=True,
                ),
            ]
        )
        d.commit()
        d.close()

    def _names(self, **params):
        return sorted(c["name"] for c in self.client.get("/api/contacts", params=params).json())

    def test_search_by_name(self):
        self.assertEqual(self._names(q="ada"), ["Ada Lovelace"])

    def test_search_by_email(self):
        self.assertEqual(self._names(q="stone.io"), ["Bob Stone"])

    def test_search_by_phone(self):
        self.assertEqual(self._names(q="555-3333"), ["Cara Diem"])

    def test_search_by_company(self):
        self.assertEqual(self._names(q="analytical"), ["Ada Lovelace", "Cara Diem"])

    def test_empty_q_returns_all(self):
        self.assertEqual(len(self._names()), 3)

    def test_favorites_filter(self):
        self.assertEqual(self._names(favorites="true"), ["Ada Lovelace", "Cara Diem"])

    def test_favorites_plus_query(self):
        self.assertEqual(self._names(favorites="true", q="cara"), ["Cara Diem"])

    def test_patch_favorite(self):
        cid = [
            c["id"] for c in self.client.get("/api/contacts").json() if c["name"] == "Bob Stone"
        ][0]
        self.client.patch(f"/api/contacts/{cid}", json={"favorite": True})
        self.assertIn("Bob Stone", self._names(favorites="true"))

    def test_fmt_has_favorite(self):
        self.assertIn("favorite", self.client.get("/api/contacts").json()[0])
