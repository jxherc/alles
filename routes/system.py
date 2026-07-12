from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_auth, require_recent_owner
from core.build_info import runtime_info
from core.database import get_db
from services import audit, managed_searxng, observability, service_manager, sysmon

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


@router.get("/services", dependencies=[Depends(require_auth)])
def services():
    return {"services": service_manager.list_services()}


@router.get("/searxng", dependencies=[Depends(require_auth)])
def searxng_status():
    return managed_searxng.status()


@router.post("/searxng/{action}", dependencies=[Depends(require_recent_owner)])
def manage_searxng(
    action: Literal["install", "update", "rollback", "uninstall", "test"],
    request: Request,
):
    try:
        if action == "install":
            result = managed_searxng.install()
        elif action == "update":
            result = managed_searxng.update()
        elif action == "rollback":
            result = managed_searxng.rollback()
        elif action == "uninstall":
            result = managed_searxng.uninstall_keep_data()
        else:
            result = managed_searxng.json_search("alles self hosted search")
    except managed_searxng.ManagedSearxngRollback as exc:
        raise ApiError(409, "searxng_update_rolled_back", str(exc)) from exc
    except managed_searxng.ManagedSearxngError as exc:
        raise ApiError(409, "searxng_manage_failed", str(exc)) from exc
    audit.record(
        action=f"service.searxng.{action}",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target="searxng",
        details={"manager": "owned_compose"},
    )
    return result


@router.post("/services/{service_id}/{action}", dependencies=[Depends(require_recent_owner)])
def control_service(
    service_id: str,
    action: Literal["start", "stop", "restart"],
    request: Request,
):
    try:
        result = service_manager.control(service_id, action)
    except service_manager.ServiceOwnershipError as exc:
        raise ApiError(409, "service_not_owned", str(exc)) from exc
    except service_manager.ServiceControlError as exc:
        raise ApiError(409, "service_control_failed", str(exc)) from exc
    audit.record(
        action=f"service.{action}",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"manager": "owned_service"},
    )
    return result
