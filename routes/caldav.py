from fastapi import APIRouter
from pydantic import BaseModel

from services import caldav_sync

router = APIRouter(prefix="/api/caldav")


@router.get("/status")
def status():
    return caldav_sync.status()


class Conn(BaseModel):
    url: str = ""
    username: str = ""
    password: str = ""


@router.post("/connect")
def connect(body: Conn):
    caldav_sync.save_cfg(
        {"url": body.url.strip(), "username": body.username.strip(), "password": body.password}
    )
    return caldav_sync.status()


@router.post("/sync")
def sync():
    # runs in a threadpool (sync def) — network-bound, fine
    return caldav_sync.sync()
