"""ui-7a — contacts header de-iconed + aligned, list/detail rebuilt with the central icon set.
Behavioral check in docs/evidence/ui-7a/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "contacts.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _head():
    i = INDEX.index('class="page-view-head contacts-head"')
    return INDEX[i : INDEX.index("page-view-body", i)]


class ContactsRebuild(unittest.TestCase):
    def test_top_buttons_de_iconed(self):
        head = _head()
        self.assertIn(">favorites</button>", head)
        self.assertIn(">birthdays</button>", head)
        # the old emoji labels are gone
        self.assertNotIn("★", head)
        self.assertNotIn("🎂", head)

    def test_header_has_scoped_class(self):
        self.assertIn('class="page-view-head contacts-head"', INDEX)
        self.assertRegex(CSS, r"\.contacts-head\s*\{")

    def test_list_row_layout_rebuilt(self):
        self.assertIn("contact-rowmain", JS)
        self.assertIn("contact-rowacts", JS)
        self.assertRegex(CSS, r"\.contact-rowmain\s*\{[^}]*flex-direction:\s*column")
        self.assertRegex(CSS, r"\.contact-item\s*\{[^}]*display:\s*flex")

    def test_per_row_star_is_icon(self):
        self.assertIn("_si(c.favorite ? 'star-fill' : 'star')", JS)
        self.assertNotIn("'★'", JS)
        self.assertNotIn("'☆'", JS)

    def test_detail_and_birthday_glyphs_unified(self):
        self.assertIn("_si('cake')", JS)  # birthday rows
        self.assertIn("_si('map-pin')", JS)  # detail map link
        self.assertIn("_si('chevron-left')", JS)  # back buttons
        self.assertIn("_si('check')", JS)  # "this is me"

    def test_uses_central_icon_helper(self):
        self.assertIn("window.icon", JS)
        self.assertRegex(JS, r"_si\s*=\s*n\s*=>")


if __name__ == "__main__":
    unittest.main()
