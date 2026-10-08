import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md

FIXTURES = Path(__file__).parent / "fixtures" / "markdown_preservation"


class MarkdownPreservationSpikeTest(unittest.TestCase):
    """Phase 6 safety proof. Every file lives in a throwaway vault."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-markdown-preservation-")
        self.root = Path(self.tmp.name)
        for source in FIXTURES.iterdir():
            shutil.copy2(source, self.root / source.name)
        (self.root / "bom-crlf.md").write_bytes(
            b"\xef\xbb\xbf---\r\ntitle: exact lines\r\n---\r\n\r\n# CRLF\r\n\r\nNo final newline"
        )
        (self.root / "large.md").write_bytes(
            ("# Large file\n\n" + ("0123456789abcdef\n" * 131_072)).encode("utf-8")
        )
        self.invalid = b"# mixed encoding\n[[unsafe]]\n\xff\xfe\x80owner bytes\n"
        (self.root / "invalid.md").write_bytes(self.invalid)
        self.patch = mock.patch.object(vault_md, "vault_dir", lambda: self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _bytes(self):
        return {p.name: p.read_bytes() for p in sorted(self.root.glob("*.md"))}

    def test_noop_visual_source_save_is_byte_for_byte_for_every_utf8_fixture(self):
        before = self._bytes()
        for name, original in before.items():
            if name == "invalid.md":
                continue
            opened = vault_md.read(name)
            self.assertTrue(opened["editable"], name)
            saved = vault_md.write(name, opened["content"], expected_hash=opened["hash"])
            self.assertEqual(saved["hash"], hashlib.sha256(original).hexdigest(), name)
            self.assertEqual((self.root / name).read_bytes(), original, name)

    def test_focused_edit_changes_only_the_selected_text(self):
        before = self._bytes()
        opened = vault_md.read("complex.md")
        updated = opened["content"].replace(
            "This owner note must stay exact.",
            "This owner note was intentionally updated.",
            1,
        )
        vault_md.write("complex.md", updated, expected_hash=opened["hash"])

        after = self._bytes()
        expected = before["complex.md"].replace(
            b"This owner note must stay exact.",
            b"This owner note was intentionally updated.",
            1,
        )
        self.assertEqual(after["complex.md"], expected)
        for name in before.keys() - {"complex.md"}:
            self.assertEqual(after[name], before[name], name)

    def test_invalid_utf8_is_protected_and_every_mutation_leaves_it_unchanged(self):
        opened = vault_md.read("invalid.md")
        self.assertTrue(opened["exists"])
        self.assertFalse(opened["editable"])
        self.assertEqual(opened["encoding"], "unsupported")
        self.assertEqual(opened["content"], "")

        with self.assertRaises(vault_md.DocumentEncodingError):
            vault_md.write("invalid.md", "replacement", expected_hash=opened["hash"])
        with self.assertRaises(vault_md.DocumentEncodingError):
            vault_md.set_task("invalid.md", 0, True)
        vault_md.rewrite_links("unsafe", "changed")
        self.assertEqual((self.root / "invalid.md").read_bytes(), self.invalid)

    def test_external_edit_blocks_a_stale_save_without_touching_either_copy(self):
        opened = vault_md.read("complex.md")
        external = opened["content"].replace("Preservation corpus", "Obsidian edit", 1)
        (self.root / "complex.md").write_text(external, encoding="utf-8")

        with self.assertRaises(vault_md.DocumentConflictError):
            vault_md.write("complex.md", opened["content"] + "\nlocal edit", opened["hash"])
        self.assertEqual((self.root / "complex.md").read_text("utf-8"), external)


if __name__ == "__main__":
    unittest.main()
