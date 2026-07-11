import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from core.database import Photo, TrashItem
from tests._client import ApiTest

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text("utf-8")
PHOTOS_JS = (ROOT / "static" / "js" / "photos.js").read_text("utf-8")
SETTINGS_JS = (ROOT / "static" / "js" / "settings.js").read_text("utf-8")
SW = (ROOT / "static" / "sw.js").read_text("utf-8")


class PhotoKitGalleryUiTest(unittest.TestCase):
    def test_gallery_has_a_mac_only_apple_photos_action(self):
        self.assertIn('id="photos-macos-btn"', INDEX)
        self.assertRegex(INDEX, r'id="photos-macos-btn"[^>]*hidden')
        self.assertIn("status.platform === 'darwin'", PHOTOS_JS)

    def test_action_starts_and_polls_a_background_import(self):
        self.assertIn("await dlgConfirm", PHOTOS_JS)
        self.assertIn("hidden items stay excluded", PHOTOS_JS)
        self.assertIn("/api/photos/sync/macos?limit=${_MAC_IMPORT_BATCH}", PHOTOS_JS)
        self.assertIn("/api/photos/sync/macos/jobs/", PHOTOS_JS)
        self.assertIn("job.state === 'queued' || job.state === 'running'", PHOTOS_JS)

    def test_action_recovers_and_refreshes_the_gallery(self):
        self.assertIn("await loadPhotos();", PHOTOS_JS)
        self.assertIn("await _loadMacPhotosStatus();", PHOTOS_JS)
        self.assertIn("btn.disabled = !status.available", PHOTOS_JS)

    def test_partial_failures_are_visible_and_not_styled_as_success(self):
        self.assertIn("job.failed ? 'error' : 'success'", PHOTOS_JS)
        self.assertIn("${job.failed} failed", PHOTOS_JS)

    def test_native_import_is_never_replayed_from_the_offline_outbox(self):
        noqueue = SW[SW.index("const NOQUEUE") : SW.index(";", SW.index("const NOQUEUE"))]
        self.assertIn("'/api/photos/sync'", noqueue)
        self.assertIn("'/api/photos/rescan'", noqueue)

    def test_global_status_distinguishes_installation_from_permission(self):
        self.assertIn("cap.photokit_authorization", SETTINGS_JS)
        self.assertIn("cap.photokit_ready", SETTINGS_JS)


class PhotoKitGalleryApiTest(ApiTest):
    def test_hiding_a_live_photo_hides_its_motion_from_search(self):
        db = self.db()
        still = Photo(
            filename="still.heic",
            original_name="private-still.heic",
            source="apple_photos",
            source_id="asset-private:photo",
            source_asset_id="asset-private",
        )
        motion = Photo(
            filename="motion.mov",
            original_name="private-motion.mov",
            is_video=True,
            source="apple_photos",
            source_id="asset-private:paired_video",
            source_asset_id="asset-private",
        )
        db.add_all([still, motion])
        db.commit()
        still_id, motion_id = still.id, motion.id
        db.close()

        response = self.client.patch(f"/api/photos/{still_id}", json={"hidden": True})

        self.assertEqual(response.status_code, 200)
        db = self.db()
        self.assertTrue(all(db.get(Photo, pid).hidden for pid in (still_id, motion_id)))
        db.close()
        self.assertEqual(self.client.get("/api/photos/search?q=private-motion").json()["count"], 0)

        response = self.client.post(
            "/api/photos/batch", json={"ids": [still_id], "action": "unhide"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        db = self.db()
        self.assertTrue(all(not db.get(Photo, pid).hidden for pid in (still_id, motion_id)))
        db.close()

    def test_live_photo_delete_and_restore_keep_the_native_pair_together(self):
        db = self.db()
        still = Photo(
            filename="still.heic",
            source="apple_photos",
            source_id="asset-live:photo",
            source_asset_id="asset-live",
            taken_at=datetime(2024, 5, 3),
        )
        motion = Photo(
            filename="motion.mov",
            is_video=True,
            source="apple_photos",
            source_id="asset-live:paired_video",
            source_asset_id="asset-live",
            taken_at=datetime(2024, 5, 3),
        )
        db.add_all([still, motion])
        db.flush()
        still.stack_id = still.id
        motion.stack_id = still.id
        still_id, motion_id = still.id, motion.id
        db.commit()
        db.close()

        response = self.client.delete(f"/api/photos/{still_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        db = self.db()
        self.assertTrue(all(db.get(Photo, pid).deleted_at for pid in (still_id, motion_id)))
        self.assertEqual(
            db.query(TrashItem).filter(TrashItem.ref.in_([still_id, motion_id])).count(), 2
        )
        db.close()

        response = self.client.post(f"/api/photos/{motion_id}/restore")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        db = self.db()
        self.assertTrue(all(db.get(Photo, pid).deleted_at is None for pid in (still_id, motion_id)))
        self.assertEqual(
            db.query(TrashItem).filter(TrashItem.ref.in_([still_id, motion_id])).count(), 0
        )
        db.close()

    def test_status_route_does_not_request_authorization(self):
        fake = {
            "platform": "darwin",
            "available": True,
            "authorization": "not_determined",
            "ready": False,
            "reason": "permission will be requested when you import",
        }
        with mock.patch("services.photokit.status", return_value=fake):
            response = self.client.get("/api/photos/sync/macos/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authorization"], "not_determined")
        self.assertIsNone(response.json()["job"])

    def test_start_route_returns_accepted_job(self):
        job = {"id": "job-1", "state": "queued"}
        with mock.patch("services.photo_sync.start_macos_sync", return_value=job) as start:
            response = self.client.post("/api/photos/sync/macos")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), job)
        start.assert_called_once_with(500)

    def test_job_route_reports_missing_job(self):
        with mock.patch("services.photo_sync.get_macos_sync_job", return_value=None):
            response = self.client.get("/api/photos/sync/macos/jobs/missing")
        self.assertEqual(response.status_code, 404)

    def test_off_mac_start_still_fails_loud(self):
        if sys.platform == "darwin":
            self.skipTest("non-mac contract")
        response = self.client.post("/api/photos/sync/macos")
        self.assertEqual(response.status_code, 501)


if __name__ == "__main__":
    unittest.main()
