"""index.html structural integrity — every top-level page-view (and the chat composer) must be a direct
child of <main>, NOT nested inside another view. A missing </div> on #wiki-view once trapped vault /
contacts / mail / photos / the composer inside the (hidden) docs view, so they rendered black."""

import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []  # (tag, id)
        self.parent_of = {}  # id -> parent id (or tag)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        eid = d.get("id")
        if eid:
            parent = next((s[1] or s[0] for s in reversed(self.stack)), None)
            self.parent_of[eid] = parent
        if tag not in (
            "br",
            "img",
            "input",
            "hr",
            "meta",
            "link",
            "source",
            "path",
            "circle",
            "line",
            "rect",
            "polyline",
            "polygon",
            "use",
            "stop",
        ):
            self.stack.append((tag, eid))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


class IndexStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = _Tree()
        cls.t.feed(HTML)

    def _not_inside_wiki(self, eid):
        # walk up the parent chain; none should be wiki-view
        seen, cur = [], eid
        while cur and cur not in seen:
            seen.append(cur)
            cur = self.t.parent_of.get(cur)
            self.assertNotEqual(cur, "wiki-view", f"#{eid} is nested inside #wiki-view")

    def test_composer_not_inside_docs_view(self):
        self.assertIn("composer-outer", self.t.parent_of)
        self._not_inside_wiki("composer-outer")

    def test_app_views_not_inside_docs_view(self):
        for vid in (
            "vault-view",
            "contacts-view",
            "files-view",
            "mail-view",
            "photos-view",
            "compare-view",
        ):
            self.assertIn(vid, self.t.parent_of)
            self._not_inside_wiki(vid)

    def test_wiki_view_closes(self):
        # the explicit close marker we added stays as a guard
        self.assertIn("/#wiki-view", HTML)


if __name__ == "__main__":
    unittest.main()
