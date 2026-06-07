"""Convert a markdown note to a .docx file (bytes). Reasonable markdown subset."""
import io
import re

from docx import Document
from docx.shared import Pt

_INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*]+?\*|`[^`]+?`|\[\[[^\]]+?\]\])")


def _add_inline(p, text):
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            p.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*"):
            p.add_run(part[1:-1]).italic = True
        elif part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1]); r.font.name = "Consolas"
        elif part.startswith("[[") and part.endswith("]]"):
            inner = part[2:-2].split("|")[-1].split("#")[0].strip()
            r = p.add_run(inner); r.italic = True   # wikilink → italic text
        else:
            p.add_run(part)


def md_to_docx(md: str, title: str = "") -> bytes:
    doc = Document()
    if title:
        doc.add_heading(title, 0)

    in_code = False
    code = []
    for line in (md or "").split("\n"):
        if line.lstrip().startswith("```"):
            if in_code:
                p = doc.add_paragraph()
                r = p.add_run("\n".join(code))
                r.font.name = "Consolas"; r.font.size = Pt(9)
                code = []; in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue

        s = line.rstrip()
        if not s.strip():
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        if h:
            doc.add_heading(h.group(2), min(len(h.group(1)), 4))
            continue
        if re.match(r"^[-*]\s+", s):
            _add_inline(doc.add_paragraph(style="List Bullet"), re.sub(r"^[-*]\s+", "", s))
            continue
        if re.match(r"^\d+\.\s+", s):
            _add_inline(doc.add_paragraph(style="List Number"), re.sub(r"^\d+\.\s+", "", s))
            continue
        if re.match(r"^[-_*]{3,}$", s):
            doc.add_paragraph("─" * 30)
            continue
        if s.startswith(">"):
            p = doc.add_paragraph(style="Intense Quote")
            _add_inline(p, s.lstrip("> ").rstrip())
            continue
        _add_inline(doc.add_paragraph(), s)

    if in_code and code:
        r = doc.add_paragraph().add_run("\n".join(code)); r.font.name = "Consolas"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
