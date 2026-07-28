"""Owner-gated controls for the explicit, reversible Journal-to-Markdown copy flow."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import get_db
from core.settings import load_settings
from routes.journal import _require_unlock
from services import journal_migration, vault_md

router = APIRouter(
    prefix="/api/journal-migration",
    dependencies=[Depends(require_recent_owner), Depends(_require_unlock)],
)


class PrepareBody(BaseModel):
    confirmation: str


def _run(operation):
    try:
        return operation()
    except vault_md.DocumentConflictError as exc:
        raise ApiError(409, "journal_migration_conflict", str(exc)) from exc
    except PermissionError as exc:
        raise ApiError(403, "journal_migration_locked", str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError(404, "journal_migration_missing", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_journal_migration", str(exc)) from exc


@router.get("/plan")
def migration_plan(db: DbSession = Depends(get_db)):
    return _run(lambda: journal_migration.migration_plan(db))


@router.post("/prepare")
def prepare_migration(body: PrepareBody, db: DbSession = Depends(get_db)):
    locked = bool(load_settings().get("journal_passcode"))
    return _run(
        lambda: journal_migration.prepare(db, body.confirmation, locked_session_confirmed=locked)
    )


@router.get("/{operation_id}")
def migration_status(operation_id: str):
    return _run(lambda: journal_migration.status(operation_id))


@router.post("/{operation_id}/apply")
def apply_migration(operation_id: str, db: DbSession = Depends(get_db)):
    return _run(lambda: journal_migration.apply(db, operation_id))


@router.post("/{operation_id}/rollback")
def rollback_migration(operation_id: str):
    return _run(lambda: journal_migration.rollback(operation_id))
