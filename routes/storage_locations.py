import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.auth import require_recent_owner
from core.database import StorageLocation, get_db
from services import storage_index, storage_locations

router = APIRouter(prefix="/api/storage-locations")


class LocationBody(BaseModel):
    name: str
    kind: str
    access: str = "read_only"
    root_path: str = ""
    endpoint: str = ""
    bucket: str = ""
    prefix: str = ""
    config: dict = Field(default_factory=dict)
    credentials: dict = Field(default_factory=dict)
    enabled: bool = True


class LocationUpdate(BaseModel):
    name: str | None = None
    access: str | None = None
    root_path: str | None = None
    endpoint: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    config: dict | None = None
    credentials: dict | None = None
    enabled: bool | None = None


@router.get("")
def list_locations(db: DbSession = Depends(get_db)):
    storage_locations.ensure_default_local(db)
    rows = (
        db.query(StorageLocation)
        .order_by(StorageLocation.is_default.desc(), StorageLocation.name)
        .all()
    )
    return {"locations": [storage_locations.public_dict(row) for row in rows]}


@router.post("", dependencies=[Depends(require_recent_owner)])
def create_location(body: LocationBody, db: DbSession = Depends(get_db)):
    storage_locations.ensure_default_local(db)
    try:
        clean = storage_locations.validate_values(
            name=body.name,
            kind=body.kind,
            access=body.access,
            root_path=body.root_path,
            endpoint=body.endpoint,
            bucket=body.bucket,
        )
        prefix = storage_locations.normalize_path(body.prefix)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        config = storage_locations.clean_config(clean["kind"], body.config)
        credentials = storage_locations.clean_credentials(clean["kind"], body.credentials)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = StorageLocation(
        **clean,
        prefix=prefix,
        config=json.dumps(config, sort_keys=True),
        secret=json.dumps(credentials, sort_keys=True) if credentials else "",
        enabled=bool(body.enabled),
        is_default=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return storage_locations.public_dict(row)


@router.patch("/{location_id}", dependencies=[Depends(require_recent_owner)])
def update_location(location_id: str, body: LocationUpdate, db: DbSession = Depends(get_db)):
    row = db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "storage location not found")
    proposed = {
        "name": body.name if body.name is not None else row.name,
        "kind": row.kind,
        "access": body.access if body.access is not None else row.access,
        "root_path": body.root_path if body.root_path is not None else row.root_path,
        "endpoint": body.endpoint if body.endpoint is not None else row.endpoint,
        "bucket": body.bucket if body.bucket is not None else row.bucket,
    }
    try:
        clean = storage_locations.validate_values(**proposed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    immutable = {
        "root_path": row.root_path,
        "endpoint": row.endpoint,
        "bucket": row.bucket,
    }
    if any(clean[key] != current for key, current in immutable.items()):
        raise HTTPException(409, "storage coordinates cannot be changed; add a new location")
    if body.prefix is not None:
        try:
            prefix = storage_locations.normalize_path(body.prefix)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if prefix != (row.prefix or ""):
            raise HTTPException(409, "storage coordinates cannot be changed; add a new location")
    if body.config is not None:
        try:
            config = storage_locations.clean_config(row.kind, body.config)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        current_config = json.loads(row.config or "{}")
        if config != current_config:
            raise HTTPException(409, "storage coordinates cannot be changed; add a new location")
    row.name = clean["name"]
    row.access = clean["access"]
    if body.credentials is not None:
        try:
            credentials = storage_locations.clean_credentials(row.kind, body.credentials)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        row.secret = json.dumps(credentials, sort_keys=True) if credentials else ""
    if body.enabled is not None:
        if row.is_default and not body.enabled:
            raise HTTPException(409, "the default local location cannot be disabled")
        row.enabled = bool(body.enabled)
    db.commit()
    db.refresh(row)
    return storage_locations.public_dict(row)


@router.delete("/{location_id}", dependencies=[Depends(require_recent_owner)])
def remove_location(location_id: str, db: DbSession = Depends(get_db)):
    row = db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "storage location not found")
    if row.is_default:
        raise HTTPException(409, "the default local location cannot be removed")
    if storage_index.is_active(location_id):
        raise HTTPException(409, "storage location is being indexed")
    if storage_locations.has_references(db, location_id):
        raise HTTPException(409, "storage location still has Files metadata")
    storage_locations.clear_derived_index(db, location_id)
    db.delete(row)
    db.commit()
    storage_index.forget(location_id)
    return {"ok": True}


@router.post("/{location_id}/test", dependencies=[Depends(require_recent_owner)])
def test_location(location_id: str, db: DbSession = Depends(get_db)):
    row = db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "storage location not found")
    return storage_locations.test_location(row)


@router.get("/{location_id}/index")
def index_status(location_id: str, db: DbSession = Depends(get_db)):
    row = db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "storage location not found")
    return storage_index.status(location_id)


@router.post("/{location_id}/index", dependencies=[Depends(require_recent_owner)])
def index_location(
    location_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession = Depends(get_db),
):
    row = db.get(StorageLocation, location_id)
    if not row:
        raise HTTPException(404, "storage location not found")
    if not row.enabled:
        raise HTTPException(409, "storage location is disabled")
    result, accepted = storage_index.enqueue(location_id)
    if accepted:
        background_tasks.add_task(storage_index.run, location_id)
    return result
