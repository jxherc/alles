from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import vault_md

router = APIRouter(prefix="/api/vault-md")


@router.get("/tree")
def tree():
    return vault_md.tree()


@router.get("/file")
def read_file(path: str):
    try:
        return vault_md.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class WriteBody(BaseModel):
    path: str
    content: str = ""


@router.put("/file")
def write_file(body: WriteBody):
    try:
        return vault_md.write(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


class PathBody(BaseModel):
    path: str
    content: str = ""


@router.post("/file")
def create_file(body: PathBody):
    try:
        return vault_md.create(body.path, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/file")
def delete_file(path: str):
    try:
        return vault_md.delete(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RenameBody(BaseModel):
    path: str
    new_path: str


@router.post("/rename")
def rename_file(body: RenameBody):
    try:
        return vault_md.rename(body.path, body.new_path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/search")
def search(q: str = ""):
    return {"results": vault_md.search(q)}


@router.get("/backlinks")
def backlinks(name: str):
    return {"backlinks": vault_md.backlinks(name)}


@router.get("/names")
def names():
    return {"names": vault_md.note_names()}
