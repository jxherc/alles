"""Short-lived in-memory sessions and uploads for no-trace conversations."""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_TTL = timedelta(hours=4)
_LOCK = threading.RLock()


@dataclass
class IncognitoSession:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "incognito chat"
    model: str = ""
    endpoint_id: str | None = None
    mode: str = "chat"
    chat_behavior: str = ""
    persona_id: str | None = None
    project_id: str | None = None
    working_dir: str = ""
    starred: bool = False
    archived: bool = False
    incognito: bool = True
    message_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_message_at: datetime | None = None
    messages: list = field(default_factory=list)
    project: object | None = None
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + _TTL)


@dataclass
class IncognitoUpload:
    id: str
    name: str
    mime_type: str
    content: bytes
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + _TTL)


@dataclass
class IncognitoMessage:
    role: str
    content: str
    meta: str = "{}"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def meta_dict(self) -> dict:
        import json

        try:
            value = json.loads(self.meta or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


_SESSIONS: dict[str, IncognitoSession] = {}
_UPLOADS: dict[str, IncognitoUpload] = {}


def _purge() -> None:
    now = datetime.utcnow()
    for key, value in list(_SESSIONS.items()):
        if value.expires_at <= now:
            _SESSIONS.pop(key, None)
    for key, value in list(_UPLOADS.items()):
        if value.expires_at <= now:
            _UPLOADS.pop(key, None)


def create_session(**values) -> IncognitoSession:
    with _LOCK:
        _purge()
        session = IncognitoSession(**values)
        _SESSIONS[session.id] = session
        return session


def get_session(session_id: str) -> IncognitoSession | None:
    with _LOCK:
        _purge()
        session = _SESSIONS.get(session_id)
        if session:
            session.expires_at = datetime.utcnow() + _TTL
        return session


def delete_session(session_id: str) -> bool:
    with _LOCK:
        return _SESSIONS.pop(session_id, None) is not None


def append_turn(session_id: str, user_text: str, assistant_text: str, meta: str = "{}") -> bool:
    with _LOCK:
        session = get_session(session_id)
        if not session:
            return False
        session.messages.append(IncognitoMessage(role="user", content=user_text))
        if assistant_text:
            session.messages.append(
                IncognitoMessage(role="assistant", content=assistant_text, meta=meta)
            )
        session.message_count = len(session.messages)
        session.last_message_at = datetime.utcnow()
        return True


def put_upload(name: str, mime_type: str, content: bytes) -> IncognitoUpload:
    with _LOCK:
        _purge()
        upload = IncognitoUpload(uuid.uuid4().hex, name, mime_type, bytes(content))
        _UPLOADS[upload.id] = upload
        return upload


def get_upload(upload_id: str) -> IncognitoUpload | None:
    with _LOCK:
        _purge()
        upload = _UPLOADS.get(upload_id)
        if upload:
            upload.expires_at = datetime.utcnow() + _TTL
        return upload


def delete_upload(upload_id: str) -> bool:
    with _LOCK:
        return _UPLOADS.pop(upload_id, None) is not None


def clear_for_tests() -> None:
    with _LOCK:
        _SESSIONS.clear()
        _UPLOADS.clear()
