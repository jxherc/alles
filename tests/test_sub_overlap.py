import unittest
from types import SimpleNamespace

from services import sub_overlap


def _sub(name, price=1, active=True):
    return SimpleNamespace(id=name, name=name, price=price, active=active)


class SubOverlapTests(unittest.TestCase):
    def test_service_category_uses_whole_words(self):
        self.assertEqual(sub_overlap._service_cat("Dropbox Plus"), "cloud")
        self.assertEqual(sub_overlap._service_cat("Apple Music Family"), "music")
        self.assertEqual(sub_overlap._service_cat("Boxed Water"), "")
        self.assertEqual(sub_overlap._service_cat("Maxim Magazine"), "")

    def test_overlaps_ignores_substring_false_matches(self):
        groups = sub_overlap.overlaps([
            _sub("Boxed Water", 9),
            _sub("Maxim Magazine", 6),
            _sub("Dropbox", 12),
            _sub("Google Drive", 3),
        ])

        self.assertEqual([g["category"] for g in groups], ["cloud"])
        self.assertEqual({s["name"] for s in groups[0]["subs"]}, {"Dropbox", "Google Drive"})


if __name__ == "__main__":
    unittest.main()
