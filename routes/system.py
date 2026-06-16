from fastapi import APIRouter

from services import sysmon

router = APIRouter(prefix="/api/system")


@router.get("/stats")
def stats():
    """live cpu/ram/disk/gpu snapshot (sync → runs in the threadpool; the cpu
    sample blocks ~0.12s)."""
    return sysmon.snapshot()
