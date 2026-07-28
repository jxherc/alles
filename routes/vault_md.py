"""Docs API over the owner's Markdown vault.

Docs is viewer-first and Obsidian remains the primary editor. Alles also offers an explicit,
local CodeMirror editor backed by private drafts, expected-hash saves, conflict copies, and
revisions. The service layer remains shared by Docs, Aide retrieval, search, and Notes.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.database import get_db
from services import document_safety, trash, vault_md

router = APIRouter(prefix="/api/vault-md")
VAULT_WATCH_INTERVAL = 0.5
VAULT_KEEPALIVE_SECONDS = 20


def _norm_path(rel: str) -> str:
    from pathlib import PurePosixPath

    rel = (rel or "").replace("\\", "/")
    return rel if PurePosixPath(rel).suffix else rel + ".md"


def _is_note(path):
    # notes live under Notes/ and are indexed as the "note" kind (keyed by stem), not "doc",
    # so they aren't double-indexed. see services/notes_vault.py
    return (path or "").replace("\\", "/").startswith("Notes/")


def _journal_day(path):
    # journal daily notes (Journal/YYYY-MM-DD.md) are synced to the DB + indexed as the
    # "journal" kind by services/journal_vault, not as docs. returns the day or None.
    from services import journal_vault

    return journal_vault.is_daily(path)


def _note_stem(path):
    from pathlib import PurePosixPath

    return PurePosixPath((path or "").replace("\\", "/")).stem


# keep the reusable text index in sync with the vault (best-effort, never breaks a write)
def _reindex_doc(path, content):
    try:
        from core.database import SessionLocal
        from services import textindex

        db = SessionLocal()
        try:
            if _is_note(path):
                from services import personal_index

                personal_index.index_record(db, "note", _note_stem(path))
            elif _journal_day(path):
                pass  # journal daily notes are synced + indexed via the watcher, not as docs
            else:
                textindex.index(db, "doc", path, content)
        finally:
            db.close()
    except Exception:
        pass


def _sync_changed(path):
    """a file changed on disk: fold journal daily notes back into the DB, index everything else."""
    day = _journal_day(path)
    if day:
        from core.database import SessionLocal
        from services import journal_vault

        db = SessionLocal()
        try:
            journal_vault.sync_from_vault(db, day)
        finally:
            db.close()
        return
    _reindex_doc(path, vault_md.read(path).get("content", ""))


def _unindex_doc(path):
    try:
        from core.database import SessionLocal
        from services import textindex

        db = SessionLocal()
        try:
            if _is_note(path):
                from services import personal_index

                personal_index.remove_record(db, "note", _note_stem(path))
            else:
                textindex.remove(db, "doc", path)
        finally:
            db.close()
    except Exception:
        pass


def _sync_rename_indexes(manifest: dict) -> None:
    state = manifest.get("state")
    if state == "complete":
        old_path = manifest.get("old_path", "")
        current_paths = {manifest.get("new_path", "")}
        current_paths.update(change.get("path_after", "") for change in manifest.get("changes", []))
        _unindex_doc(old_path)
    elif state == "rolled_back":
        current_paths = {manifest.get("old_path", "")}
        current_paths.update(
            change.get("path_before", "") for change in manifest.get("changes", [])
        )
        _unindex_doc(manifest.get("new_path", ""))
    else:
        return

    for path in sorted(current_paths):
        if not path:
            continue
        document = vault_md.read(path)
        if document.get("exists"):
            _reindex_doc(path, document.get("content", ""))


# ── read / browse ────────────────────────────────────────────────────────────
@router.get("/tree")
def tree():
    return vault_md.tree()


@router.get("/file")
def read_file(path: str):
    try:
        return vault_md.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/raw")
def raw_asset(path: str):
    """serve an embedded asset (image/pdf/etc.) by path or bare name — for ![[ ]] embeds."""
    resolved = vault_md.find_asset(path) or path
    try:
        data, mime = vault_md.file_bytes(resolved)
    except ValueError:
        raise HTTPException(404, "asset not found")
    return Response(content=data, media_type=mime, headers={"cache-control": "no-cache"})


@router.get("/search")
def search(q: str = ""):
    return {"results": vault_md.search(q)}


@router.get("/grep")
def grep(q: str = ""):
    return {"results": vault_md.full_text_search(q)}


@router.get("/tags")
def tags():
    return {"tags": vault_md.all_tags()}


@router.get("/tag")
def by_tag(tag: str):
    return {"notes": vault_md.notes_with_tag(tag)}


@router.get("/preview")
def preview_note(name: str):
    """resolve a wikilink name → a short excerpt for the hover preview."""
    name = (name or "").strip()
    if not name:
        return {"found": False, "excerpt": ""}
    hits = vault_md.search(name)
    hit = next((h for h in hits if (h.get("name", "").lower() == name.lower())), None)
    if not hit and hits:
        hit = hits[0]
    if not hit:
        return {"found": False, "excerpt": ""}
    doc = vault_md.read(hit["path"])
    body = doc.get("content", "")
    try:
        _, body = vault_md.parse_frontmatter(body)
    except Exception:
        pass
    return {
        "found": True,
        "path": hit["path"],
        "title": hit.get("name", name),
        "excerpt": body.strip()[:240],
    }


@router.get("/backlinks")
def backlinks(name: str):
    return {"backlinks": vault_md.backlinks(name)}


@router.get("/unlinked")
def unlinked(name: str):
    return {"mentions": vault_md.unlinked_mentions(name)}


@router.get("/names")
def names():
    return {"names": vault_md.note_names()}


@router.get("/ask")
def ask_vault(q: str = "", db: DbSession = Depends(get_db)):
    """ask-anything over the vault — semantic retrieval via the shared text index."""
    from routes.textindex import _collect_docs
    from services import textindex

    if not textindex.stats(db).get("doc"):
        textindex.reindex_kind(db, "doc", _collect_docs())
    hits = textindex.search(db, q, kind="doc", k=6) if q else []
    return {"q": q, "sources": hits}


# ── basic file management (content editing happens in Obsidian) ───────────────
class PathBody(BaseModel):
    path: str
    content: str = ""
    unique: bool = False


class SafeDocumentBody(BaseModel):
    path: str
    content: str
    expected_hash: str


class DraftBody(BaseModel):
    path: str
    content: str
    base_hash: str
    write_session: str = Field(default="", max_length=80)
    write_revision: int = Field(default=0, ge=0)
    write_generation: int = Field(default=0, ge=0)


class RevisionRestoreBody(BaseModel):
    path: str
    revision_id: str
    expected_hash: str


@router.get("/safety/draft")
def read_document_draft(path: str):
    try:
        return {"draft": document_safety.load_draft(path)}
    except (ValueError, document_safety.RecoveryConflict) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/safety/draft")
def write_document_draft(body: DraftBody):
    try:
        return document_safety.save_draft(
            body.path,
            body.content,
            body.base_hash,
            body.write_session,
            body.write_revision,
            body.write_generation,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/safety/draft")
def remove_document_draft(path: str, expected_hash: str = ""):
    try:
        deleted = (
            document_safety.delete_draft_if_hash(path, expected_hash)
            if expected_hash
            else document_safety.delete_draft(path)
        )
        if expected_hash and not deleted and document_safety.load_draft(path) is not None:
            raise HTTPException(409, "draft changed before it could be deleted")
        return {"ok": True, "deleted": deleted}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/safety/compare")
def compare_document(body: SafeDocumentBody):
    try:
        return document_safety.compare_document(body.path, body.content, body.expected_hash)
    except vault_md.DocumentEncodingError as exc:
        raise ApiError(409, "document_encoding_unsupported", str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/safety/save")
def save_document(body: SafeDocumentBody):
    try:
        result = document_safety.save_document(body.path, body.content, body.expected_hash)
    except document_safety.DocumentSaveConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "code": "document_conflict",
                "detail": "document changed outside Alles; both copies were preserved",
                "conflict": exc.conflict,
            },
        )
    except vault_md.DocumentEncodingError as exc:
        raise ApiError(409, "document_encoding_unsupported", str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _reindex_doc(result["path"], body.content)
    return result


@router.get("/safety/conflicts/{conflict_id}")
def read_document_conflict(conflict_id: str):
    try:
        return document_safety.load_conflict(conflict_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (OSError, document_safety.RecoveryConflict) as exc:
        raise HTTPException(404, "conflict copy not found") from exc


@router.get("/safety/revisions")
def document_revisions(path: str):
    try:
        return {"revisions": document_safety.list_revisions(path)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/safety/revisions/restore")
def restore_document_revision(body: RevisionRestoreBody):
    try:
        result = document_safety.restore_revision(body.path, body.revision_id, body.expected_hash)
    except vault_md.DocumentConflictError as exc:
        raise ApiError(409, "document_conflict", str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (OSError, document_safety.RecoveryConflict) as exc:
        raise HTTPException(404, "revision not found") from exc
    document = vault_md.read(result["path"])
    _reindex_doc(result["path"], document.get("content", ""))
    return result


@router.post("/file")
def create_file(body: PathBody, background_tasks: BackgroundTasks):
    try:
        out = (
            vault_md.create_unique(body.path, body.content)
            if body.unique
            else vault_md.create(body.path, body.content)
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = out.get("path", _norm_path(body.path))
    background_tasks.add_task(_reindex_doc, path, vault_md.read(path).get("content", ""))
    return out


@router.delete("/file")
def delete_file(path: str, db: DbSession = Depends(get_db)):
    try:
        resolved = vault_md._safe(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if resolved == vault_md.root_dir():
        raise HTTPException(400, "won't delete the vault root")
    if not resolved.exists():
        raise HTTPException(404, "not found")
    ref = str(resolved.relative_to(vault_md.root_dir())).replace("\\", "/")
    item = trash.soft_delete_path(db, "vault", ref, resolved)
    if ref.lower().endswith((".md", ".markdown")):
        _unindex_doc(ref)
    return {"ok": True, "trashed": True, "trash_id": item.id}


@router.get("/trash")
def list_trash(db: DbSession = Depends(get_db)):
    return [
        {
            "id": item.id,
            "path": item.ref,
            "name": item.name,
            "trashed_at": item.trashed_at.isoformat() if item.trashed_at else None,
        }
        for item in trash.list_items(db, kind="vault")
    ]


class TrashAction(BaseModel):
    id: str


@router.post("/trash/restore")
def restore_trash(body: TrashAction, db: DbSession = Depends(get_db)):
    item = trash.get(db, body.id)
    if not item or item.kind != "vault":
        raise HTTPException(404, "trash item not found")
    try:
        destination = vault_md._safe(item.ref)
        trash.restore_path(db, item, destination)
    except FileExistsError as exc:
        raise ApiError(409, "restore_conflict", "a document already exists at that path") from exc
    if destination.is_file() and destination.suffix.lower() in {".md", ".markdown"}:
        _reindex_doc(item.ref, vault_md.read(item.ref).get("content", ""))
    return {"ok": True, "restored": item.ref}


class RenameBody(BaseModel):
    path: str
    new_path: str


@router.post("/rename")
def rename_file(body: RenameBody):
    try:
        source = vault_md._safe(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if source.is_file():
        try:
            manifest = document_safety.rename_document(body.path, body.new_path)
        except FileNotFoundError as exc:
            raise HTTPException(404, "document not found") from exc
        except FileExistsError as exc:
            raise ApiError(
                409, "rename_destination_exists", "a document already exists at that path"
            ) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except document_safety.RenameRecoveryRequired as exc:
            raise ApiError(
                409,
                "rename_recovery_required",
                "rename paused safely; use the pending recovery transaction",
                headers={"x-alles-recovery-id": exc.transaction_id},
            ) from exc
        _sync_rename_indexes(manifest)
        return {
            "ok": True,
            "path": manifest["new_path"],
            "links_rewritten": len(manifest.get("changes", [])),
            "transaction_id": manifest["id"],
        }

    try:
        out = vault_md.rename(body.path, body.new_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "folder not found") from exc
    except FileExistsError as exc:
        raise ApiError(409, "rename_destination_exists", "a folder already exists there") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    new_path = out.get("path", _norm_path(body.new_path))
    out["links_rewritten"] = 0
    # folder rename: reindex each child at its new path (old entries get cleaned by reconcile)
    base = vault_md.vault_dir()
    old_pre = body.path.strip("/") + "/"
    new_pre = new_path.strip("/") + "/"
    for p in (base / new_path).rglob("*.md"):
        rel_new = str(p.relative_to(base)).replace("\\", "/")
        rel_old = old_pre + rel_new[len(new_pre) :]
        _unindex_doc(rel_old)
        try:
            content = vault_md._read_text_for_edit(p)
        except vault_md.DocumentEncodingError:
            content = ""
        _reindex_doc(rel_new, content)
    return out


class RenameRecoveryBody(BaseModel):
    id: str
    action: str


@router.get("/rename/pending")
def pending_renames():
    return {"transactions": document_safety.pending_renames()}


@router.post("/rename/recover")
def recover_rename(body: RenameRecoveryBody):
    try:
        if body.action == "resume":
            manifest = document_safety.resume_rename(body.id)
        elif body.action == "rollback":
            manifest = document_safety.rollback_rename(body.id)
        else:
            raise HTTPException(400, "action must be resume or rollback")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except document_safety.RecoveryConflict as exc:
        raise ApiError(409, "rename_recovery_conflict", str(exc)) from exc
    _sync_rename_indexes(manifest)
    return {"ok": True, "transaction": manifest}


class FolderBody(BaseModel):
    path: str


@router.post("/folder")
def make_folder(body: FolderBody):
    try:
        return vault_md.create_folder(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── live two-way: notice files changed on disk (e.g. edited in Obsidian) ───────
def _vault_sig() -> dict:
    """Nanosecond mtime and size signature for cheap external-change detection."""
    base = vault_md.vault_dir()
    out = {}
    for p in base.rglob("*.md"):
        rel = str(p.relative_to(base)).replace("\\", "/")
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        try:
            st = p.stat()
            out[rel] = f"{st.st_mtime_ns}:{st.st_size}"
        except OSError:
            pass
    return out


def _sig_diff(prev: dict, cur: dict):
    """(changed_or_added, removed) rel-paths between two signatures."""
    changed = [p for p in cur if prev.get(p) != cur[p]]
    removed = [p for p in prev if p not in cur]
    return changed, removed


def _observed_event(path: str, *, removed: bool = False) -> dict:
    current_hash = ""
    if not removed:
        try:
            current_hash = vault_md.read(path).get("hash", "")
        except (OSError, ValueError):
            pass
    try:
        origin = document_safety.classify_observed_change(path, current_hash)
    except Exception:
        origin = "external"
    return {
        "path": path,
        "kind": "removed" if removed else "changed",
        "origin": origin,
        "hash": current_hash,
    }


@router.get("/stream")
async def stream():
    """SSE: push {changed, removed} when vault files change on disk, and reindex the changed
    docs so search/recall reflect Obsidian edits. the UI re-renders on each event."""
    import asyncio
    import json as _json

    async def gen():
        prev = await asyncio.to_thread(_vault_sig)
        yield 'data: {"hello":1}\n\n'
        idle = 0
        while True:
            await asyncio.sleep(VAULT_WATCH_INTERVAL)
            cur = await asyncio.to_thread(_vault_sig)
            changed, removed = _sig_diff(prev, cur)
            if not (changed or removed):
                idle += 1
                if idle * VAULT_WATCH_INTERVAL >= VAULT_KEEPALIVE_SECONDS:
                    idle = 0
                    yield ": ping\n\n"
                continue
            idle = 0
            prev = cur
            events = [*(_observed_event(path) for path in changed)]
            events.extend(_observed_event(path, removed=True) for path in removed)
            for p in changed:  # keep the index fresh (idempotent); journal notes sync to the DB
                try:
                    await asyncio.to_thread(lambda q=p: _sync_changed(q))
                except Exception:
                    pass
            for p in removed:
                _unindex_doc(p)
            yield f"data: {_json.dumps({'changed': changed, 'removed': removed, 'events': events})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
