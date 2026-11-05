"""WebDAV for the docs folder (Obsidian's Remotely Save over the local network).
the rules live in services/docs_webdav.py. sign in with an alles token as the password
(any user name), or the owner's session; with no password set up, the folder is as open
as the rest of the app."""

import base64
import binascii
import mimetypes
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, BackgroundTasks, Request, Response

from core.api_tokens import token_access
from core.auth import login_blocked, record_login_fail, verify_session
from core.database import SessionLocal
from core.settings import auth_enabled
from services import docs_webdav

router = APIRouter(prefix="/dav/docs")

_READ = ("OPTIONS", "PROPFIND", "GET", "HEAD")
_ALLOW = "OPTIONS, PROPFIND, GET, HEAD, PUT, MKCOL, DELETE, MOVE"
# DAV class 1 only: no locks, and no partial update (so the plugin sends whole files).
# Obsidian reaches this with its own requestUrl, which skips CORS (Remotely Save
# src/fsWebdav.ts patches the webdav client's request to requestUrl), so no CORS headers.
_DAV = {"DAV": "1", "Allow": _ALLOW, "MS-Author-Via": "DAV"}
# copy is not registered, so the framework answers it 405
_METHODS = [*_READ, "PUT", "MKCOL", "DELETE", "MOVE"]
_PREFIX = "/dav/docs"


def _text(status: int, message: str, headers: dict | None = None) -> Response:
    return Response(message, status_code=status, media_type="text/plain", headers=headers or {})


def _challenge() -> Response:
    return _text(401, "sign in", {"WWW-Authenticate": 'Basic realm="alles docs"'})


def _credential(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer":
        return value.strip()
    if scheme.lower() == "basic":
        try:
            return base64.b64decode(value).decode("utf-8").partition(":")[2]
        except (binascii.Error, UnicodeDecodeError):
            return ""
    return ""


def _denied(request: Request, scope: str) -> Response | None:
    """None when the request may go on, else the reply to send."""
    ip = request.client.host if request.client else ""
    secret = _credential(request)
    if secret.startswith(("alles_", "aide_")):
        if login_blocked(ip):
            return _text(429, "too many wrong tries; wait a few minutes")
        db = SessionLocal()
        try:
            access = token_access(secret, db, scope)
        finally:
            db.close()
        if access == "ok":
            return None
        record_login_fail(ip)
        if access == "forbidden":
            return _text(403, f"this token cannot {scope}")
        return _challenge()
    if not auth_enabled():
        return None
    if verify_session(request.cookies.get("aide_session", "")):
        return None
    return _challenge()


def _destination(request: Request) -> str:
    """the path inside docs that a MOVE's Destination header names."""
    raw = request.headers.get("destination", "").strip()
    parts = urlsplit(raw)
    if parts.netloc and parts.netloc.casefold() != request.headers.get("host", "").casefold():
        raise docs_webdav.DavError(502, "the destination is not inside docs")
    path = unquote(parts.path)
    if path != _PREFIX and not path.startswith(_PREFIX + "/"):
        raise docs_webdav.DavError(502, "the destination is not inside docs")
    return path[len(_PREFIX) :]


def _reindex(background_tasks: BackgroundTasks, paths: list[str]) -> None:
    from routes import vault_md as vault_routes

    for item in dict.fromkeys(paths):
        background_tasks.add_task(vault_routes._sync_changed, item)


@router.api_route("", methods=_METHODS)
@router.api_route("/{path:path}", methods=_METHODS)
async def dav(request: Request, background_tasks: BackgroundTasks, path: str = ""):
    if docs_webdav.mode() == "off":
        return _text(404, "docs over webdav is off")
    method = request.method
    denied = _denied(request, "read" if method in _READ else "write")
    if denied is not None:
        return denied
    try:
        if method in ("PUT", "MKCOL", "DELETE", "MOVE"):
            size = request.headers.get("content-length", "")
            if size.isdigit() and int(size) > docs_webdav.MAX_FILE_BYTES:
                return _text(413, "file too large")
        if method == "OPTIONS":
            return Response(status_code=200, headers=_DAV)
        if method == "PROPFIND":
            depth = request.headers.get("depth", "infinity").strip().lower()
            body = docs_webdav.propfind(path, depth if depth in ("0", "1") else "infinity")
            return Response(
                body, status_code=207, media_type="application/xml; charset=utf-8", headers=_DAV
            )
        if method in ("GET", "HEAD"):
            file, tag = docs_webdav.read_file(path)
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if method == "HEAD":
                size = str(file.stat().st_size)
                return Response(
                    status_code=200, media_type=mime, headers={"ETag": tag, "Content-Length": size}
                )
            return Response(file.read_bytes(), media_type=mime, headers={"ETag": tag})
        if method == "MKCOL":
            docs_webdav.make_folder(path)
            return Response(status_code=201)
        if method in ("DELETE", "MOVE"):
            db = SessionLocal()
            try:
                if method == "DELETE":
                    _reindex(background_tasks, docs_webdav.delete_path(db, path))
                    return Response(status_code=204, background=background_tasks)
                overwrite = request.headers.get("overwrite", "T").strip().upper() != "F"
                status, old, new = docs_webdav.move_path(db, path, _destination(request), overwrite)
                _reindex(background_tasks, old + new)
                return Response(status_code=status, background=background_tasks)
            finally:
                db.close()
        status, tag, saved = docs_webdav.put_document(
            path, await request.body(), request.headers.get("if-match", "")
        )
        if saved.lower().endswith((".md", ".markdown")):
            _reindex(background_tasks, [saved])
        return Response(status_code=status, headers={"ETag": tag}, background=background_tasks)
    except docs_webdav.DavError as exc:
        return _text(exc.status, exc.message)
