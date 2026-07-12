"""Owner APIs for scoped grants and durable delegated approvals."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import CapabilityGrant, CapabilityGrantEvent, DelegatedAction, get_db
from services.delegated_actions import create_grant, decide_action, revoke_grant

router = APIRouter(prefix="/api/delegation")


def _bad(exc: ValueError):
    code = str(exc)
    raise ApiError(400, code, code.replace("_", " ")) from exc


def _grant(row: CapabilityGrant) -> dict:
    return {
        "id": row.id,
        "scope_kind": row.scope_kind,
        "scope_id": row.scope_id or "",
        "capability": row.capability,
        "target_root": row.target_root or "",
        "access_mode": row.access_mode,
        "state": row.state,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_at": row.created_at.isoformat(),
    }


def _action(row: DelegatedAction) -> dict:
    return {
        "id": row.id,
        "origin": row.origin,
        "run_id": row.run_id,
        "agent_run_id": row.agent_run_id,
        "session_id": row.session_id,
        "grant_id": row.grant_id,
        "scope_kind": row.scope_kind,
        "scope_id": row.scope_id or "",
        "capability": row.capability,
        "action": row.action,
        "target": row.target or "",
        "data_summary": row.data_summary or "",
        "privacy_effect": row.privacy_effect or "",
        "cost": row.cost or "",
        "exact_hash": row.exact_hash,
        "state": row.state,
        "expires_at": row.expires_at.isoformat(),
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "used_at": row.used_at.isoformat() if row.used_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat(),
    }


class GrantBody(BaseModel):
    scope_kind: str
    scope_id: str = ""
    capability: str
    target_root: str = ""
    access_mode: str = "read"
    expires_at: datetime | None = None


@router.get("/grants")
def list_grants(db: DbSession = Depends(get_db)):
    return [
        _grant(row)
        for row in db.query(CapabilityGrant).order_by(CapabilityGrant.created_at.desc()).all()
    ]


@router.post("/grants", dependencies=[Depends(require_recent_owner)])
def add_grant(body: GrantBody, db: DbSession = Depends(get_db)):
    try:
        row = create_grant(db, **body.model_dump())
    except ValueError as exc:
        _bad(exc)
    db.commit()
    db.refresh(row)
    return _grant(row)


@router.delete("/grants/{grant_id}", dependencies=[Depends(require_recent_owner)])
def remove_grant(grant_id: str, db: DbSession = Depends(get_db)):
    row = db.get(CapabilityGrant, grant_id)
    if not row:
        raise HTTPException(404)
    revoke_grant(db, row)
    db.commit()
    db.refresh(row)
    return _grant(row)


@router.get("/actions")
def list_actions(state: str = "pending", limit: int = 100, db: DbSession = Depends(get_db)):
    query = db.query(DelegatedAction)
    if state:
        query = query.filter_by(state=state)
    rows = query.order_by(DelegatedAction.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [_action(row) for row in rows]


class DecisionBody(BaseModel):
    allow: bool
    exact_hash: str


@router.post("/actions/{action_id}/decision", dependencies=[Depends(require_recent_owner)])
def action_decision(
    action_id: str,
    body: DecisionBody,
    db: DbSession = Depends(get_db),
):
    row = db.get(DelegatedAction, action_id)
    if not row:
        raise HTTPException(404)
    try:
        decide_action(db, row, allow=body.allow, exact_hash=body.exact_hash)
    except ValueError as exc:
        db.commit()  # preserve expiry/denial audit events
        _bad(exc)
    db.commit()
    db.refresh(row)
    return _action(row)


@router.get("/events")
def list_events(limit: int = 100, db: DbSession = Depends(get_db)):
    rows = (
        db.query(CapabilityGrantEvent)
        .order_by(CapabilityGrantEvent.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        {
            "id": row.id,
            "grant_id": row.grant_id,
            "action_id": row.action_id,
            "kind": row.kind,
            "actor": row.actor,
            "scope_kind": row.scope_kind,
            "scope_id": row.scope_id,
            "capability": row.capability,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
