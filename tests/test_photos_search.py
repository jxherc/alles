import base64
import json
import unittest
from datetime import datetime
from unittest import mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Photo
from routes import photos as P


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
