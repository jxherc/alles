"""4a - the contact-birthday calendar overlay route."""

from core.database import Contact
from tests._client import ApiTest


class CalendarBirthdaysTests(ApiTest):
    def _contact(self, name, birthday):
        db = self.db()
        db.add(Contact(name=name, birthday=birthday))
        db.commit()
        db.close()

    def _bdays(self):
        return self.client.get("/api/calendar/birthdays").json()

    def test_full_date_birthday(self):
        self._contact("Ada", "1990-12-10")
        out = self._bdays()
        self.assertEqual(out, [{"id": out[0]["id"], "name": "Ada", "month": 12, "day": 10}])

    def test_month_day_only(self):
        self._contact("Bea", "03-04")  # no year on file
        out = self._bdays()
        self.assertEqual((out[0]["month"], out[0]["day"]), (3, 4))

    def test_skips_blank_and_garbage(self):
        self._contact("HasNone", "")
        self._contact("Garbage", "not-a-date")
        self._contact("Good", "1985-06-25")
        out = self._bdays()
        self.assertEqual([c["name"] for c in out], ["Good"])

    def test_skips_out_of_range_month(self):
        self._contact("Weird", "1990-13-40")  # invalid month/day
        self.assertEqual(self._bdays(), [])
