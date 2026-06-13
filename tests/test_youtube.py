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


if __name__ == "__main__":
    unittest.main()
