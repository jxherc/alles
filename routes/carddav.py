from fastapi import APIRouter
from pydantic import BaseModel

from services import carddav_sync

router = APIRouter(prefix="/api/carddav")


@router.get("/status")
def status():
    return carddav_sync.status()


class Conn(BaseModel):
    url: str = ""
    username: str = ""
    password: str = ""


@router.post("/connect")
def connect(body: Conn):
    carddav_sync.save_cfg(
        {"url": body.url.strip(), "username": body.username.strip(), "password": body.password}
    )
    return carddav_sync.status()


@router.post("/disconnect")
def disconnect():
    carddav_sync.save_cfg({"url": "", "username": "", "password": ""})
    return carddav_sync.status()


class Interval(BaseModel):
    interval: str = "off"


@router.post("/interval")
def set_interval(body: Interval):
    carddav_sync.set_interval(body.interval)
    return carddav_sync.status()


@router.post("/sync")
def sync():
    return carddav_sync.sync()
