import importlib.util
import io
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as database
from services import photo_sync, photos_store
from services.photokit import PhotoKitResource


def _png(size=(40, 30), color=(25, 100, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class _FakePhotoKit:
    def __init__(self, resources, payloads=None, before_export=None):
        self.resources = list(resources)
        self.payloads = payloads or {}
        self.before_export = before_export
        self.exports = []

    def ensure_authorized(self, timeout=60):
        return "authorized"

    def iter_resources(self):
        return list(self.resources)

    def export_resource(self, item, destination, timeout=300):
        self.exports.append(item.source_id)
        if self.before_export:
            self.before_export(item, len(self.exports))
        data = self.payloads.get(item.source_id)
        if data is None:
            data = _png() if item.kind == "photo" else b"\x00\x00\x00\x18ftypqt  live-motion"
        Path(destination).write_bytes(data)


def _resource(
    source_id,
    kind="photo",
    *,
    asset_id="asset-1",
    modified=None,
    favorite=True,
    hidden=False,
    original_name=None,
):
    return PhotoKitResource(
        source_id=source_id,
        asset_id=asset_id,
        kind=kind,
        original_name=original_name or ("IMG_0001.PNG" if kind == "photo" else "IMG_0001.MOV"),
        taken_at=datetime(2024, 5, 3, 10, 30),
        modified_at=modified or datetime(2024, 5, 4, 8, 15),
        favorite=favorite,
        hidden=hidden,
        width=40,
        height=30,
        exif={"lat": 25.033, "lon": 121.5654, "live_photo": kind != "video"},
        resource=object(),
    )


class PhotoKitSyncTest(unittest.TestCase):
    def setUp(self):
        self.photos_tmp = tempfile.TemporaryDirectory()
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        database.Base.metadata.create_all(self.eng)
        self.session = sessionmaker(bind=self.eng)()
        root = Path(self.photos_tmp.name).resolve()
        self._patches = [
            mock.patch.object(photos_store, "photos_dir", lambda: root),
            mock.patch.object(photos_store, "thumbs_dir", lambda: root / ".thumbs"),
        ]
        (root / ".thumbs").mkdir(exist_ok=True)
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()
        self.session.close()
        self.eng.dispose()
        self.photos_tmp.cleanup()

    def test_repeat_sync_uses_stable_source_ids_instead_of_duplicating(self):
        kit = _FakePhotoKit([_resource("asset-1:photo")])

        first = photo_sync.sync_macos_library(self.session, adapter=kit)
        second = photo_sync.sync_macos_library(self.session, adapter=kit)

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(self.session.query(database.Photo).count(), 1)
        row = self.session.query(database.Photo).one()
        self.assertEqual((row.source, row.source_id), ("apple_photos", "asset-1:photo"))
        self.assertTrue(row.favorite)
        self.assertEqual(row.taken_at, datetime(2024, 5, 3, 10, 30))

    def test_live_photo_keeps_motion_and_collapses_pair_into_a_stack(self):
        kit = _FakePhotoKit(
            [
                _resource("asset-live:photo", asset_id="asset-live"),
                _resource("asset-live:paired_video", "paired_video", asset_id="asset-live"),
            ]
        )

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        self.assertEqual(result["imported"], 2)
        rows = self.session.query(database.Photo).order_by(database.Photo.is_video).all()
        self.assertEqual(len(rows), 2)
        still, motion = rows
        self.assertFalse(still.is_video)
        self.assertTrue(motion.is_video)
        self.assertEqual(still.stack_id, still.id)
        self.assertEqual(motion.stack_id, still.id)
        self.assertEqual(motion.width, 40)
        self.assertEqual(motion.height, 30)
        self.assertEqual(still.source_asset_id, "asset-live")
        self.assertEqual(motion.source_asset_id, "asset-live")

    def test_repeat_sync_preserves_local_privacy_and_favorite_choices(self):
        source_id = "asset-local:photo"
        kit = _FakePhotoKit([_resource(source_id, favorite=True, hidden=False)])
        photo_sync.sync_macos_library(self.session, adapter=kit)
        row = self.session.query(database.Photo).one()
        row.favorite = False
        row.hidden = True
        self.session.commit()
        kit.resources = [_resource(source_id, favorite=True, hidden=False)]

        photo_sync.sync_macos_library(self.session, adapter=kit)

        row = self.session.query(database.Photo).one()
        self.assertFalse(row.favorite)
        self.assertTrue(row.hidden)

    def test_repeat_sync_does_not_reverse_a_local_live_photo_unstack(self):
        kit = _FakePhotoKit(
            [
                _resource("asset-live:photo", asset_id="asset-live"),
                _resource("asset-live:paired_video", "paired_video", asset_id="asset-live"),
            ]
        )
        photo_sync.sync_macos_library(self.session, adapter=kit)
        for row in self.session.query(database.Photo).all():
            row.stack_id = None
        self.session.commit()

        photo_sync.sync_macos_library(self.session, adapter=kit)

        self.assertTrue(
            all(row.stack_id is None for row in self.session.query(database.Photo).all())
        )

    def test_limit_reports_remaining_resources_for_the_next_run(self):
        kit = _FakePhotoKit(
            [_resource(f"asset-{i}:photo", asset_id=f"asset-{i}") for i in range(3)]
        )

        result = photo_sync.sync_macos_library(self.session, adapter=kit, limit=2)

        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(self.session.query(database.Photo).count(), 2)

    def test_limit_also_bounds_revised_assets_that_need_icloud_exports(self):
        items = [_resource(f"asset-{i}:photo", asset_id=f"asset-{i}") for i in range(2)]
        kit = _FakePhotoKit(items)
        photo_sync.sync_macos_library(self.session, adapter=kit)
        kit.resources = [
            _resource(
                item.source_id,
                asset_id=item.asset_id,
                modified=datetime(2024, 5, 8, 9, 0),
            )
            for item in items
        ]

        result = photo_sync.sync_macos_library(self.session, adapter=kit, limit=1)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(len(kit.exports), 3)

    def test_raw_photo_is_preserved_when_no_preview_decoder_exists(self):
        source_id = "asset-raw:photo"
        payload = b"II*\x00simulated-camera-raw"
        kit = _FakePhotoKit(
            [_resource(source_id, asset_id="asset-raw", original_name="DSC_0001.DNG")],
            {source_id: payload},
        )

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        row = self.session.query(database.Photo).one()
        self.assertEqual(result["imported"], 1)
        self.assertTrue(row.filename.endswith(".dng"))
        self.assertEqual((row.width, row.height), (40, 30))
        self.assertEqual(photos_store.original_path(row.filename).read_bytes(), payload)

    def test_newer_source_revision_replaces_stale_media(self):
        source_id = "asset-edit:photo"
        first_item = _resource(
            source_id, asset_id="asset-edit", modified=datetime(2024, 5, 4, 8, 15)
        )
        second_item = _resource(
            source_id, asset_id="asset-edit", modified=datetime(2024, 5, 6, 9, 45)
        )
        first_bytes = _png(color=(200, 20, 20))
        second_bytes = _png(color=(20, 20, 200))
        kit = _FakePhotoKit([first_item], {source_id: first_bytes})
        photo_sync.sync_macos_library(self.session, adapter=kit)
        original_checksum = self.session.query(database.Photo).one().checksum
        kit.resources = [second_item]
        kit.payloads[source_id] = second_bytes

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        row = self.session.query(database.Photo).one()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(kit.exports, [source_id, source_id])
        self.assertNotEqual(row.checksum, original_checksum)
        self.assertEqual(photos_store.original_path(row.filename).read_bytes(), second_bytes)
        self.assertEqual(row.source_modified_at, second_item.modified_at)

    def test_first_native_sync_adopts_one_matching_legacy_row(self):
        source_id = "asset-existing:photo"
        payload = _png(color=(90, 40, 160))
        info = photos_store.import_image(payload, "legacy.png")
        legacy = database.Photo(**info)
        self.session.add(legacy)
        self.session.commit()
        kit = _FakePhotoKit([_resource(source_id, asset_id="asset-existing")], {source_id: payload})

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        rows = self.session.query(database.Photo).all()
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["adopted"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].source, rows[0].source_id), ("apple_photos", source_id))

    def test_adoption_repairs_a_legacy_row_whose_managed_copy_is_missing(self):
        source_id = "asset-missing:photo"
        payload = _png(color=(10, 120, 80))
        info = photos_store.import_image(payload, "legacy.png")
        legacy = database.Photo(**info)
        self.session.add(legacy)
        self.session.commit()
        photos_store.delete_files(info["filename"], info["thumb"])
        kit = _FakePhotoKit([_resource(source_id, asset_id="asset-missing")], {source_id: payload})

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        row = self.session.query(database.Photo).one()
        self.assertEqual(result["adopted"], 1)
        self.assertTrue(photos_store.original_path(row.filename).is_file())
        self.assertEqual(photos_store.original_path(row.filename).read_bytes(), payload)

    def test_adoption_chooses_one_of_multiple_valid_legacy_duplicates(self):
        source_id = "asset-duplicate:photo"
        payload = _png(color=(100, 80, 20))
        for name in ("legacy-a.png", "legacy-b.png"):
            self.session.add(database.Photo(**photos_store.import_image(payload, name)))
        self.session.commit()
        kit = _FakePhotoKit(
            [_resource(source_id, asset_id="asset-duplicate")], {source_id: payload}
        )

        result = photo_sync.sync_macos_library(self.session, adapter=kit)

        rows = self.session.query(database.Photo).all()
        self.assertEqual(result["adopted"], 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row.source_id == source_id for row in rows), 1)

    def test_export_runs_outside_the_session_transaction(self):
        source_id = "asset-transaction:photo"
        states = []
        kit = _FakePhotoKit(
            [_resource(source_id, modified=datetime(2024, 5, 4, 8, 15))],
            before_export=lambda _item, _number: states.append(self.session.in_transaction()),
        )
        photo_sync.sync_macos_library(self.session, adapter=kit)
        kit.resources = [_resource(source_id, modified=datetime(2024, 5, 7, 12, 30))]

        photo_sync.sync_macos_library(self.session, adapter=kit)

        self.assertEqual(states, [False, False])

    def test_database_failure_removes_the_uncommitted_managed_copy(self):
        patcher = None

        def fail_next_flush(_item, _number):
            nonlocal patcher
            patcher = mock.patch.object(
                self.session, "flush", side_effect=SQLAlchemyError("simulated write failure")
            )
            patcher.start()

        kit = _FakePhotoKit(
            [_resource("asset-lock:photo", asset_id="asset-lock")],
            before_export=fail_next_flush,
        )
        try:
            result = photo_sync.sync_macos_library(self.session, adapter=kit)
        finally:
            if patcher:
                patcher.stop()

        originals = [path for path in Path(self.photos_tmp.name).iterdir() if path.is_file()]
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["failure_reasons"], {"database": 1})
        self.assertEqual(originals, [])


class PhotoKitTransactionTest(unittest.TestCase):
    def test_long_export_does_not_hold_the_sqlite_write_lock(self):
        db_tmp = tempfile.TemporaryDirectory()
        photos_tmp = tempfile.TemporaryDirectory()
        root = Path(photos_tmp.name).resolve()
        engine = create_engine(f"sqlite:///{Path(db_tmp.name) / 'photos.db'}")
        database.Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        primary = sessions()
        concurrent_ok = []

        def concurrent_write(_item, export_number):
            if export_number != 2:
                return
            other = sessions()
            try:
                other.add(database.Photo(filename="concurrent.png"))
                other.commit()
                concurrent_ok.append(True)
            finally:
                other.close()

        items = [
            _resource("asset-a:photo", asset_id="asset-a"),
            _resource("asset-b:photo", asset_id="asset-b"),
        ]
        kit = _FakePhotoKit(items, before_export=concurrent_write)
        try:
            with (
                mock.patch.object(photos_store, "photos_dir", lambda: root),
                mock.patch.object(photos_store, "thumbs_dir", lambda: root / ".thumbs"),
            ):
                (root / ".thumbs").mkdir()
                result = photo_sync.sync_macos_library(primary, adapter=kit)
        finally:
            primary.close()
            engine.dispose()
            photos_tmp.cleanup()
            db_tmp.cleanup()

        self.assertEqual(result["imported"], 2)
        self.assertEqual(concurrent_ok, [True])


class MacHeicDecodeTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pillow_heif"), "pillow-heif is macOS-only")
    def test_real_heic_gets_dimensions_thumbnail_preview_and_checksum(self):
        from pillow_heif import register_heif_opener

        register_heif_opener()
        payload = io.BytesIO()
        Image.new("RGB", (48, 32), (80, 160, 220)).save(payload, format="HEIF")
        root_tmp = tempfile.TemporaryDirectory()
        root = Path(root_tmp.name).resolve()
        try:
            (root / ".thumbs").mkdir()
            with (
                mock.patch.object(photos_store, "photos_dir", lambda: root),
                mock.patch.object(photos_store, "thumbs_dir", lambda: root / ".thumbs"),
            ):
                info = photos_store.import_image(payload.getvalue(), "phone.heic")
                thumb_exists = photos_store.thumb_path(info["thumb"]).is_file()
        finally:
            root_tmp.cleanup()

        self.assertEqual((info["width"], info["height"]), (48, 32))
        self.assertTrue(thumb_exists)
        self.assertTrue(info["preview"])
        self.assertEqual(len(info["checksum"]), 64)


class PhotoKitBackgroundJobTest(unittest.TestCase):
    def setUp(self):
        self.saved_jobs = dict(photo_sync._MAC_JOBS)
        photo_sync._MAC_JOBS.clear()

    def tearDown(self):
        photo_sync._MAC_JOBS.clear()
        photo_sync._MAC_JOBS.update(self.saved_jobs)

    def test_duplicate_start_reuses_the_active_job_and_finishes(self):
        entered = threading.Event()
        release = threading.Event()

        class FakeSession:
            def close(self):
                pass

        def run(_db, **_kwargs):
            entered.set()
            release.wait(1)
            return {
                "imported": 2,
                "skipped": 1,
                "updated": 0,
                "failed": 0,
                "remaining": 0,
                "total": 3,
            }

        ready = {
            "platform": "darwin",
            "available": True,
            "authorization": "authorized",
            "ready": True,
            "reason": "ready",
        }
        with (
            mock.patch("services.photokit.status", return_value=ready),
            mock.patch.object(photo_sync, "SessionLocal", return_value=FakeSession()),
            mock.patch.object(photo_sync, "sync_macos_library", side_effect=run),
        ):
            first = photo_sync.start_macos_sync(limit=10)
            self.assertTrue(entered.wait(1))
            second = photo_sync.start_macos_sync(limit=10)
            self.assertEqual(second["id"], first["id"])
            release.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                job = photo_sync.get_macos_sync_job(first["id"])
                if job["state"] == "complete":
                    break
                time.sleep(0.01)

        self.assertEqual(job["state"], "complete")
        self.assertEqual(job["imported"], 2)


if __name__ == "__main__":
    unittest.main()
