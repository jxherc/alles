"""Owner-controlled read-only bank aggregation."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.auth import require_auth, require_recent_owner
from core.database import get_db
from core.api_errors import ApiError
from services import finance_connectors

router = APIRouter(prefix="/api/finance/connections", dependencies=[Depends(require_auth)])


class SimpleFINBody(BaseModel):
    setup_token: str


class PlaidConfigBody(BaseModel):
    client_id: str
    secret: str
    environment: str = "sandbox"


class PlaidExchangeBody(BaseModel):
    public_token: str


def _error(exc: Exception):
    raise ApiError(409, "finance_connection_failed", str(exc)) from exc


@router.get("")
def connections(db: DbSession = Depends(get_db)):
    return {"providers": list(finance_connectors.PROVIDERS), "connections": finance_connectors.list_connections(db)}


@router.post("/simplefin", dependencies=[Depends(require_recent_owner)])
def connect_simplefin(body: SimpleFINBody, db: DbSession = Depends(get_db)):
    try:
        return finance_connectors.connect_simplefin(db, body.setup_token)
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)


@router.post("/plaid", dependencies=[Depends(require_recent_owner)])
def configure_plaid(body: PlaidConfigBody, db: DbSession = Depends(get_db)):
    try:
        return finance_connectors.configure_plaid(
            db, client_id=body.client_id, secret=body.secret, environment=body.environment
        )
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)


@router.post("/{connection_id}/plaid/link-token", dependencies=[Depends(require_recent_owner)])
def plaid_link_token(connection_id: str, request: Request, db: DbSession = Depends(get_db)):
    redirect_uri = str(request.url_for("finance_plaid_return"))
    try:
        return finance_connectors.plaid_link_token(db, connection_id, redirect_uri=redirect_uri)
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)


@router.get("/plaid/return", name="finance_plaid_return")
def plaid_return():
    return {"ok": True, "message": "return to Alles to finish connecting Plaid"}


@router.post("/{connection_id}/plaid/exchange", dependencies=[Depends(require_recent_owner)])
def plaid_exchange(connection_id: str, body: PlaidExchangeBody, db: DbSession = Depends(get_db)):
    try:
        return finance_connectors.exchange_plaid_public_token(db, connection_id, body.public_token)
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)


@router.post("/{connection_id}/sync", dependencies=[Depends(require_recent_owner)])
def sync(connection_id: str, db: DbSession = Depends(get_db)):
    try:
        return finance_connectors.sync(db, connection_id)
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)


@router.delete("/{connection_id}", dependencies=[Depends(require_recent_owner)])
def disconnect(connection_id: str, db: DbSession = Depends(get_db)):
    try:
        return finance_connectors.disconnect(db, connection_id)
    except finance_connectors.FinanceConnectorError as exc:
        _error(exc)
