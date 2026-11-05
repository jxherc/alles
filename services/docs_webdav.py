"""WebDAV view of the docs folder, for Obsidian's "Remotely Save" plugin on an iPad or phone.

off by default. "read" answers OPTIONS, PROPFIND, GET and HEAD only. "write" also lets PUT
save a file, MKCOL make a folder, DELETE remove and MOVE rename, which is everything the
Remotely Save plugin does in a sync (src/fsWebdav.ts: putFileContents, createDirectory,
deleteFile, moveFile, and the connection check in src/fsAll.ts that writes, rewrites and
removes a scratch file). a markdown PUT goes through docs' own safe save
(document_safety.save_document): it keeps a revision and keeps both copies when the file
changed underneath. DELETE never destroys a document: it moves it to docs' trash, where
"recently deleted" can bring it back. COPY is never answered.

protocol facts (RFC 4918): a multistatus reply is XML with one response per resource, a
collection has <d:collection/> in resourcetype, Depth is 0, 1 or infinity.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import socket
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from core.settings import load_settings
from services import document_safety, trash, vault_md

MODES = ("off", "read", "write")
MAX_PUT_BYTES = 8 * 1024 * 1024  # a markdown document
MAX_FILE_BYTES = 100 * 1024 * 1024  # any other file; the plugin sends files over 10 MB whole
# the plugin's connection check makes a folder with this name, writes into it and deletes it
# (src/fsAll.ts checkConnectCommonOps); that scratch folder is not a note, so it is not trashed
_SCRATCH_PREFIX = "rs-test-folder-"
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


def _through_link(clean: str) -> bool:
    """true when any part of the path, as written, is a symlink (not where it points)."""
    here = vault_md.root_dir()
    for part in clean.split("/"):
        if not part:
            continue
        here = here / part
        if here.is_symlink():
            return True
        if not here.exists():
            return False
    return False


def resolve(rel: str) -> tuple[str, Path]:
    clean = (rel or "").strip("/")
    if _hidden(clean):
        raise DavError(404, "not found")
    if _through_link(clean):
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
    """save a file: (status, new etag, saved path). markdown goes through docs' own save,
    anything else (pictures, pdfs) is written whole and atomically."""
    if mode() != "write":
        raise DavError(403, "saving over webdav is off")
    clean, path = resolve(rel)
    if not clean:
        raise DavError(405, "the root is a folder")
    is_doc = path.suffix.lower() in _DOC_SUFFIXES
    if is_doc and len(data) > MAX_PUT_BYTES:
        raise DavError(413, "document too large")
    if len(data) > MAX_FILE_BYTES:
        raise DavError(413, "file too large")
    if path.is_dir():
        raise DavError(409, "that name is a folder")
    existed = path.is_file()
    if not is_doc:
        try:
            vault_md._atomic_write(path, data)
        except OSError:
            raise DavError(409, "could not save the file") from None
        return (204 if existed else 201), etag(path), clean
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DavError(415, "documents must be utf-8") from None
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


def _bin(db, clean: str, path: Path) -> None:
    """take a file or folder out of docs without losing it: docs' trash keeps it 30 days."""
    if clean.startswith(_SCRATCH_PREFIX) and not clean.lower().endswith(_DOC_SUFFIXES):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return
    trash.soft_delete_path(db, "vault", clean, path)


def _markdown_under(path: Path, clean: str) -> list[str]:
    if path.is_file():
        return [clean] if path.suffix.lower() in _DOC_SUFFIXES else []
    base = vault_md.root_dir()
    return [
        str(p.relative_to(base)).replace("\\", "/")
        for p in path.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _DOC_SUFFIXES
        and not _hidden(str(p.relative_to(path)))
    ]


def delete_path(db, rel: str) -> list[str]:
    """DELETE: move to docs' trash. returns the markdown paths that are gone, to re-index."""
    if mode() != "write":
        raise DavError(403, "saving over webdav is off")
    clean, path = resolve(rel)
    if not clean:
        raise DavError(403, "the docs folder itself cannot be changed")
    if not path.exists():
        raise DavError(404, "not found")
    gone = _markdown_under(path, clean)
    _bin(db, clean, path)
    return gone


def move_path(
    db, rel: str, to_rel: str, overwrite: bool = True
) -> tuple[int, list[str], list[str]]:
    """MOVE: rename a file or folder. (status, old markdown paths, new markdown paths).
    no links are rewritten: the client renames the same way on its own side."""
    if mode() != "write":
        raise DavError(403, "saving over webdav is off")
    src_clean, src = resolve(rel)
    try:
        dst_clean, dst = resolve(to_rel)
    except DavError as exc:
        raise DavError(403 if exc.status == 404 else exc.status, exc.message) from None
    if not src_clean or not dst_clean:
        raise DavError(403, "the docs folder itself cannot be changed")
    if not src.exists():
        raise DavError(404, "not found")
    if src_clean == dst_clean:
        raise DavError(403, "source and destination are the same")
    if dst_clean.startswith(src_clean + "/"):
        raise DavError(403, "a folder cannot move into itself")
    if not dst.parent.is_dir():
        raise DavError(409, "the parent folder is missing")
    case_only = dst.exists() and os.path.samefile(src, dst)
    existed = dst.exists() and not case_only
    if existed:
        if not overwrite:
            raise DavError(412, "the destination exists")
        if src.is_dir() != dst.is_dir():
            raise DavError(409, "a file and a folder cannot replace each other")
        before_dst = _markdown_under(dst, dst_clean)
        _bin(db, dst_clean, dst)
    else:
        before_dst = []
    old = _markdown_under(src, src_clean)
    src.rename(dst)
    new = _markdown_under(dst, dst_clean)
    return (204 if existed else 201), old + before_dst, new


def lan_address() -> str:
    """this machine's address on the local network, or empty when it can't be told."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            host = sock.getsockname()[0]
    except OSError:
        return ""
    return "" if host.startswith("127.") else host
