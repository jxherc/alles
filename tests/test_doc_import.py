import io
import struct
import subprocess
import sys
import textwrap
import unittest
import zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from services import doc_import


class DocImportTests(unittest.TestCase):
    def test_txt_passthrough(self):
        r = doc_import.import_document("my notes.txt", b"hello world")
        self.assertEqual(r["name"], "my notes")
        self.assertIn("hello world", r["content"])

    def test_md_passthrough(self):
        r = doc_import.import_document("a.md", b"# Title\n\n- x")
        self.assertIn("# Title", r["content"])

    def test_html_to_md(self):
        html = (
            "<html><head><style>.x{color:red}</style></head><body>"
            "<h1>Hi</h1><p>a <strong>bold</strong> word and "
            "<a href='http://e.com'>link</a></p>"
            "<ul><li>one</li><li>two</li></ul></body></html>"
        )
        c = doc_import.import_document("page.html", html.encode())["content"]
        self.assertIn("# Hi", c)
        self.assertIn("**bold**", c)
        self.assertIn("[link](http://e.com)", c)
        self.assertIn("- one", c)
        self.assertNotIn("color:red", c)  # <style> stripped

    def test_docx_to_md(self):
        from docx import Document

        doc = Document()
        doc.add_heading("Heading One", level=1)
        doc.add_paragraph("a normal paragraph")
        doc.add_paragraph("bullet item", style="List Bullet")
        buf = io.BytesIO()
        doc.save(buf)
        c = doc_import.import_document("d.docx", buf.getvalue())["content"]
        self.assertIn("# Heading One", c)
        self.assertIn("a normal paragraph", c)
        self.assertIn("- bullet item", c)

    def test_docx_checks_actual_inflation_before_document_parser(self):
        fixture = io.BytesIO()
        with zipfile.ZipFile(fixture, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("tiny.xml", b"x" * 1024)
        data = bytearray(fixture.getvalue())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<I", data, central + 24, 1)
        struct.pack_into("<I", data, 22, 1)
        with mock.patch("docx.Document") as parser:
            with self.assertRaisesRegex(ValueError, "size|expanded"):
                doc_import.import_document("local.docx", bytes(data))
            parser.assert_not_called()

    def test_docx_stored_archive_still_preserves_content(self):
        from docx import Document

        document = Document()
        document.add_paragraph("ordinary stored article")
        source, stored = io.BytesIO(), io.BytesIO()
        document.save(source)
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(stored, "w") as target:
            for item in original.infolist():
                target.writestr(item.filename, original.read(item))
        self.assertEqual(
            doc_import.import_document("stored.docx", stored.getvalue())["content"],
            "ordinary stored article\n",
        )

    def test_head_only_html_is_empty_instead_of_markdown_markers(self):
        with self.assertRaisesRegex(ValueError, "no readable text"):
            doc_import.import_document(
                "empty.html", b"<head><title><b>metadata</b></title><style>hidden</style></head>"
            )

    def test_pdf_page_failure_rejects_partial_extraction(self):
        reader = mock.Mock()
        reader.pages = [mock.Mock(), mock.Mock()]
        reader.pages[0].extract_text.return_value = "first page text"
        reader.pages[1].extract_text.side_effect = ValueError("synthetic page failure")
        with mock.patch.dict(
            "sys.modules", {"pypdf": mock.Mock(PdfReader=mock.Mock(return_value=reader))}
        ):
            with self.assertRaisesRegex(ValueError, "every PDF page"):
                doc_import._extract_pdf(b"synthetic local fixture")

    def test_pdf_stops_at_cumulative_output_budget(self):
        reader = mock.Mock()
        reader.pages = [mock.Mock() for _ in range(3)]
        for page in reader.pages:
            page.extract_text.return_value = "é" * 10
        with (
            mock.patch.dict(
                "sys.modules", {"pypdf": mock.Mock(PdfReader=mock.Mock(return_value=reader))}
            ),
            mock.patch.object(doc_import, "MAX_TEXT_BYTES", 32, create=True),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                doc_import._extract_pdf(b"small synthetic fixture")
        reader.pages[0].extract_text.assert_called_once()
        reader.pages[1].extract_text.assert_called_once()
        reader.pages[2].extract_text.assert_not_called()

    def test_docx_merged_cells_stop_before_oversized_markdown_row(self):
        from docx import Document

        document = Document()
        table = document.add_table(rows=1, cols=4)
        table.cell(0, 0).merge(table.cell(0, 3)).text = "small text " * 4
        data = io.BytesIO()
        document.save(data)
        with mock.patch.object(doc_import, "MAX_TEXT_BYTES", 64):
            with self.assertRaisesRegex(doc_import.DocumentTooLarge, "exceeds"):
                doc_import.import_document("small.docx", data.getvalue())

    def test_html_implicit_head_close_keeps_body_and_skips_scripts(self):
        source = b"<html><head><title>title only</title><style>b{color:red}</style><body><p>Report</p><script>hidden()</script></body></html>"
        self.assertEqual(doc_import.import_document("report.html", source)["content"], "Report\n")

    def test_html_checks_cumulative_output_while_consuming_elements(self):
        with mock.patch.object(doc_import, "MAX_TEXT_BYTES", 32):
            with self.assertRaisesRegex(doc_import.DocumentTooLarge, "exceeds"):
                doc_import.import_document("tiny.html", b"<p>small paragraph</p>" * 3)

    def test_empty_formatting_and_tables_are_not_readable_content(self):
        from docx import Document

        document = Document()
        document.add_table(rows=1, cols=2)
        data = io.BytesIO()
        document.save(data)
        for name, source in (
            ("empty.docx", data.getvalue()),
            ("empty.html", b"<body><h1></h1><p><b> </b></p><hr></body>"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "no readable text"):
                    doc_import.import_document(name, source)

    def test_html_optional_body_and_head_tags_preserve_visible_content(self):
        for source in (
            b"<html><head><title>T</title><p>Report</p></html>",
            b"<head><title>T</title>Report",
            b"<head><meta charset='utf-8'><p>Report</p>",
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    doc_import.import_document("report.html", source)["content"], "Report\n"
                )

    def test_utf8_html_xml_declaration_does_not_change_encoding(self):
        for declaration in ("UTF-8", "iso-8859-1"):
            source = f'<?xml version="1.0" encoding="{declaration}"?><html><body><p>café 中文</p></body></html>'
            with self.subTest(declaration=declaration):
                self.assertEqual(
                    doc_import.import_document("export.html", source.encode("utf-8"))["content"],
                    "café 中文\n",
                )

    def test_unsupported_type(self):
        with self.assertRaises(ValueError):
            doc_import.import_document("a.xyz", b"data")

    def test_pdf_graceful_when_pypdf_missing(self):
        try:
            import pypdf  # noqa: F401

            return  # pypdf installed → nothing to assert here
        except Exception:
            pass
        with self.assertRaises(ValueError):
            doc_import.import_document("a.pdf", b"%PDF-1.4 not a real pdf")

    def test_html_em_italic_and_ol(self):
        html = "<p><em>slanted</em> and <i>also</i></p><ol><li>first</li><li>second</li></ol>"
        c = doc_import.import_document("x.html", html.encode())["content"]
        self.assertIn("*slanted*", c)
        self.assertIn("*also*", c)
        self.assertIn("1. first", c)
        self.assertIn("2. second", c)

    def test_name_strips_path_and_ext(self):
        r = doc_import.import_document("path/to/doc.txt", b"x")
        self.assertEqual(r["name"], "doc")

    def test_htm_extension_works(self):
        html = "<h2>Sub</h2><p>body</p>"
        c = doc_import.import_document("page.htm", html.encode())["content"]
        self.assertIn("## Sub", c)
        self.assertIn("body", c)

    def test_docx_heading2_and_numbered_list(self):
        from docx import Document

        doc = Document()
        doc.add_heading("Chapter Two", level=2)
        doc.add_paragraph("step one", style="List Number")
        buf = io.BytesIO()
        doc.save(buf)
        c = doc_import.import_document("doc.docx", buf.getvalue())["content"]
        self.assertIn("## Chapter Two", c)
        self.assertIn("1. step one", c)


class PdfWorkerTests(unittest.TestCase):
    def run_worker(self, code, **limits):
        original = subprocess.Popen
        self.processes = []

        def start(command, **kwargs):
            self.assertEqual(command[-1], "--pdf-worker")
            self.assertNotIn("ALLES_DATA", kwargs["env"])
            process = original([sys.executable, "-I", "-c", code], **kwargs)
            self.processes.append(process)
            return process

        with mock.patch.object(doc_import.subprocess, "Popen", side_effect=start):
            with mock.patch.multiple(doc_import, **limits) if limits else nullcontext():
                try:
                    return doc_import.import_document("local.pdf", b"local fixture")["content"]
                finally:
                    self.assertTrue(self.processes)
                    for process in self.processes:
                        self.assertIsNotNone(process.poll(), "PDF child must be reaped")

    def test_real_worker_deadline_kills_and_reaps_child(self):
        with self.assertRaisesRegex(doc_import.DocumentTooLarge, "too long"):
            self.run_worker("import time; time.sleep(5)", PDF_TIMEOUT_SECONDS=0.1)
        # Failure releases the single-extraction slot for the next import.
        self.assertEqual(self.run_worker("print('retry succeeds')"), "retry succeeds\n")

    def test_real_worker_memory_watchdog_kills_small_child(self):
        # Set the allowance below normal interpreter RSS; no oversized allocation.
        with self.assertRaisesRegex(doc_import.DocumentTooLarge, "resource limit"):
            self.run_worker("import time; time.sleep(5)", PDF_MEMORY_BYTES=1)

    def test_worker_output_limit_and_crash_never_return_partial_text(self):
        with self.assertRaises(doc_import.DocumentTooLarge):
            self.run_worker("print('x' * 33)", MAX_TEXT_BYTES=32)
        with self.assertRaises(doc_import.DocumentTooLarge):
            self.run_worker("import sys; print('partial'); sys.exit(3)")

    def test_worker_entry_extracts_in_order_and_aborts_failed_pages(self):
        worker = str(Path(doc_import.__file__).resolve())
        for failing in (False, True):
            with self.subTest(failing=failing):
                code = textwrap.dedent(f"""
                    import runpy, sys, types
                    class Page:
                        def __init__(self, text): self.text = text
                        def extract_text(self):
                            if self.text is None: raise ValueError('synthetic page failure')
                            return self.text
                    class Reader:
                        def __init__(self, data):
                            assert data.read() == b'local fixture'
                            self.pages = [Page('first é page'), Page({None if failing else "last page"!r})]
                    sys.modules['pypdf'] = types.SimpleNamespace(PdfReader=Reader)
                    sys.argv = [{worker!r}, '--pdf-worker']
                    runpy.run_path({worker!r}, run_name='__main__')
                """)
                if failing:
                    with self.assertRaisesRegex(ValueError, "every PDF page"):
                        self.run_worker(code)
                else:
                    self.assertEqual(self.run_worker(code), "first é page\n\nlast page\n")

    def test_overlapping_pdf_import_returns_retryable_message_without_starting_child(self):
        with mock.patch.object(doc_import, "_PDF_GATE") as gate:
            gate.acquire.return_value = False
            with mock.patch.object(doc_import.subprocess, "Popen") as start:
                with self.assertRaisesRegex(ValueError, "try again shortly"):
                    doc_import.import_document("local.pdf", b"local fixture")
                start.assert_not_called()
                gate.release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
