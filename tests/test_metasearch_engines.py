import unittest

from services.research import search as search_service


class MetasearchEnginesTest(unittest.TestCase):
    def test_keyless_metasearch_skips_engines_that_only_return_captchas(self):
        backends = search_service._text_backends()["backend"].split(",")
        self.assertNotIn("startpage", backends)
        self.assertIn("duckduckgo", backends)
        self.assertEqual(backends[0], "wikipedia")

    def test_startpage_is_not_a_search_engine_option(self):
        self.assertNotIn("startpage", search_service._KNOWN_PROVIDERS)


if __name__ == "__main__":
    unittest.main()
