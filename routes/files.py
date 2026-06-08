from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services import files_store as fs

router = APIRouter(prefix="/api/files")


@router.get("/list")
def list_files(path: str = Query("")):
    try:
        return fs.listdir(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/read")
def read_file(path: str = Query(...)):
    try:
        return fs.read_text(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/raw")
def raw_file(path: str = Query(...), download: bool = False):
    try:
        p = fs.abspath(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.is_file():
        raise HTTPException(404)
    # inline by default so images preview; download=1 forces a save dialog
    return FileResponse(str(p), filename=p.name if download else None)


class MkdirBody(BaseModel):
    path: str


@router.post("/mkdir")
def mkdir(body: MkdirBody):
    try:
        return fs.mkdir(body.path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RenameBody(BaseModel):
    path: str
    to: str


@router.post("/rename")
def rename(body: RenameBody):
    try:
        return fs.rename(body.path, body.to)
    except FileNotFoundError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/delete")
def delete(path: str = Query(...)):
    try:
        return fs.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    try:
        return fs.save_upload(path, file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
