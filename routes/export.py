"""3h - unified export endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from services import exporters

router = APIRouter(prefix="/api/export")


@router.get("")
def list_kinds():
    return {"kinds": exporters.kinds()}


@router.get("/{kind}")
def export_kind(kind: str, format: str = "json", db: DbSession = Depends(get_db)):
    try:
        content, media, fname = exporters.export(db, kind, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(
        content,
        media_type=media,
        headers={"content-disposition": f'attachment; filename="{fname}"'},
    )
