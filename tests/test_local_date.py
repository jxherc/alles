"""a stored utc time is read as the day it falls on here, so evening rows aren't tomorrow's"""

import os
import time
import unittest
from datetime import date, datetime

from core.schema.base import local_date


class LocalDateTests(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Toronto"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def test_seven_pm_in_toronto_is_still_today(self):
        # nov 2 00:03 utc is nov 1 7:03 pm in toronto (est)
        self.assertEqual(local_date(datetime(2026, 11, 2, 0, 3)), date(2026, 11, 1))

    def test_a_summer_evening_too(self):
        # jul 15 02:30 utc is jul 14 10:30 pm in toronto (edt)
        self.assertEqual(local_date(datetime(2026, 7, 15, 2, 30)), date(2026, 7, 14))

    def test_midday_is_the_same_day(self):
        self.assertEqual(local_date(datetime(2026, 11, 1, 17, 0)), date(2026, 11, 1))


if __name__ == "__main__":
    unittest.main()
