import unittest
from services.automations import _render


class RenderTests(unittest.TestCase):
    def test_substitutes_known(self):
        self.assertEqual(_render("{name} renews in {days}", {"name": "Netflix", "days": 3}),
                         "Netflix renews in 3")

    def test_unknown_placeholder_left_as_is(self):
        self.assertEqual(_render("hi {who}", {"name": "x"}), "hi {who}")

    def test_empty_template(self):
        self.assertEqual(_render("", {"name": "x"}), "")

    def test_no_placeholders(self):
        self.assertEqual(_render("just text", {}), "just text")


if __name__ == "__main__":
    unittest.main()
