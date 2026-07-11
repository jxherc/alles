from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from core.auth import require_auth
from core.build_info import runtime_info
from core.database import get_db
from services import audit, observability, sysmon

router = APIRouter(prefix="/api/system")


@router.get("/build", dependencies=[Depends(require_auth)])
def build():
    """Public release markers and read-only gates for unfinished UI."""
    return runtime_info()


@router.get("/stats")
def stats():
    """live cpu/ram/disk/gpu snapshot (sync → runs in the threadpool; the cpu
    sample blocks ~0.12s)."""
    return sysmon.snapshot()


@router.get("/health", dependencies=[Depends(require_auth)])
def runtime_health():
    return observability.runtime_health()


@router.get("/logs", dependencies=[Depends(require_auth)])
def logs(limit: int = Query(100, ge=1, le=500)):
    return {"entries": observability.read_recent_logs(limit), "limit": limit}


@router.get("/audit", dependencies=[Depends(require_auth)])
def audit_records(limit: int = Query(100, ge=1, le=500), db: DbSession = Depends(get_db)):
    return {"entries": audit.recent(db, limit), "limit": limit}
