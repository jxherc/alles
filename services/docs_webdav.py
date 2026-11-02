"""WebDAV view of the docs folder, for Obsidian's "Remotely Save" plugin on an iPad or phone.

off by default. "read" answers OPTIONS, PROPFIND, GET and HEAD only. "write" also lets PUT
save a markdown document and MKCOL make a folder. a PUT goes through docs' own safe save
(document_safety.save_document): it keeps a revision and keeps both copies when the file
changed underneath. delete, move and copy are never answered: those stay in docs.

protocol facts (RFC 4918): a multistatus reply is XML with one response per resource, a
collection has <d:collection/> in resourcetype, Depth is 0, 1 or infinity.
"""

from __future__ import annotations

import mimetypes
import socket
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from core.settings import load_settings
from services import document_safety, vault_md

MODES = ("off", "read", "write")
MAX_PUT_BYTES = 8 * 1024 * 1024
_DOC_SUFFIXES = (".md", ".markdown")
_HASHES: dict[tuple[str, int, int], str] = {}


class DavError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message


def mode() -> str:
    value = str(load_settings().get("docs_dav", "off")).strip().lower()
    return value if value in MODES else "off"


def _hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.split("/") if part)


def resolve(rel: str) -> tuple[str, Path]:
    clean = (rel or "").strip("/")
    if _hidden(clean):
        raise DavError(404, "not found")
    try:
        return clean, vault_md._safe(clean)
    except ValueError:
        raise DavError(403, "path escapes the docs folder") from None


def _content_hash(path: Path, stat) -> str:
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _HASHES.get(key)
    if cached is None:
        if len(_HASHES) > 20000:
            _HASHES.clear()
        cached = vault_md._hash_bytes(path.read_bytes())
        _HASHES[key] = cached
    return cached


def etag(path: Path, stat=None) -> str:
    """the content hash docs itself uses, so If-Match lines up with a docs save."""
    stat = stat or path.stat()
    return f'"{_content_hash(path, stat)}"'


def _href(rel: str, is_dir: bool) -> str:
    href = "/dav/docs/" + quote(rel, safe="/") if rel else "/dav/docs/"
    return href + "/" if is_dir and not href.endswith("/") else href


def _entry(rel: str, path: Path) -> str:
    stat = path.stat()
    is_dir = path.is_dir()
    modified = format_datetime(datetime.fromtimestamp(stat.st_mtime, UTC), usegmt=True)
    last = f"<d:getlastmodified>{modified}</d:getlastmodified>"
    if is_dir:
        props = ["<d:resourcetype><d:collection/></d:resourcetype>", last]
    else:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        props = [
            "<d:resourcetype/>",
            f"<d:getcontentlength>{stat.st_size}</d:getcontentlength>",
            f"<d:getcontenttype>{escape(mime)}</d:getcontenttype>",
            f"<d:getetag>{etag(path, stat)}</d:getetag>",
            last,
        ]
    return (
        f"<d:response><d:href>{escape(_href(rel, is_dir))}</d:href><d:propstat><d:prop>"
        + "".join(props)
        + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def _children(rel: str, path: Path) -> list[tuple[str, Path]]:
    out = []
    for child in sorted(path.iterdir(), key=lambda c: c.name.lower()):
        if child.name.startswith(".") or child.is_symlink():
            continue
        out.append((f"{rel}/{child.name}" if rel else child.name, child))
    return out


def propfind(rel: str, depth: str) -> str:
    clean, path = resolve(rel)
    if not path.exists():
        raise DavError(404, "not found")
    rows = [_entry(clean, path)]
    if path.is_dir() and depth != "0":
        stack = _children(clean, path)
        while stack:
            child_rel, child = stack.pop(0)
            rows.append(_entry(child_rel, child))
            if child.is_dir() and depth == "infinity":
                stack = _children(child_rel, child) + stack
    head = '<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:">'
    return head + "".join(rows) + "</d:multistatus>"


def read_file(rel: str) -> tuple[Path, str]:
    _, path = resolve(rel)
    if path.is_dir():
        raise DavError(405, "a folder has no body")
    if not path.is_file() or path.is_symlink():
        raise DavError(404, "not found")
    return path, etag(path)


def put_document(rel: str, data: bytes, if_match: str = "") -> tuple[int, str, str]:
    """save a markdown document through docs' own save: (status, new etag, saved path)."""
    if mode() != "write":
        raise DavError(403, "saving over webdav is off")
    clean, path = resolve(rel)
    if not clean or path.suffix.lower() not in _DOC_SUFFIXES:
        raise DavError(403, "only markdown documents can be saved here; other files stay in docs")
    if len(data) > MAX_PUT_BYTES:
        raise DavError(413, "document too large")
    if path.is_dir():
        raise DavError(409, "that name is a folder")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DavError(415, "documents must be utf-8") from None
    existed = path.is_file()
    current = vault_md._hash_bytes(path.read_bytes()) if existed else ""
    wanted = current
    if if_match.strip() not in ("", "*"):
        wanted = if_match.strip().removeprefix("W/").strip('"')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        result = document_safety.save_document(clean, text, wanted)
    except document_safety.DocumentSaveConflict:
        raise DavError(412, "the document changed; both copies were kept in docs") from None
    except (ValueError, vault_md.DocumentConflictError) as exc:
        raise DavError(409, str(exc)) from None
    return (204 if existed else 201), f'"{result["hash"]}"', result["path"]


def make_folder(rel: str) -> None:
    if mode() != "write":
        raise DavError(403, "saving over webdav is off")
    clean, path = resolve(rel)
    if not clean:
        raise DavError(405, "the root exists")
    if path.exists():
        raise DavError(405, "already exists")
    if not path.parent.is_dir():
        raise DavError(409, "the parent folder is missing")
    path.mkdir()


def lan_address() -> str:
    """this machine's address on the local network, or empty when it can't be told."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            host = sock.getsockname()[0]
    except OSError:
        return ""
    return "" if host.startswith("127.") else host
