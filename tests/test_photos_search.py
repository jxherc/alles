import json
import unittest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Photo
from routes import photos as P


def _mkdb():
    eng = create_engine("sqlite:///:memory:")
    Photo.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _add(db, **kw):
    base = dict(filename="x.jpg", thumb="x.jpg", original_name="img.jpg",
                width=10, height=10, taken_at=datetime(2026, 6, 14, 10, 0), exif="{}")
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


if __name__ == "__main__":
    unittest.main()
