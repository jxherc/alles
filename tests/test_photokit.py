"""Contract tests for the signed native PhotoKit helper adapter.

All helper processes are mocked. These tests never prompt for or read the
machine's real Photos library.
"""

import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from services import photokit


class PhotoKitStatusTest(unittest.TestCase):
    def test_status_is_import_safe_off_macos(self):
        with mock.patch.object(photokit.sys, "platform", "linux"):
            result = photokit.status()
        self.assertFalse(result["available"])
        self.assertEqual(result["authorization"], "unavailable")

    def test_unbuilt_helper_is_available_without_building_or_prompting(self):
        with (
            mock.patch.object(photokit, "_support_reason", return_value=None),
            mock.patch.object(photokit, "_binary_path", return_value=Path("/missing/helper")),
            mock.patch.object(photokit, "_source_digest", return_value="new"),
            mock.patch.object(photokit, "_built_digest", return_value=""),
            mock.patch.object(photokit, "_run_helper") as run,
        ):
            result = photokit.status()
        self.assertTrue(result["available"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["authorization"], "not_determined")
        run.assert_not_called()

    def test_built_helper_maps_every_authorization_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "helper"
            binary.touch()
            for state, ready in (
                ("not_determined", False),
                ("restricted", False),
                ("denied", False),
                ("authorized", True),
                ("limited", True),
            ):
                with (
                    self.subTest(state),
                    mock.patch.object(photokit, "_support_reason", return_value=None),
                    mock.patch.object(photokit, "_binary_path", return_value=binary),
                    mock.patch.object(photokit, "_source_digest", return_value="same"),
                    mock.patch.object(photokit, "_built_digest", return_value="same"),
                    mock.patch.object(
                        photokit, "_run_helper", return_value={"authorization": state}
                    ),
                ):
                    result = photokit.status()
                self.assertEqual(result["authorization"], state)
                self.assertIs(result["ready"], ready)


class PhotoKitAuthorizationTest(unittest.TestCase):
    def test_authorization_builds_helper_only_after_explicit_action(self):
        with mock.patch.object(
            photokit,
            "_run_helper",
            return_value={"authorization": "authorized"},
        ) as run:
            self.assertEqual(photokit.ensure_authorized(), "authorized")
        run.assert_called_once_with(["authorize"], build=True, timeout=75)

    def test_authorization_accepts_limited_access(self):
        with mock.patch.object(photokit, "_run_helper", return_value={"authorization": "limited"}):
            self.assertEqual(photokit.ensure_authorized(), "limited")

    def test_authorization_rejects_denied_and_restricted(self):
        for state in ("denied", "restricted"):
            with (
                self.subTest(state),
                mock.patch.object(photokit, "_run_helper", return_value={"authorization": state}),
                self.assertRaises(photokit.PhotoKitPermissionError),
            ):
                photokit.ensure_authorized()


class PhotoKitBuildTest(unittest.TestCase):
    def test_helper_bundle_declares_usage_description_and_entitlement(self):
        info = photokit._INFO.read_text("utf-8")
        entitlements = photokit._ENTITLEMENTS.read_text("utf-8")
        self.assertIn("NSPhotoLibraryUsageDescription", info)
        self.assertIn("Hidden items are excluded", info)
        self.assertIn("com.apple.security.personal-information.photos-library", entitlements)

    def test_helper_prefers_current_nondestructive_edits_and_keeps_live_motion(self):
        source = photokit._SOURCE.read_text("utf-8")
        self.assertIn("first([5, 1, 8, 4, 19])", source)
        self.assertIn("first([6, 2, 12])", source)
        self.assertIn("first([10, 9, 11])", source)
        self.assertIn("includeHiddenAssets = false", source)
        self.assertIn("requestData(", source)
        self.assertIn("cancelDataRequest(requestID)", source)

    def test_build_creates_and_signs_a_scoped_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "native" / "AllesPhotoKitBridge.app"
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if "swiftc" in command:
                    output = Path(command[command.index("-o") + 1])
                    output.write_bytes(b"helper")
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")

            with (
                mock.patch.object(photokit.sys, "platform", "darwin"),
                mock.patch.object(photokit, "_app_path", return_value=app),
                mock.patch.object(
                    photokit,
                    "_binary_path",
                    side_effect=lambda: app / "Contents" / "MacOS" / "AllesPhotoKitBridge",
                ),
                mock.patch.object(photokit, "_tool", side_effect=lambda name: f"/usr/bin/{name}"),
                mock.patch.object(photokit, "_signing_identity", return_value=""),
                mock.patch.object(photokit.subprocess, "run", side_effect=fake_run),
            ):
                binary = photokit._ensure_helper()

            self.assertTrue(binary.is_file())
            self.assertTrue((app / "Contents" / "Info.plist").is_file())
            self.assertTrue(any("swiftc" in command for command in calls))
            compile_command = next(command for command in calls if "swiftc" in command)
            self.assertIn("-target", compile_command)
            self.assertTrue(
                compile_command[compile_command.index("-target") + 1].endswith("macosx11.0")
            )
            sign = next(command for command in calls if command[0].endswith("codesign"))
            self.assertIn("--entitlements", sign)
            self.assertEqual(sign[sign.index("--sign") + 1], "-")
            self.assertIn("runtime", sign)


class PhotoKitResourceTest(unittest.TestCase):
    def test_list_converts_helper_records_to_stable_resources(self):
        rows = [
            {
                "source_id": "A0199/L0/001:photo",
                "asset_id": "A0199/L0/001",
                "kind": "photo",
                "original_name": "../IMG_0199.HEIC",
                "taken_at": "2024-03-04T05:06:07.000Z",
                "modified_at": "2024-03-05T06:07:08.000Z",
                "favorite": True,
                "hidden": False,
                "width": 4032,
                "height": 3024,
                "lat": 25.033,
                "lon": 121.5654,
                "live_photo": True,
            }
        ]
        with mock.patch.object(photokit, "_run_helper", return_value=rows) as run:
            resources = photokit.iter_resources()
        run.assert_called_once_with(["list"], build=True, timeout=180)
        item = resources[0]
        self.assertEqual(item.source_id, "A0199/L0/001:photo")
        self.assertEqual(item.original_name, "IMG_0199.HEIC")
        expected = (
            datetime.fromisoformat("2024-03-04T05:06:07+00:00").astimezone().replace(tzinfo=None)
        )
        self.assertEqual(item.taken_at, expected)
        self.assertEqual(item.exif["lat"], 25.033)
        self.assertTrue(item.exif["live_photo"])

    def test_malformed_helper_rows_are_skipped(self):
        with mock.patch.object(photokit, "_run_helper", return_value=[{}, None]):
            self.assertEqual(photokit.iter_resources(), [])

    def test_export_uses_asset_identity_and_cleans_up_failures(self):
        item = photokit.PhotoKitResource(
            source_id="A1:photo",
            asset_id="A1",
            kind="photo",
            original_name="IMG_1.HEIC",
            taken_at=None,
            modified_at=None,
            favorite=False,
            hidden=False,
            width=1,
            height=1,
            exif={},
            resource=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "IMG_1.HEIC"

            def export(_item, _path, _timeout):
                destination.write_bytes(b"heic")

            with mock.patch.object(photokit, "_export_via_session", side_effect=export):
                self.assertEqual(photokit.export_resource(item, destination), destination)

            destination.write_bytes(b"partial")
            with (
                mock.patch.object(
                    photokit,
                    "_export_via_session",
                    side_effect=photokit.PhotoKitExportError("failed"),
                ),
                self.assertRaises(photokit.PhotoKitExportError),
            ):
                photokit.export_resource(item, destination)
            self.assertFalse(destination.exists())

    def test_timeout_response_stops_the_persistent_export_process(self):
        process = _FakeExportProcess('{"ok":false,"error":"timeout"}\n')
        item = _resource()
        photokit._EXPORT_PROCESS = process
        try:
            with (
                mock.patch.object(
                    photokit.select, "select", return_value=([process.stdout], [], [])
                ),
                self.assertRaises(photokit.PhotoKitTimeoutError),
            ):
                photokit._export_via_session(item, Path("/tmp/ignored"), 1)
        finally:
            photokit._EXPORT_PROCESS = None
        self.assertTrue(process.terminated)

    def test_non_object_response_stops_the_persistent_export_process(self):
        process = _FakeExportProcess("[]\n")
        item = _resource()
        photokit._EXPORT_PROCESS = process
        try:
            with (
                mock.patch.object(
                    photokit.select, "select", return_value=([process.stdout], [], [])
                ),
                self.assertRaises(photokit.PhotoKitExportError),
            ):
                photokit._export_via_session(item, Path("/tmp/ignored"), 1)
        finally:
            photokit._EXPORT_PROCESS = None
        self.assertTrue(process.terminated)


class _FakeExportProcess:
    def __init__(self, response):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(response)
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def _resource():
    return photokit.PhotoKitResource(
        source_id="A1:photo",
        asset_id="A1",
        kind="photo",
        original_name="IMG_1.HEIC",
        taken_at=None,
        modified_at=None,
        favorite=False,
        hidden=False,
        width=1,
        height=1,
        exif={},
        resource=None,
    )


if __name__ == "__main__":
    unittest.main()
