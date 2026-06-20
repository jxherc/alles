import base64
import unittest

from services.imagegen import _b64_images, image_models, is_image_model


class ImageGenTests(unittest.TestCase):
    def test_extracts_b64_images(self):
        data = {
            "data": [
                {"b64_json": base64.b64encode(b"PNGBYTES").decode()},
                {"b64_json": base64.b64encode(b"second").decode()},
            ]
        }
        self.assertEqual(_b64_images(data), [b"PNGBYTES", b"second"])

    def test_url_only_yields_nothing(self):
        self.assertEqual(_b64_images({"data": [{"url": "http://x/img.png"}]}), [])

    def test_empty_and_none(self):
        self.assertEqual(_b64_images({}), [])
        self.assertEqual(_b64_images(None), [])

    def test_bad_b64_skipped(self):
        self.assertEqual(_b64_images({"data": [{"b64_json": "!!!notb64"}]}), [])

    def test_mixed_good_and_bad_b64(self):
        good = base64.b64encode(b"ok").decode()
        data = {"data": [{"b64_json": "!!!bad"}, {"b64_json": good}]}
        self.assertEqual(_b64_images(data), [b"ok"])

    def test_empty_data_list(self):
        self.assertEqual(_b64_images({"data": []}), [])

    def test_is_image_model_dalle(self):
        self.assertTrue(is_image_model("dall-e-3"))
        self.assertTrue(is_image_model("dalle-2"))

    def test_is_image_model_flux(self):
        self.assertTrue(is_image_model("flux-dev"))
        self.assertTrue(is_image_model("FLUX.1-schnell"))

    def test_is_image_model_stable_diffusion(self):
        self.assertTrue(is_image_model("stable-diffusion-xl"))
        self.assertTrue(is_image_model("sdxl-turbo"))

    def test_is_not_image_model(self):
        self.assertFalse(is_image_model("gpt-4o"))
        self.assertFalse(is_image_model("llama3.2:3b"))
        self.assertFalse(is_image_model("claude-3-5-sonnet"))

    def test_image_models_filters_list(self):
        models = ["gpt-4o", "dall-e-3", "llama3.1:8b", "flux-dev"]
        result = image_models(models)
        self.assertEqual(result, ["dall-e-3", "flux-dev"])

    def test_image_models_empty_list(self):
        self.assertEqual(image_models([]), [])
        self.assertEqual(image_models(None), [])


if __name__ == "__main__":
    unittest.main()
