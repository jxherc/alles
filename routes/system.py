from fastapi import APIRouter, Depends

from core.auth import require_auth
from core.build_info import runtime_info
from services import sysmon

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
