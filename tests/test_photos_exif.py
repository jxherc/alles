import unittest
from datetime import datetime

from services.photos_store import _exif_fields, _gps_to_decimal


class GpsTests(unittest.TestCase):
    def test_north_east_positive(self):
        # 37°48'30" N, 122°25'09" W style → use N/E here for positive
        gps = {1: "N", 2: (37, 48, 30), 3: "E", 4: (122, 25, 9)}
        lat, lon = _gps_to_decimal(gps)
        self.assertAlmostEqual(lat, 37.808333, places=4)
        self.assertAlmostEqual(lon, 122.419167, places=4)

    def test_south_west_negative(self):
        gps = {1: "S", 2: (33, 51, 54), 3: "W", 4: (151, 12, 36)}
        lat, lon = _gps_to_decimal(gps)
        self.assertLess(lat, 0)
        self.assertLess(lon, 0)

    def test_empty_returns_none(self):
        self.assertIsNone(_gps_to_decimal({}))
        self.assertIsNone(_gps_to_decimal(None))

    def test_malformed_returns_none(self):
        self.assertIsNone(_gps_to_decimal({1: "N", 2: "garbage"}))


class ExifFieldsTests(unittest.TestCase):
    def test_camera_tags(self):
        _, out = _exif_fields({"Make": "Apple", "Model": "iPhone 15", "FNumber": 1.8})
        self.assertEqual(out["Make"], "Apple")
        self.assertEqual(out["Model"], "iPhone 15")
        self.assertEqual(out["FNumber"], "1.8")

    def test_taken_at_parsed(self):
        taken, _ = _exif_fields({"DateTimeOriginal": "2026:06:18 14:30:00"})
        self.assertEqual(taken, datetime(2026, 6, 18, 14, 30, 0))

    def test_datetime_fallback(self):
        taken, _ = _exif_fields({"DateTime": "2026:01:02 03:04:05"})
        self.assertEqual(taken, datetime(2026, 1, 2, 3, 4, 5))

    def test_richer_tags(self):
        _, out = _exif_fields({"Orientation": 6, "Flash": 16, "Software": "iOS 18"})
        self.assertIn("Orientation", out)
        self.assertIn("Flash", out)
        self.assertEqual(out["Software"], "iOS 18")

    def test_empty(self):
        taken, out = _exif_fields({})
        self.assertIsNone(taken)
        self.assertEqual(out, {})

    def test_ignores_blank_values(self):
        _, out = _exif_fields({"Make": "", "Model": None, "LensModel": "wide"})
        self.assertNotIn("Make", out)
        self.assertNotIn("Model", out)
        self.assertEqual(out["LensModel"], "wide")

    def test_bad_date_does_not_crash(self):
        taken, _ = _exif_fields({"DateTimeOriginal": "not a date"})
        self.assertIsNone(taken)


if __name__ == "__main__":
    unittest.main()
