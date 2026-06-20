import base64
import json
import unittest
from datetime import datetime
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Photo
from routes import photos as P
from services.photos_store import _exif_fields, _gps_to_decimal


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    Photo.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _add(db, **kw):
    base = dict(
        filename="x.jpg",
        thumb="x.jpg",
        original_name="img.jpg",
        width=10,
        height=10,
        taken_at=datetime(2026, 6, 14, 10, 0),
        exif="{}",
    )
    base.update(kw)
    db.add(Photo(**base))
    db.commit()


class PhotoSearchTests(unittest.TestCase):
    def test_by_filename(self):
        db = _mkdb()
        _add(db, original_name="vacation_beach.jpg")
        _add(db, original_name="receipt.png")
        self.assertEqual(P.search_photos("beach", db)["count"], 1)

    def test_by_camera_exif(self):
        db = _mkdb()
        _add(db, exif=json.dumps({"Make": "Canon", "Model": "EOS R5"}))
        _add(db, exif=json.dumps({"Make": "Apple", "Model": "iPhone 16"}))
        self.assertEqual(P.search_photos("canon", db)["count"], 1)
        self.assertEqual(P.search_photos("iphone", db)["count"], 1)

    def test_by_date(self):
        db = _mkdb()
        _add(db, taken_at=datetime(2026, 6, 14))
        _add(db, taken_at=datetime(2025, 1, 1))
        self.assertEqual(P.search_photos("june 2026", db)["count"], 1)
        self.assertEqual(P.search_photos("2025", db)["count"], 1)

    def test_empty(self):
        self.assertEqual(P.search_photos("", _mkdb())["count"], 0)

    def test_by_caption(self):
        # caption is part of haystack — should be findable
        db = _mkdb()
        _add(db, caption="sunset over the mountains")
        _add(db, caption="birthday party")
        self.assertEqual(P.search_photos("mountains", db)["count"], 1)
        self.assertEqual(P.search_photos("birthday", db)["count"], 1)

    def test_by_keywords(self):
        db = _mkdb()
        _add(db, keywords="travel,nature")
        _add(db, keywords="food,urban")
        self.assertEqual(P.search_photos("nature", db)["count"], 1)
        self.assertEqual(P.search_photos("urban", db)["count"], 1)
        self.assertEqual(P.search_photos("travel", db)["count"], 1)

    def test_deleted_excluded(self):
        # soft-deleted photos must not appear in search results
        db = _mkdb()
        _add(db, original_name="gone.jpg", deleted_at=datetime(2026, 1, 1))
        _add(db, original_name="gone_beach.jpg")
        # 'gone' matches both names but deleted one should be excluded
        self.assertEqual(P.search_photos("gone", db)["count"], 1)

    def test_hidden_excluded(self):
        # hidden photos are excluded from normal search
        db = _mkdb()
        _add(db, original_name="secret_doc.jpg", hidden=True)
        _add(db, original_name="normal_doc.jpg", hidden=False)
        self.assertEqual(P.search_photos("doc", db)["count"], 1)
        self.assertEqual(P.search_photos("secret", db)["count"], 0)


class GpsDecimalTests(unittest.TestCase):
    def test_north_east(self):
        gps = {1: "N", 2: (48.0, 51.0, 0.0), 3: "E", 4: (2.0, 21.0, 0.0)}
        lat, lon = _gps_to_decimal(gps)
        self.assertAlmostEqual(lat, 48.85, places=1)
        self.assertAlmostEqual(lon, 2.35, places=1)

    def test_south_west_negative(self):
        # southern/western hemisphere → negative decimal coords
        gps = {1: "S", 2: (33.0, 52.0, 0.0), 3: "W", 4: (70.0, 40.0, 0.0)}
        lat, lon = _gps_to_decimal(gps)
        self.assertLess(lat, 0)
        self.assertLess(lon, 0)

    def test_none_on_missing(self):
        self.assertIsNone(_gps_to_decimal(None))
        self.assertIsNone(_gps_to_decimal({}))


class ExifFieldsTests(unittest.TestCase):
    def test_date_parsing(self):
        tags = {"DateTimeOriginal": "2024:07:04 12:30:00", "Make": "Nikon"}
        taken_at, fields = _exif_fields(tags)
        self.assertEqual(taken_at, datetime(2024, 7, 4, 12, 30, 0))
        self.assertEqual(fields["Make"], "Nikon")

    def test_bad_date_ignored(self):
        tags = {"DateTimeOriginal": "not-a-date"}
        taken_at, fields = _exif_fields(tags)
        self.assertIsNone(taken_at)

    def test_only_keep_keys(self):
        # fields not in _EXIF_KEEP should not appear
        tags = {"Make": "Sony", "SomeOtherTag": "whatever"}
        _, fields = _exif_fields(tags)
        self.assertIn("Make", fields)
        self.assertNotIn("SomeOtherTag", fields)


class EditSaveTests(unittest.TestCase):
    _FAKE = {
        "filename": "x.png",
        "thumb": "x.jpg",
        "original_name": "edited.png",
        "width": 2,
        "height": 2,
        "taken_at": datetime(2026, 6, 14),
        "exif": "{}",
    }

    def test_decodes_dataurl_and_saves(self):
        db = _mkdb()
        png = base64.b64encode(b"PNGDATA").decode()
        with mock.patch.object(P.ps, "import_image", lambda raw, name: self._FAKE):
            res = P.edit_save(
                P.EditSaveBody(data_url="data:image/png;base64," + png, name="edited.png"), db
            )
        self.assertEqual(res["original_name"], "edited.png")
        self.assertEqual(db.query(Photo).count(), 1)

    def test_bad_base64_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):  # non-base64 chars → empty/garbage → 400
            P.edit_save(P.EditSaveBody(data_url="data:image/png;base64,!!!!"), _mkdb())


if __name__ == "__main__":
    unittest.main()
