"""ui-8e (frontend contract) — the visual custom-type editor + the form consuming custom types.
Backend custom-type CRUD is covered by tests/test_vault_custom_types.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class VaultTypesUi(unittest.TestCase):
    def test_custom_types_loaded(self):
        self.assertIn("let _customTypes", JS)
        self.assertIn("function _loadCustomTypes", JS)
        self.assertIn("/api/vault/custom-types", JS)

    def test_form_uses_all_types(self):
        # the type picker lists built-in + custom, and fields resolve via defs
        self.assertIn("function _allTypes", JS)
        self.assertIn("_allTypes().map", JS)
        self.assertIn("function _defOf", JS)

    def test_editor_present(self):
        self.assertIn("function _renderTypeEditor", JS)
        self.assertIn("function _editType", JS)
        self.assertIn("function _renderTypeForm", JS)
        self.assertIn("function _saveType", JS)

    def test_editor_has_width_and_kind_controls(self):
        self.assertIn("vt-width", JS)
        self.assertIn("vt-kind", JS)
        self.assertIn("['full', 'half', 'third']", JS)
        self.assertIn("['text', 'secret', 'password', 'textarea']", JS)

    def test_add_remove_fields(self):
        self.assertIn("vt-addf", JS)
        self.assertIn("vt-rmf", JS)
        self.assertIn("_vtDraft.fields.push", JS)
        self.assertIn("_vtDraft.fields.splice", JS)

    def test_save_puts_to_backend(self):
        self.assertIn("function _saveType", JS)
        self.assertIn("/api/vault/custom-types/${key}`", JS)
        # the save call PUTs the {label, fields} body
        self.assertIn("JSON.stringify({ label, fields })", JS)

    def test_css_for_editor(self):
        self.assertRegex(CSS, r"\.vt-field\b")
        self.assertRegex(CSS, r"\.vt-form\b")


if __name__ == "__main__":
    unittest.main()
