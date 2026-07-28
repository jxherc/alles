from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.database import ModelEndpoint, get_db
from core.settings import load_settings
from services import obsidian_setup, setup_state

router = APIRouter(prefix="/api/setup")


def _response(db: DbSession) -> dict:
    endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()
    with_models = [endpoint for endpoint in endpoints if endpoint.models_list()]
    state = setup_state.public_state()
    return {
        "configured": bool(with_models) or state["completed"],
        "endpoints": len(endpoints),
        "endpoints_with_models": len(with_models),
        "setup": state,
    }


@router.get("/status")
def status(db: DbSession = Depends(get_db)):
    return _response(db)


class SetupStepBody(BaseModel):
    step: str
    values: dict


@router.patch("/step")
def save_step(body: SetupStepBody, db: DbSession = Depends(get_db)):
    try:
        setup_state.save_step(body.step, body.values)
    except setup_state.SetupStateError as exc:
        raise ApiError(
            400, "invalid_setup_access" if body.step == "access" else "invalid_setup_step", str(exc)
        ) from exc
    return _response(db)


@router.post("/dismiss")
def dismiss(db: DbSession = Depends(get_db)):
    setup_state.dismiss()
    return _response(db)


@router.post("/resume")
def resume(db: DbSession = Depends(get_db)):
    setup_state.resume()
    return _response(db)


@router.post("/complete")
def complete(db: DbSession = Depends(get_db)):
    try:
        setup_state.complete()
    except setup_state.SetupStateError as exc:
        raise ApiError(409, "setup_incomplete", str(exc)) from exc
    return _response(db)


def _configured_vault() -> Path | None:
    raw = load_settings().get("vault_dir")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


@router.get("/obsidian")
def obsidian_status():
    vault = _configured_vault()
    if vault is None or not vault.is_dir():
        return {
            "vault_connected": False,
            "obsidian_detected": bool(obsidian_setup.detect_obsidian()),
            "obsidian_path": obsidian_setup.detect_obsidian() or "",
            "companion_installed": False,
            "companion_integrity": "not-installed",
            "plugin_path": "",
        }
    return {"vault_connected": True, **obsidian_setup.status(vault)}


class ObsidianInstallBody(BaseModel):
    approve: bool = False


@router.post("/obsidian", dependencies=[Depends(require_recent_owner)])
def install_obsidian(body: ObsidianInstallBody):
    if not body.approve:
        raise ApiError(400, "explicit_approval_required", "approve the optional companion first")
    vault = _configured_vault()
    if vault is None:
        raise ApiError(
            409, "vault_not_connected", "connect a Vault before installing the companion"
        )
    try:
        return {"vault_connected": True, **obsidian_setup.install_companion(vault)}
    except obsidian_setup.ObsidianSetupError as exc:
        raise ApiError(409, "obsidian_companion_refused", str(exc)) from exc
