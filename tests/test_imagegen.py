import base64
import unittest
from services.imagegen import _b64_images


class ImageGenTests(unittest.TestCase):
    def test_extracts_b64_images(self):
        data = {"data": [
            {"b64_json": base64.b64encode(b"PNGBYTES").decode()},
            {"b64_json": base64.b64encode(b"second").decode()},
        ]}
        self.assertEqual(_b64_images(data), [b"PNGBYTES", b"second"])

    def test_url_only_yields_nothing(self):
        self.assertEqual(_b64_images({"data": [{"url": "http://x/img.png"}]}), [])

    def test_empty_and_none(self):
        self.assertEqual(_b64_images({}), [])
        self.assertEqual(_b64_images(None), [])

    def test_bad_b64_skipped(self):
        self.assertEqual(_b64_images({"data": [{"b64_json": "!!!notb64"}]}), [])


if __name__ == "__main__":
    unittest.main()
