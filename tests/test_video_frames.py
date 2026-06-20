import unittest
from unittest import mock

from services import video_frames as vf


class VideoDetectTests(unittest.TestCase):
    def test_is_video_by_mime(self):
        self.assertTrue(vf.is_video("video/mp4", "clip.bin"))

    def test_is_video_by_ext(self):
        self.assertTrue(vf.is_video("application/octet-stream", "clip.mov"))
        self.assertTrue(vf.is_video("", "movie.webm"))

    def test_not_video(self):
        self.assertFalse(vf.is_video("image/png", "a.png"))
        self.assertFalse(vf.is_video("text/plain", "notes.txt"))


class SampleTimesTests(unittest.TestCase):
    def test_sample_times_even(self):
        ts = vf._sample_times(100.0, 5)
        self.assertEqual(len(ts), 5)
        self.assertTrue(all(0 <= t <= 100 for t in ts))
        self.assertEqual(ts, sorted(ts))

    def test_sample_times_capped(self):
        ts = vf._sample_times(100.0, 9999)
        self.assertLessEqual(len(ts), vf.MAX_FRAMES)

    def test_sample_times_short(self):
        ts = vf._sample_times(0.0, 8)
        self.assertTrue(len(ts) >= 1)  # zero/unknown duration still yields at least one grab


class ExtractTests(unittest.TestCase):
    def test_extract_missing_file_empty(self):
        self.assertEqual(vf.extract_frames("/no/such/file.mp4"), [])

    def test_extract_no_ffmpeg_empty(self):
        # if ffmpeg can't be found, we degrade to no frames rather than raising
        with mock.patch.object(vf, "_have_ffmpeg", return_value=False):
            with mock.patch.object(vf.os.path, "isfile", return_value=True):
                self.assertEqual(vf.extract_frames("anything.mp4"), [])

    def test_frame_data_url_shape(self):
        # stub the actual ffmpeg grab; assert we wrap bytes as proper data URLs
        with (
            mock.patch.object(vf, "_have_ffmpeg", return_value=True),
            mock.patch.object(vf.os.path, "isfile", return_value=True),
            mock.patch.object(vf, "_probe_duration", return_value=10.0),
            mock.patch.object(vf, "_grab_frame", return_value=b"\xff\xd8jpegbytes"),
        ):
            urls = vf.extract_frames("clip.mp4", n=3)
        self.assertEqual(len(urls), 3)
        self.assertTrue(all(u.startswith("data:image/jpeg;base64,") for u in urls))

    def test_max_frames_enforced(self):
        with (
            mock.patch.object(vf, "_have_ffmpeg", return_value=True),
            mock.patch.object(vf.os.path, "isfile", return_value=True),
            mock.patch.object(vf, "_probe_duration", return_value=600.0),
            mock.patch.object(vf, "_grab_frame", return_value=b"\xff\xd8x"),
        ):
            urls = vf.extract_frames("clip.mp4", n=9999)
        self.assertLessEqual(len(urls), vf.MAX_FRAMES)


if __name__ == "__main__":
    unittest.main()
