"""Read-only SimpleFIN and Plaid aggregation with durable, encrypted credentials.

The connector never receives a bank password and never exposes stored tokens through its
public API. Provider data is imported into the active Finance authority with stable provenance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import uuid
from datetime import UTC, date, datetime
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from core.database import Account, FinanceConnection, SessionLocal, Transaction
from services import actual_finance, finance_currency, net_guard

PLAID_BASES = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
PROVIDERS = (
    {
        "id": "simplefin",
        "label": "SimpleFIN",
        "regions": ["US", "CA"],
        "auth": "one-time setup token",
        "read_only": True,
    },
    {
        "id": "plaid",
        "label": "Plaid",
        "regions": ["CA", "US"],
        "auth": "Plaid Link",
        "read_only": True,
    },
)


class FinanceConnectorError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: str, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def public_dict(row: FinanceConnection) -> dict:
    mapping = _json(row.account_map_json, {})
    return {
        "id": row.id,
        "provider": row.provider,
        "label": row.label,
        "environment": row.environment,
        "status": row.status,
        "item_id": row.item_id,
        "account_count": len(mapping),
        "consent_expires_at": row.consent_expires_at.isoformat() if row.consent_expires_at else None,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "last_error": row.last_error,
        "can_reconnect": row.provider == "plaid",
        "read_only": True,
    }


def list_connections(db) -> list[dict]:
    return [public_dict(row) for row in db.query(FinanceConnection).order_by(FinanceConnection.created_at).all()]


def _decoded_claim_url(setup_token: str, *, url_validator=net_guard.is_public_url) -> str:
    raw = str(setup_token or "").strip()
    if not raw or len(raw) > 8192:
        raise FinanceConnectorError("SimpleFIN setup token is invalid")
    try:
        padded = raw + "=" * (-len(raw) % 4)
        value = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (UnicodeError, ValueError) as exc:
        raise FinanceConnectorError("SimpleFIN setup token is invalid") from exc
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise FinanceConnectorError("SimpleFIN claim URL must be a credential-free HTTPS URL")
    if not url_validator(value):
        raise FinanceConnectorError("SimpleFIN claim URL must resolve to a public HTTPS host")
    return value


def _validated_access_url(value: str, *, url_validator=net_guard.is_public_url) -> str:
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise FinanceConnectorError("SimpleFIN returned an invalid access URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is None
        or parsed.password is None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise FinanceConnectorError("SimpleFIN returned an invalid access URL")
    if not url_validator(raw):
        raise FinanceConnectorError("SimpleFIN access URL must resolve to a public HTTPS host")
    return raw


def connect_simplefin(db, setup_token: str, *, client=httpx, url_validator=net_guard.is_public_url) -> dict:
    claim_url = _decoded_claim_url(setup_token, url_validator=url_validator)
    try:
        response = client.post(claim_url, headers={"Content-Length": "0"}, timeout=30, follow_redirects=False)
        response.raise_for_status()
    except Exception as exc:
        raise FinanceConnectorError("SimpleFIN setup token exchange failed") from exc
    access_url = _validated_access_url(response.text, url_validator=url_validator)
    row = FinanceConnection(
        provider="simplefin",
        label="SimpleFIN",
        environment="production",
        status="connected",
        access_token=access_url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return public_dict(row)


def configure_plaid(db, *, client_id: str, secret: str, environment: str) -> dict:
    env = str(environment or "").strip().lower()
    if env not in PLAID_BASES:
        raise FinanceConnectorError("Plaid environment must be sandbox or production")
    if not str(client_id or "").strip() or not str(secret or "").strip():
        raise FinanceConnectorError("Plaid client ID and secret are required")
    row = FinanceConnection(
        provider="plaid",
        label="Plaid",
        environment=env,
        status="link_required",
        client_id=str(client_id).strip(),
        client_secret=str(secret).strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return public_dict(row)


def _plaid_post(row: FinanceConnection, path: str, payload: dict, *, client=httpx) -> dict:
    base = PLAID_BASES.get(row.environment)
    if not base or not row.client_id or not row.client_secret:
        raise FinanceConnectorError("Plaid connection is incomplete")
    body = {"client_id": row.client_id, "secret": row.client_secret, **payload}
    try:
        response = client.post(f"{base}{path}", json=body, timeout=45)
        data = response.json()
    except Exception as exc:
        raise FinanceConnectorError("Plaid request failed") from exc
    if response.status_code >= 400 or not isinstance(data, dict):
        message = str((data or {}).get("error_message") or "Plaid request failed")
        raise FinanceConnectorError(message[:500])
    return data


def plaid_link_token(db, connection_id: str, *, redirect_uri: str = "", client=httpx) -> dict:
    row = db.get(FinanceConnection, connection_id)
    if not row or row.provider != "plaid":
        raise FinanceConnectorError("Plaid connection not found")
    request = {
        "user": {"client_user_id": f"alles-owner-{row.id}"},
        "client_name": "Alles",
        "products": ["transactions"],
        "country_codes": ["CA", "US"],
        "language": "en",
        "transactions": {"days_requested": 90},
    }
    if redirect_uri:
        request["redirect_uri"] = redirect_uri
    if row.access_token:
        request["access_token"] = row.access_token
        request.pop("products", None)
        request.pop("transactions", None)
    data = _plaid_post(row, "/link/token/create", request, client=client)
    token = str(data.get("link_token") or "")
    if not token:
        raise FinanceConnectorError("Plaid did not return a Link token")
    return {"link_token": token, "expiration": data.get("expiration"), "environment": row.environment}


def exchange_plaid_public_token(db, connection_id: str, public_token: str, *, client=httpx) -> dict:
    row = db.get(FinanceConnection, connection_id)
    if not row or row.provider != "plaid":
        raise FinanceConnectorError("Plaid connection not found")
    token = str(public_token or "").strip()
    if not token:
        raise FinanceConnectorError("Plaid public token is required")
    data = _plaid_post(row, "/item/public_token/exchange", {"public_token": token}, client=client)
    access_token = str(data.get("access_token") or "")
    item_id = str(data.get("item_id") or "")
    if not access_token or not item_id:
        raise FinanceConnectorError("Plaid token exchange was incomplete")
    row.access_token = access_token
    row.item_id = item_id
    row.status = "connected"
    row.last_error = ""
    db.commit()
    db.refresh(row)
    return public_dict(row)


def _simplefin_snapshot(row: FinanceConnection, *, client=httpx) -> dict:
    parsed = urlsplit(row.access_token or "")
    if not parsed.username or parsed.password is None:
        raise FinanceConnectorError("SimpleFIN connection is incomplete")
    clean = urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    try:
        response = client.get(
            f"{clean}/accounts",
            auth=(unquote(parsed.username), unquote(parsed.password)),
            params={"version": "2"},
            timeout=60,
            follow_redirects=False,
        )
        data = response.json()
    except Exception as exc:
        raise FinanceConnectorError("SimpleFIN account sync failed") from exc
    if response.status_code >= 400 or not isinstance(data, dict):
        raise FinanceConnectorError("SimpleFIN account sync failed")
    errors = data.get("errors") or data.get("errlist") or []
    if errors:
        raise FinanceConnectorError(f"SimpleFIN reported: {str(errors[0])[:400]}")
    accounts = []
    for raw in data.get("accounts") or []:
        if not isinstance(raw, dict):
            continue
        transactions = []
        for tx in raw.get("transactions") or []:
            if not isinstance(tx, dict) or not str(tx.get("id") or ""):
                continue
            try:
                posted = int(tx.get("posted"))
                if posted <= 0:
                    raise ValueError
                posted_date = datetime.fromtimestamp(posted, UTC).date().isoformat()
            except (OSError, OverflowError, TypeError, ValueError) as exc:
                raise FinanceConnectorError("SimpleFIN returned an invalid transaction date") from exc
            transactions.append(
                {
                    "external_id": str(tx.get("id") or ""),
                    "date": posted_date,
                    "amount": float(tx.get("amount") or 0),
                    "payee": str(tx.get("payee") or tx.get("description") or ""),
                    "description": str(tx.get("description") or ""),
                }
            )
        accounts.append(
            {
                "external_id": str(raw.get("id") or raw.get("name") or ""),
                "name": str(raw.get("name") or "SimpleFIN account"),
                "kind": "checking",
                "currency": str(raw.get("currency") or "USD"),
                "transactions": transactions,
            }
        )
    return {"accounts": accounts, "cursor": row.cursor, "removed": []}


def _plaid_snapshot(row: FinanceConnection, *, client=httpx) -> dict:
    if not row.access_token:
        raise FinanceConnectorError("complete Plaid Link before syncing")
    original_cursor = row.cursor or ""
    cursor = original_cursor
    accounts_by_id = {}
    added, modified, removed = [], [], []
    pages = 0
    while True:
        pages += 1
        if pages > 100:
            raise FinanceConnectorError("Plaid pagination limit exceeded")
        payload = {"access_token": row.access_token}
        if cursor:
            payload["cursor"] = cursor
        data = _plaid_post(row, "/transactions/sync", payload, client=client)
        for account in data.get("accounts") or []:
            if isinstance(account, dict) and account.get("account_id"):
                accounts_by_id[str(account["account_id"])] = account
        added.extend(item for item in data.get("added") or [] if isinstance(item, dict))
        modified.extend(item for item in data.get("modified") or [] if isinstance(item, dict))
        removed.extend(str(item.get("transaction_id") or "") for item in data.get("removed") or [] if isinstance(item, dict))
        cursor = str(data.get("next_cursor") or cursor)
        if not data.get("has_more"):
            break
    grouped = {}
    for raw in [*added, *modified]:
        account_id = str(raw.get("account_id") or "")
        external_id = str(raw.get("transaction_id") or "")
        if not account_id or not external_id:
            continue
        grouped.setdefault(account_id, {})[external_id] = {
            "external_id": external_id,
            "date": str(raw.get("date") or raw.get("authorized_date") or ""),
            "amount": -float(raw.get("amount") or 0),
            "payee": str(raw.get("merchant_name") or raw.get("name") or ""),
            "description": str(raw.get("name") or ""),
        }
    accounts = []
    for external_id in sorted(set(accounts_by_id) | set(grouped)):
        txns = grouped.get(external_id, {})
        raw = accounts_by_id.get(external_id, {})
        accounts.append(
            {
                "external_id": external_id,
                "name": str(raw.get("name") or raw.get("official_name") or "Plaid account"),
                "kind": "credit" if raw.get("type") == "credit" else "checking",
                "currency": str((raw.get("balances") or {}).get("iso_currency_code") or "CAD"),
                "transactions": list(txns.values()),
            }
        )
    return {"accounts": accounts, "cursor": cursor, "removed": removed}


def _stable_import_id(row: FinanceConnection, external_id: str) -> str:
    digest = hashlib.sha256(f"{row.provider}:{row.id}:{external_id}".encode()).hexdigest()
    return f"aggregator:{row.provider}:{digest}"


def _account_for_snapshot(db, connection: FinanceConnection, account: dict, mapping: dict) -> str:
    external_id = account["external_id"]
    if mapping.get(external_id):
        return str(mapping[external_id])
    request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"alles:{connection.id}:account:{external_id}"))
    values = {"name": account["name"], "kind": account["kind"], "currency": account["currency"], "opening": 0}
    if actual_finance.is_canonical(db):
        created = actual_finance.create_account(db, values, request_id=request_id)
        account_id = str(created["id"])
    else:
        row = Account(name=values["name"], kind=values["kind"], currency=values["currency"], opening=0)
        finance_currency.prepare_account(row)
        db.add(row)
        db.flush()
        account_id = row.id
    mapping[external_id] = account_id
    return account_id


def _upsert_transaction(db, connection: FinanceConnection, account_id: str, raw: dict) -> bool:
    amount = float(raw.get("amount") or 0)
    if not math.isfinite(amount):
        raise FinanceConnectorError("provider returned a non-finite transaction amount")
    try:
        transaction_date = date.fromisoformat(str(raw.get("date") or "")).isoformat()
    except ValueError as exc:
        raise FinanceConnectorError("provider returned an invalid transaction date") from exc
    identity = _stable_import_id(connection, raw["external_id"])
    values = {
        "account_id": account_id,
        "date": transaction_date,
        "amount": amount,
        "category": "",
        "payee": raw["payee"],
        "notes": raw["description"],
        "tags": "",
        "cleared": True,
    }
    if actual_finance.is_canonical(db):
        actual_finance.create_transaction(
            db,
            values,
            source_id=f"finance-connector:{connection.id}:{raw['external_id']}",
            import_identity=identity,
            evidence={"source": connection.provider, "connection_id": connection.id},
        )
        return True
    existing = db.query(Transaction).filter(Transaction.import_identity == identity).first()
    if existing:
        for key in ("account_id", "date", "amount", "payee", "notes"):
            setattr(existing, key, values[key])
        existing.cleared = True
        return False
    transaction = Transaction(
        **values,
        import_identity=identity,
        import_source=connection.provider,
    )
    db.add(transaction)
    finance_currency.prepare_transaction(db, transaction, source=connection.provider)
    return True


def _remove_transaction(db, connection: FinanceConnection, external_id: str) -> bool:
    clean_id = str(external_id or "").strip()
    if not clean_id:
        return False
    if actual_finance.is_canonical(db):
        source_id = f"finance-connector:{connection.id}:{clean_id}"
        if actual_finance._find_deletion_link(db, "transaction", source_id) is None:
            return False
        actual_finance.delete_transaction(db, source_id)
        return True
    identity = _stable_import_id(connection, clean_id)
    existing = db.query(Transaction).filter(Transaction.import_identity == identity).first()
    if not existing:
        return False
    db.delete(existing)
    return True


def sync(db, connection_id: str, *, client=httpx) -> dict:
    row = db.get(FinanceConnection, connection_id)
    if not row:
        raise FinanceConnectorError("Finance connection not found")
    try:
        snapshot = _simplefin_snapshot(row, client=client) if row.provider == "simplefin" else _plaid_snapshot(row, client=client)
        mapping = _json(row.account_map_json, {})
        created = updated = removed = 0
        for external_id in snapshot.get("removed") or []:
            if _remove_transaction(db, row, external_id):
                removed += 1
        for account in snapshot["accounts"]:
            account_id = _account_for_snapshot(db, row, account, mapping)
            for transaction in account["transactions"]:
                if _upsert_transaction(db, row, account_id, transaction):
                    created += 1
                else:
                    updated += 1
        row.account_map_json = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
        row.cursor = snapshot.get("cursor") or row.cursor
        row.status = "connected"
        row.last_synced_at = _now()
        row.last_error = ""
        db.commit()
        return {**public_dict(row), "created": created, "updated": updated, "removed": removed}
    except Exception as exc:
        db.rollback()
        fresh = db.get(FinanceConnection, connection_id)
        if fresh:
            fresh.status = "error"
            fresh.last_error = str(exc)[:1000]
            db.commit()
        if isinstance(exc, FinanceConnectorError):
            raise
        raise FinanceConnectorError(str(exc)) from exc


def disconnect(db, connection_id: str, *, client=httpx) -> dict:
    row = db.get(FinanceConnection, connection_id)
    if not row:
        raise FinanceConnectorError("Finance connection not found")
    if row.provider == "plaid" and row.access_token:
        _plaid_post(row, "/item/remove", {"access_token": row.access_token}, client=client)
    db.delete(row)
    db.commit()
    return {"ok": True, "connection_id": connection_id}
