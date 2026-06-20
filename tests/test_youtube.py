import unittest

from services import youtube


class YoutubeIdTests(unittest.TestCase):
    def test_extracts_from_common_urls(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "dQw4w9WgXcQ": "dQw4w9WgXcQ",
        }
        for url, vid in cases.items():
            self.assertEqual(youtube.extract_video_id(url), vid, url)

    def test_rejects_non_youtube(self):
        self.assertIsNone(youtube.extract_video_id("https://example.com/watch?v=nope"))
        self.assertIsNone(youtube.extract_video_id("not a url"))
        self.assertIsNone(youtube.extract_video_id(""))

    def test_live_url_format(self):
        self.assertEqual(
            youtube.extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_v_path_format(self):
        self.assertEqual(
            youtube.extract_video_id("https://www.youtube.com/v/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_none_input(self):
        # None gets coerced to "" in the function via (url or "")
        self.assertIsNone(youtube.extract_video_id(None))

    def test_raw_id_eleven_chars(self):
        self.assertEqual(youtube.extract_video_id("abcdefghijk"), "abcdefghijk")

    def test_raw_id_twelve_chars_rejected(self):
        self.assertIsNone(youtube.extract_video_id("abcdefghijkl"))

    def test_raw_id_ten_chars_rejected(self):
        self.assertIsNone(youtube.extract_video_id("abcdefghij"))

    def test_raw_id_with_underscore_hyphen(self):
        self.assertEqual(youtube.extract_video_id("aB3-_cD4eF5"), "aB3-_cD4eF5")

    def test_url_with_extra_query_params(self):
        url = "https://www.youtube.com/watch?list=PLabc&v=dQw4w9WgXcQ&index=3"
        self.assertEqual(youtube.extract_video_id(url), "dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
