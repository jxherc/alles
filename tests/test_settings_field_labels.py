"""Settings fields must have persistent accessible names, not just placeholders."""

import unittest
from html.parser import HTMLParser
from pathlib import Path


class Element:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def text(self):
        return " ".join(c.text() if isinstance(c, Element) else c for c in self.children).strip()


class Document(HTMLParser):
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, html):
        super().__init__()
        self.root = Element("document", [])
        self.stack = [self.root]
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        self.elements.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def name(self, field):
        attrs = field.attrs
        by_id = {e.attrs.get("id"): e for e in self.elements if e.attrs.get("id")}
        if attrs.get("aria-labelledby"):
            return " ".join(
                by_id[id_].text() for id_ in attrs["aria-labelledby"].split() if id_ in by_id
            )
        if attrs.get("aria-label"):
            return attrs["aria-label"].strip()
        labels = [
            e
            for e in self.elements
            if e.tag == "label" and e.attrs.get("for") == attrs.get("id") and attrs.get("id")
        ]
        parent = field.parent
        while parent:
            if parent.tag == "label":
                labels.append(parent)
            parent = parent.parent
        return " ".join(label.text() for label in labels)


class SettingsFieldLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = Document(
            (Path(__file__).resolve().parents[1] / "static/index.html").read_text()
        )
        cls.fields = []
        for element in cls.document.elements:
            if element.tag not in {"input", "textarea", "select"} or element.attrs.get("type") in {
                "hidden",
                "file",
            }:
                continue
            ancestor = element.parent
            while ancestor and ancestor.attrs.get("id") != "settings-modal":
                ancestor = ancestor.parent
            if ancestor:
                cls.fields.append(element)

    def test_all_settings_entry_fields_have_persistent_names(self):
        self.assertGreater(len(self.fields), 70, "the complete Settings form must be inspected")
        for field in self.fields:
            with self.subTest(field=field.attrs.get("id", field.attrs.get("data-shortcut"))):
                self.assertTrue(
                    self.document.name(field),
                    "add an associated label; placeholders disappear while typing",
                )

    def test_quiet_hours_have_distinct_names(self):
        fields = {field.attrs.get("id"): field for field in self.fields}
        names = [
            self.document.name(fields[id_]).lower() for id_ in ("s-prox-qstart", "s-prox-qend")
        ]
        self.assertIn("start", names[0])
        self.assertIn("end", names[1])
        self.assertNotEqual(*names)

    def test_shortcut_names_include_the_visible_label(self):
        for field in self.fields:
            if not field.attrs.get("data-shortcut"):
                continue
            label = next(
                child
                for child in field.parent.children
                if isinstance(child, Element) and child.tag == "label"
            )
            with self.subTest(shortcut=field.attrs["data-shortcut"]):
                self.assertIn(label.text().lower(), self.document.name(field).lower())

    def test_settings_field_ids_have_unambiguous_label_targets(self):
        for field in self.fields:
            id_ = field.attrs.get("id")
            if id_:
                with self.subTest(id=id_):
                    matches = [
                        element
                        for element in self.document.elements
                        if element.attrs.get("id") == id_
                    ]
                    self.assertEqual(
                        matches, [field], "a label must resolve to its one entry field"
                    )


if __name__ == "__main__":
    unittest.main()
