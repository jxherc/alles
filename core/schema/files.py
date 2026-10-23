import os
import unicodedata
import uuid
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)

from core.schema.base import Base, EncryptedText, _now, _uid

DEFAULT_LOCAL_STORAGE_LOCATION_ID = "default-local"


def normalize_file_identity_path(value: str) -> str:
    """Return one safe, slash-separated Files identity without touching the filesystem."""
    raw = str(value or "")
    if os.name == "nt":
        raw = raw.replace("\\", "/")
    raw = raw.strip("/")
    parts = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("path escapes storage location")
        parts.append(part)
    return "/".join(parts)


def _normalized_path_default(context):
    return normalize_file_identity_path(context.get_current_parameters().get("path", ""))


class StorageLocation(Base):
    """One browsable Files root. Backup destinations remain separate configuration."""

    __tablename__ = "storage_locations"
    id = Column(String, primary_key=True, default=_uid)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, index=True)  # local | webdav | s3
    access = Column(String, nullable=False, default="read_only")  # read_only | managed
    root_path = Column(Text, default="")
    endpoint = Column(Text, default="")
    bucket = Column(String, default="")
    prefix = Column(Text, default="")
    config = Column(Text, default="{}")  # non-secret capability/config metadata
    secret = Column(EncryptedText("storage_locations.secret"), default="")
    enabled = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class FileTag(Base):
    # macOS-Finder-style labels for a file/folder in the files app, keyed by its
    # root-relative path. tags = comma-separated, color = one swatch name.
    __tablename__ = "file_tags"
    __table_args__ = (
        UniqueConstraint("location_id", "normalized_path", name="uq_file_tags_location_path"),
    )
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, index=True)  # legacy files-root-relative path; kept for compatibility
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
        index=True,
    )
    normalized_path = Column(String, nullable=False, default=_normalized_path_default, index=True)
    tags = Column(String, default="")  # csv of normalized (lowercased) tags
    color = Column(String, default="")  # swatch name: red/orange/green/blue/purple/gray
    starred = Column(Boolean, default=False)  # favorite flag (6a)
    created_at = Column(DateTime, default=_now)


class DocRevision(Base):
    __tablename__ = "doc_revisions"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # vault-relative, normalized
    content = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class IndexChunk(Base):
    # reusable, persistent, multi-kind text index (1c) — shared by docs RAG (3d)
    # and code semantic search (10a). vec is a JSON float list, or "" when no embedder.
    __tablename__ = "index_chunks"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, nullable=False, index=True)  # doc | code | ...
    ref = Column(String, nullable=False, index=True)  # vault path, symbol id, ...
    location_id = Column(String, nullable=True, index=True)
    normalized_path = Column(String, nullable=True, index=True)
    chunk_no = Column(Integer, default=0)
    text = Column(Text, default="")
    vec = Column(Text, default="")  # json.dumps(list[float]) or ""
    created_at = Column(DateTime, default=_now)


class FileVersion(Base):
    # generic file version history (1e) — blobs stored under <data>/.versions, deduped by sha.
    __tablename__ = "file_versions"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # files-relative path
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
        index=True,
    )
    normalized_path = Column(String, nullable=False, default=_normalized_path_default, index=True)
    sha = Column(String, default="")
    size = Column(Integer, default=0)
    stored = Column(String, default="")  # blob filename in the versions dir
    created_at = Column(DateTime, default=_now)


class TrashItem(Base):
    # generic soft-delete registry (1d). files stash their bytes in the trash dir;
    # photos flip Photo.deleted_at. restore/purge dispatch on kind. expires_at drives purge.
    __tablename__ = "trash_items"
    id = Column(String, primary_key=True, default=_uid)
    kind = Column(String, nullable=False, index=True)  # file | photo
    ref = Column(String, nullable=False)  # files-relative path | photo id
    location_id = Column(String, nullable=True, index=True)
    normalized_path = Column(String, nullable=True, index=True)
    name = Column(String, default="")
    payload = Column(Text, default="{}")  # json: {trash_name, is_dir, ...}
    trashed_at = Column(DateTime, default=_now)
    expires_at = Column(DateTime, nullable=True)


class Share(Base):
    # generic read-only share/publish for any resource (1a). sessions keep their
    # own share_token column for back-compat; this covers doc/file/photo/etc.
    __tablename__ = "shares"
    id = Column(String, primary_key=True, default=_uid)
    token = Column(
        String, unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex
    )
    kind = Column(String, nullable=False)  # doc|file|photo|album|contact|event|session
    ref = Column(String, nullable=False)  # resource id, or vault/files-relative path
    location_id = Column(String, nullable=True, index=True)
    normalized_path = Column(String, nullable=True, index=True)
    level = Column(String, default="view")  # view | download
    expires_at = Column(String, default="")  # 4c - ISO datetime; "" = never expires
    password_hash = Column(String, default="")  # 4c - sha256 of the access password; "" = open
    created_at = Column(DateTime, default=_now)


class DocComment(Base):
    # inline comments anchored to a quoted span of a doc (3e). a thread root has
    # parent_id == None; replies point at the root via parent_id. anchor holds the
    # quoted text — orphaned (computed on read) when it no longer occurs in the note.
    __tablename__ = "doc_comments"
    id = Column(String, primary_key=True, default=_uid)
    doc = Column(String, nullable=False, index=True)  # vault-relative path
    anchor = Column(Text, default="")  # the quoted text the thread is pinned to
    body = Column(Text, default="")
    author = Column(String, default="me")
    parent_id = Column(String, nullable=True, index=True)  # None = thread root
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class FileComment(Base):
    # comments on a file in the files app (6c), keyed by files-relative path. threaded like
    # DocComment: a root has parent_id == None, replies point at the root via parent_id.
    __tablename__ = "file_comments"
    id = Column(String, primary_key=True, default=_uid)
    path = Column(String, nullable=False, index=True)  # files-root-relative
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
        index=True,
    )
    normalized_path = Column(String, nullable=False, default=_normalized_path_default, index=True)
    body = Column(Text, default="")
    author = Column(String, default="me")
    parent_id = Column(String, nullable=True, index=True)  # None = thread root
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class FileOperation(Base):
    """Durable identity and state for queued Files work and later undo/recovery."""

    __tablename__ = "file_operations"
    id = Column(String, primary_key=True, default=_uid)
    action = Column(String, nullable=False, index=True)
    source_location_id = Column(String, nullable=False, index=True)
    source_path = Column(String, nullable=False, default="")
    destination_location_id = Column(String, nullable=True, index=True)
    destination_path = Column(String, default="")
    state = Column(String, nullable=False, default="queued", index=True)
    bytes_total = Column(Integer, default=0)
    bytes_done = Column(Integer, default=0)
    error_code = Column(String, default="")
    undo_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class FileOperationPathClaim(Base):
    """One canonical Files path lock; an operation may hold several at once."""

    __tablename__ = "file_operation_path_claims"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "claim_scope",
            "normalized_path",
            name="uq_file_operation_path_claim_operation_scope_path",
        ),
    )

    id = Column(String, primary_key=True, default=_uid)
    operation_id = Column(
        String,
        ForeignKey("file_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_scope = Column(String, nullable=False, index=True)
    normalized_path = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=_now)


def canonical_local_physical_claim_path(value: str, *, case_sensitive: bool = False) -> str:
    """Return the Unicode- and case-stable key used for local filesystem claims."""
    normalized = unicodedata.normalize("NFC", str(value or ""))
    return normalized if case_sensitive else unicodedata.normalize("NFC", normalized.casefold())


def local_claim_case_insensitive(path: Path) -> bool:
    """Detect case behavior inside the target filesystem without writing probe files."""
    if os.name == "nt":
        return True
    candidate = Path(path)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if not candidate.exists():
        return True

    def probe_alias(item: Path) -> bool | None:
        name = item.name
        for index, character in enumerate(name):
            swapped = character.swapcase()
            if not character.isalpha() or swapped == character:
                continue
            alias = item.with_name(f"{name[:index]}{swapped}{name[index + 1 :]}")
            try:
                return alias.exists() and os.path.samefile(item, alias)
            except OSError:
                return None
        return None

    if candidate.is_dir():
        try:
            for child in candidate.iterdir():
                result = probe_alias(child)
                if result is not None:
                    return result
        except OSError:
            return True

    try:
        parent = candidate.parent
        if parent != candidate and parent.stat().st_dev == candidate.stat().st_dev:
            result = probe_alias(candidate)
            if result is not None:
                return result
    except OSError:
        pass
    return True


def _canonicalize_file_operation_claim(_mapper, _connection, target) -> None:
    if target.claim_scope in {"local-physical", "local-physical-ci", "local-physical-cs"}:
        target.normalized_path = canonical_local_physical_claim_path(
            target.normalized_path,
            case_sensitive=target.claim_scope == "local-physical-cs",
        )


event.listen(FileOperationPathClaim, "before_insert", _canonicalize_file_operation_claim)
event.listen(FileOperationPathClaim, "before_update", _canonicalize_file_operation_claim)


def _create_file_operation_path_claim_triggers(_target, connection, **_kwargs) -> None:
    existing_path = "rtrim(existing.normalized_path, '/')"
    new_path = "rtrim(NEW.normalized_path, '/')"
    same_path = f"({existing_path} = {new_path})"
    new_descendant = f"(substr({new_path},1,length({existing_path})+1) = {existing_path} || '/')"
    existing_descendant = f"(substr({existing_path},1,length({new_path})+1) = {new_path} || '/')"
    for action in ("INSERT", "UPDATE"):
        exclude_current = "existing.id != OLD.id AND " if action == "UPDATE" else ""
        overlap = (
            f"{exclude_current}existing.claim_scope = NEW.claim_scope "
            "AND existing.operation_id != NEW.operation_id "
            f"AND ({same_path} "
            f"OR {existing_path} = '' OR {new_path} = '' "
            f"OR {new_descendant} OR {existing_descendant})"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS "
            f"trg_file_operation_path_claim_overlap_{action.lower()} "
            f"BEFORE {action} ON file_operation_path_claims FOR EACH ROW "
            f"WHEN EXISTS (SELECT 1 FROM file_operation_path_claims existing WHERE {overlap}) "
            "BEGIN SELECT RAISE(ABORT, 'file operation path already in use'); END"
        )


event.listen(
    FileOperationPathClaim.__table__,
    "after_create",
    _create_file_operation_path_claim_triggers,
)


class FileOperationSourceClaim(Base):
    """One durable exclusive claim on a mutable Files source and its path subtree."""

    __tablename__ = "file_operation_source_claims"
    __table_args__ = (
        UniqueConstraint(
            "claim_scope",
            "normalized_path",
            name="uq_file_operation_source_claim_scope_path",
        ),
    )

    operation_id = Column(
        String,
        ForeignKey("file_operations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_scope = Column(String, nullable=False, index=True)
    normalized_path = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=_now)


event.listen(FileOperationSourceClaim, "before_insert", _canonicalize_file_operation_claim)
event.listen(FileOperationSourceClaim, "before_update", _canonicalize_file_operation_claim)


def _create_file_operation_source_claim_triggers(_target, connection, **_kwargs) -> None:
    existing_path = "rtrim(existing.normalized_path, '/')"
    new_path = "rtrim(NEW.normalized_path, '/')"
    same_path = f"({existing_path} = {new_path})"
    new_descendant = f"(substr({new_path},1,length({existing_path})+1) = {existing_path} || '/')"
    existing_descendant = f"(substr({existing_path},1,length({new_path})+1) = {new_path} || '/')"
    overlap = (
        "existing.claim_scope = NEW.claim_scope AND existing.operation_id != NEW.operation_id "
        f"AND ({same_path} OR {existing_path} = '' OR {new_path} = '' "
        f"OR {new_descendant} OR {existing_descendant})"
    )
    for action in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS "
            f"trg_file_operation_source_claim_overlap_{action.lower()} "
            f"BEFORE {action} ON file_operation_source_claims FOR EACH ROW "
            f"WHEN EXISTS (SELECT 1 FROM file_operation_source_claims existing WHERE {overlap}) "
            "BEGIN SELECT RAISE(ABORT, 'file operation source already in use'); END"
        )


event.listen(
    FileOperationSourceClaim.__table__,
    "after_create",
    _create_file_operation_source_claim_triggers,
)


class OfflineFile(Base):
    """One explicitly cached Files item. Cache state is never treated as backup."""

    __tablename__ = "offline_files"
    __table_args__ = (
        UniqueConstraint("location_id", "normalized_path", name="uq_offline_files_location_path"),
    )
    id = Column(String, primary_key=True, default=_uid)
    location_id = Column(
        String,
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    normalized_path = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False, default="queued", index=True)
    cache_name = Column(String, default="")
    size = Column(Integer, default=0)
    checksum = Column(String, default="")
    etag = Column(String, default="")
    version_id = Column(String, default="")
    error_code = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
