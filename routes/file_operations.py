"""Durable Files operation queue, retry, cancel, and undo APIs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.auth import require_auth
from core.database import DEFAULT_LOCAL_STORAGE_LOCATION_ID, FileOperation, get_db
from services import file_operations

router = APIRouter(prefix="/api/files/operations", dependencies=[Depends(require_auth)])


class OperationBody(BaseModel):
    action: str
    source_location_id: str = DEFAULT_LOCAL_STORAGE_LOCATION_ID
    source_path: str
    destination_location_id: str | None = None
    destination_path: str = ""
    run_now: bool = True


def _row(db, operation_id: str) -> FileOperation:
    row = db.get(FileOperation, operation_id)
    if not row or row.action == file_operations.DIRECT_MUTATION_ACTION:
        raise HTTPException(404, "Files operation not found")
    return row


def _run(call):
    try:
        return call()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (RuntimeError, ValueError, file_operations.FileOperationError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
def list_operations(
    state: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    db: DbSession = Depends(get_db),
):
    query = db.query(FileOperation).filter(
        FileOperation.action != file_operations.DIRECT_MUTATION_ACTION
    )
    if state:
        query = query.filter(FileOperation.state == state)
    rows = query.order_by(FileOperation.created_at.desc()).limit(limit).all()
    return {"operations": [file_operations.public_dict(row) for row in rows]}


@router.post("")
def create_operation(body: OperationBody, db: DbSession = Depends(get_db)):
    row = _run(
        lambda: file_operations.enqueue(
            db,
            action=body.action,
            source_location_id=body.source_location_id,
            source_path=body.source_path,
            destination_location_id=body.destination_location_id,
            destination_path=body.destination_path,
        )
    )
    if body.run_now:
        row = _run(lambda: file_operations.run(db, row))
    return file_operations.public_dict(row)


@router.get("/{operation_id}")
def get_operation(operation_id: str, db: DbSession = Depends(get_db)):
    return file_operations.public_dict(_row(db, operation_id))


@router.post("/{operation_id}/run")
def run_operation(operation_id: str, db: DbSession = Depends(get_db)):
    row = _run(lambda: file_operations.run(db, _row(db, operation_id)))
    return file_operations.public_dict(row)


@router.post("/{operation_id}/cancel")
def cancel_operation(operation_id: str, db: DbSession = Depends(get_db)):
    row = _run(lambda: file_operations.cancel(db, _row(db, operation_id)))
    return file_operations.public_dict(row)


@router.post("/{operation_id}/retry")
def retry_operation(operation_id: str, db: DbSession = Depends(get_db)):
    row = _run(lambda: file_operations.retry(db, _row(db, operation_id)))
    return file_operations.public_dict(row)


@router.delete("/{operation_id}")
def discard_operation(operation_id: str, db: DbSession = Depends(get_db)):
    _run(lambda: file_operations.discard(db, _row(db, operation_id)))
    return {"ok": True}


@router.post("/{operation_id}/undo")
def undo_operation(operation_id: str, db: DbSession = Depends(get_db)):
    row = _run(lambda: file_operations.undo(db, _row(db, operation_id)))
    return file_operations.public_dict(row)
