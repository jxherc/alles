"""
Import a document into the vault as markdown. Handles .md/.txt (passthrough),
.docx (python-docx), .html (stripped to md), .pdf (pypdf, graceful if missing).
"""

import io
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

MAX_TEXT_BYTES = 1024 * 1024
MAX_DOCX_BYTES = 32 * 1024 * 1024
PDF_MEMORY_BYTES = 256 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 10
_PDF_GATE = threading.BoundedSemaphore(1)


class DocumentTooLarge(ValueError):
    pass


def import_document(filename: str, data: bytes) -> dict:
    name = (filename or "imported").replace("\\", "/").rsplit("/", 1)[-1]
    stem, _, ext = name.rpartition(".")
    ext = ext.lower()
    stem = (stem or name).strip() or "imported"
    if ext in ("md", "markdown", "txt", "", "html", "htm"):
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("text import needs a UTF-8 file; no content was saved") from exc
        if ext in ("html", "htm"):
            content = _html_to_md(content)
    elif ext == "docx":
        content = _docx_to_md(data)
    elif ext == "pdf":
        content = _pdf_to_md(data)
    else:
        raise ValueError(f"can't import .{ext} — try .md, .txt, .docx, .html or .pdf")
    if not content.strip():
        raise ValueError("no readable text found; nothing was saved")
    if ext not in ("md", "markdown", "txt", ""):
        content = content.strip() + "\n"
    return {"name": stem, "content": content}


def _validate_docx_archive(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_BYTES:
            raise ValueError("expanded document is too large; use a smaller file")
        for item in archive.infolist():
            if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("unsupported DOCX compression; save a standard DOCX copy")
            # Retain zipfile's header, encryption and overlapping-entry checks.
            with archive.open(item):
                pass
            name_size, extra_size = struct.unpack_from("<HH", data, item.header_offset + 26)
            start = item.header_offset + 30 + name_size + extra_size
            compressed = memoryview(data)[start : start + item.compress_size]
            if item.compress_type == zipfile.ZIP_DEFLATED:
                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                # Check actual output before zipfile can truncate to a forged file_size.
                expanded = decoder.decompress(compressed, item.file_size + 1)
                if len(expanded) != item.file_size or not decoder.eof or decoder.unused_data:
                    raise ValueError("invalid DOCX expanded member size")
            else:
                expanded = compressed
                if len(expanded) != item.file_size:
                    raise ValueError("invalid DOCX stored member size")
            if zlib.crc32(expanded) != item.CRC:
                raise ValueError("invalid DOCX member checksum")


def _docx_to_md(data: bytes) -> str:
    from docx import Document
    from docx.table import Table

    _validate_docx_archive(data)
    doc = Document(io.BytesIO(data))
    out = []
    size = 0
    readable = False

    def check(extra):
        if size + extra > MAX_TEXT_BYTES:
            raise DocumentTooLarge("extracted text exceeds 1 MiB; split the document and try again")

    def emit(line):
        nonlocal size
        count = len(line.encode("utf-8")) + 1
        check(count)
        out.append(line)
        size += count

    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            emit("")
            columns = len(block.columns)
            check(columns * 6 + 2)
            for index, row in enumerate(block.rows):
                # python-docx materializes one tuple entry per grid position.
                # Check spans before row.cells can expand even empty cells.
                spans = [cell.grid_span for cell in row._tr.tc_lst]
                if any(span < 1 for span in spans):
                    raise ValueError("invalid table cell span")
                check(sum(spans) * 3 + 2)
                parts = ["| "]
                row_size = 2
                for cell_index, cell in enumerate(row.cells):
                    text = cell.text.strip().replace("\n", " ")
                    readable |= bool(text.strip())
                    part = (" " if cell_index else "") + text + " |"
                    row_size += len(part.encode("utf-8"))
                    check(row_size + 1)
                    parts.append(part)
                emit("".join(parts))
                if index == 0:
                    check(columns * 6 + 2)
                    emit("| " + " | ".join(["---"] * columns) + " |")
            emit("")
            continue
        p = block
        text = p.text.rstrip()
        readable |= bool(text.strip())
        style = ((p.style.name if p.style else "") or "").lower()
        if not text:
            emit("")
            continue
        m = re.match(r"heading (\d)", style)
        if m:
            emit("#" * min(int(m.group(1)), 6) + " " + text)
        elif style == "title":
            emit("# " + text)
        elif "list number" in style:
            emit("1. " + text)
        elif "list" in style:
            emit("- " + text)
        elif style in ("quote", "intense quote"):
            emit("> " + text)
        else:
            emit(text)
    return "\n".join(out) if readable else ""


class _HtmlToMd(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.output_bytes = 0
        self.readable = False
        self.skip = 0
        self.in_head = False
        self.lists = []  # stack of [kind, counter]
        self.in_link = False
        self.href = None
        self.link_txt = []
        self.pre = 0

    def emit(self, text):
        self.output_bytes += len(text.encode("utf-8"))
        if self.output_bytes + 1 > MAX_TEXT_BYTES:
            raise DocumentTooLarge("extracted text exceeds 1 MiB; split the document and try again")
        self.out.append(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "head":
            self.in_head = True
            return
        if tag == "body":
            self.in_head = False
        if tag in ("script", "style"):
            self.skip += 1
            return
        if self.skip or self.in_head:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.emit("\n\n")
        elif tag == "br":
            self.emit("  \n")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag == "blockquote":
            self.emit("\n\n> ")
        elif tag == "hr":
            self.emit("\n\n---\n\n")
        elif tag == "ul":
            self.lists.append(["ul", 0])
        elif tag == "ol":
            self.lists.append(["ol", 0])
        elif tag == "li":
            indent = "  " * max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.emit(f"\n{indent}{self.lists[-1][1]}. ")
            else:
                self.emit(f"\n{indent}- ")
        elif tag == "a":
            self.in_link = True
            self.href = a.get("href")
            self.link_txt = []
        elif tag == "pre":
            self.pre += 1
            self.emit("\n\n```\n")

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
            return
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or self.in_head:
            return
        if tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote"):
            self.emit("\n")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
        elif tag == "a":
            txt = "".join(self.link_txt).strip()
            if self.href and txt:
                self.emit(f"[{txt}]({self.href})")
            elif txt:
                self.emit(txt)
            self.in_link = False
            self.href = None
            self.link_txt = []
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.emit("\n```\n")

    def handle_data(self, data):
        if self.skip or self.in_head:
            return
        self.readable |= bool(data.strip())
        if self.in_link:
            self.link_txt.append(data)
            return
        if self.pre:
            self.emit(data)
            return
        self.emit(re.sub(r"\s+", " ", data))

    def md(self):
        if not self.readable:
            return ""
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_md(s: str) -> str:
    from lxml import html

    if not s.strip():
        return ""
    # Normalize optional head/body tags before suppressing metadata. The
    # tokenizer alone cannot infer where visible HTML body content begins.
    parser = html.HTMLParser(no_network=True, encoding="utf-8")
    document = html.document_fromstring(s.encode("utf-8"), parser=parser)
    if any(error.level_name == "FATAL" for error in parser.error_log):
        raise ValueError("could not read the whole HTML document; nothing was saved")
    p = _HtmlToMd()
    p.feed(html.tostring(document, encoding="unicode"))
    return p.md()


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader  # older name, same api
        except Exception:
            raise ValueError(
                "PDF import is unavailable on this server; export text or DOCX instead"
            )
    reader = PdfReader(io.BytesIO(data))
    pages = []
    size = 0
    for pg in reader.pages:
        try:
            txt = (pg.extract_text() or "").strip()
        except Exception as exc:
            raise ValueError("could not extract every PDF page; nothing was saved") from exc
        if txt:
            size += len(txt.encode("utf-8")) + (2 if pages else 0)
            # Reserve the final newline added by import_document.
            if size + 1 > MAX_TEXT_BYTES:
                raise DocumentTooLarge(
                    "extracted text exceeds 1 MiB; split the document and try again"
                )
            pages.append(txt)
    return "\n\n".join(pages)


def _pdf_to_md(data: bytes) -> str:
    # A page can inflate before extract_text returns, so text-size checks alone
    # cannot protect the server. Keep the parser in one disposable process.
    import psutil

    if not _PDF_GATE.acquire(blocking=False):
        raise ValueError("another PDF is being read; try again shortly")
    try:
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
            source.write(data)
            source.seek(0)
            env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--pdf-worker"],
                stdin=source,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                monitor = psutil.Process(process.pid)
                deadline = time.monotonic() + PDF_TIMEOUT_SECONDS
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise DocumentTooLarge(
                            "PDF extraction took too long; split the document and try again"
                        )
                    try:
                        memory = monitor.memory_info().rss
                    except psutil.NoSuchProcess:
                        continue
                    if (
                        memory > PDF_MEMORY_BYTES
                        or os.fstat(output.fileno()).st_size > MAX_TEXT_BYTES
                    ):
                        raise DocumentTooLarge(
                            "PDF extraction exceeds the resource limit; split the document and try again"
                        )
                    time.sleep(0.01)
                output.seek(0)
                text = output.read(MAX_TEXT_BYTES + 1).decode("utf-8")
                if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise DocumentTooLarge(
                        "extracted text exceeds 1 MiB; split the document and try again"
                    )
                if process.returncode == 2:
                    raise ValueError(text)
                if process.returncode != 0:
                    raise DocumentTooLarge(
                        "PDF extraction exceeds the resource limit or could not finish; split the document and try again"
                    )
                return text
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
    finally:
        _PDF_GATE.release()


def _pdf_worker():
    # Linux enforces address-space/CPU limits in the kernel. The parent also
    # monitors RSS and elapsed time, including on macOS where RLIMIT_AS is not
    # available. No extracted content is sent back after any failed page.
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_BYTES, PDF_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    try:
        data = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise DocumentTooLarge("choose a file smaller than 8 MiB")
        text = _extract_pdf(data)
    except (DocumentTooLarge, MemoryError):
        return 3
    except ValueError as exc:
        sys.stdout.buffer.write(str(exc).encode("utf-8")[:4096])
        return 2
    except Exception:
        sys.stdout.buffer.write(b"could not read this PDF; check the file and try again")
        return 2
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__" and sys.argv[1:] == ["--pdf-worker"]:
    sys.exit(_pdf_worker())
