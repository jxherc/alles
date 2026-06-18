import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import VaultEntry, get_db
from core.settings import load_settings, save_settings
from services.crypto import decrypt, encrypt, make_verifier, verify_master

router = APIRouter(prefix="/api")

# token → (expiry, plaintext_password) — never written to disk
_unlock_tokens: dict[str, tuple[float, str]] = {}
_TTL = 600  # 10 min


def _master_pw(x_vault_token: str | None = Header(None)) -> str:
    """resolve the caller's own unlock token to its master password.

    binds each vault request to the token returned by /vault/unlock, so an
    unlock by one session no longer hands the vault to every other request
    that happens to land in the 10-min window.
    """
    now = time.time()
    for tok in [t for t, (exp, _) in list(_unlock_tokens.items()) if now > exp]:
        del _unlock_tokens[tok]
    v = _unlock_tokens.get(x_vault_token or "")
    if not v:
        raise HTTPException(403, "vault locked")
    _unlock_tokens[x_vault_token] = (now + _TTL, v[1])  # slide the window
    return v[1]


class UnlockBody(BaseModel):
    password: str


@router.get("/vault/generate")
def vault_generate(
    length: int = 20,
    upper: bool = True,
    lower: bool = True,
    digits: bool = True,
    symbols: bool = True,
    avoid_ambiguous: bool = True,
):
    from services.pwtools import estimate_strength, generate_password

    pw = generate_password(length, upper, lower, digits, symbols, avoid_ambiguous)
    return {"password": pw, "strength": estimate_strength(pw)}


class StrengthBody(BaseModel):
    password: str


@router.post("/vault/strength")
def vault_strength(body: StrengthBody):
    from services.pwtools import estimate_strength

    return estimate_strength(body.password)


@router.post("/vault/unlock")
def vault_unlock(body: UnlockBody):
    s = load_settings()
    verifier = s.get("vault_verifier", "")
    if not verifier:
        # first time — store only the verifier (no plaintext anywhere on disk)
        save_settings({"vault_verifier": make_verifier(body.password)})
        token = secrets.token_urlsafe(16)
        _unlock_tokens[token] = (time.time() + _TTL, body.password)
        return {"token": token}

    if not verify_master(body.password, verifier):
        raise HTTPException(401, "wrong master password")

    token = secrets.token_urlsafe(16)
    _unlock_tokens[token] = (time.time() + _TTL, body.password)
    return {"token": token}


@router.post("/vault/lock")
def vault_lock():
    _unlock_tokens.clear()
    return {"ok": True}


@router.get("/vault")
def list_vault(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    # entry names/usernames are metadata, but still vault-locked
    entries = db.query(VaultEntry).order_by(VaultEntry.created_at.desc()).all()
    return [
        {
            "id": e.id,
            "name": e.name,
            "username": e.username or "",
            "category": e.category,
            "type": e.type or "password",
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]


_BASE_CATS = ["password", "api key", "card", "note", "general"]
_FIELD_KEYS = ["username", "password", "url", "notes", "card"]  # canonical, ordered


def _default_schema(category: str) -> list[str]:
    """which fields a category has by default, when nothing's been saved for it."""
    c = (category or "").lower()
    if "card" in c:
        return ["card"]
    if "note" in c:
        return ["notes"]
    if re.search(r"password|login|account", c):
        return ["username", "password", "url", "notes"]
    if "api" in c or "key" in c:
        return ["password", "url", "notes"]
    return ["password", "notes"]


def _all_schemas(db) -> tuple[list[str], dict]:
    used = [c for (c,) in db.query(VaultEntry.category).distinct().all() if c]
    saved = load_settings().get("vault_category_schemas") or {}
    cats = sorted(set(_BASE_CATS) | set(used) | set(saved.keys()))
    schemas = {}
    for c in cats:
        fields = saved.get(c)
        schemas[c] = {"fields": fields if isinstance(fields, list) else _default_schema(c)}
    return cats, schemas


@router.get("/vault/categories")
def vault_categories(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    cats, schemas = _all_schemas(db)
    return {"categories": cats, "schemas": schemas}


class CategorySchema(BaseModel):
    name: str
    fields: list[str] = []


@router.put("/vault/category-schema")
def put_category_schema(body: CategorySchema, _pw: str = Depends(_master_pw)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "category name required")
    fields = [f for f in body.fields if f in _FIELD_KEYS]  # drop anything not a known field
    m = dict(load_settings().get("vault_category_schemas") or {})
    m[name] = fields
    save_settings({"vault_category_schemas": m})
    return {"name": name, "fields": fields}


class CreateEntry(BaseModel):
    name: str
    value: str = ""  # legacy single-secret create
    fields: dict | None = None  # typed structured fields (password/card/note)
    type: str = "password"
    category: str = "general"
    username: str = ""


def _fields_of(body) -> dict:
    """normalize a create/patch body into a fields dict to encrypt."""
    if body.fields is not None:
        return body.fields
    return {"password": body.value} if body.value else {}


@router.post("/vault")
def create_entry(body: CreateEntry, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    enc = encrypt(pw, json.dumps(_fields_of(body)))
    e = VaultEntry(
        name=body.name,
        username=body.username,
        value_encrypted=enc,
        category=body.category,
        type=body.type or "password",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id, "name": e.name, "category": e.category, "type": e.type}


class PatchEntry(BaseModel):
    name: str | None = None
    value: str | None = None
    fields: dict | None = None
    type: str | None = None
    category: str | None = None
    username: str | None = None


@router.patch("/vault/{entry_id}")
def patch_entry(
    entry_id: str, body: PatchEntry, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)
):
    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    if body.name is not None:
        e.name = body.name
    if body.category is not None:
        e.category = body.category
    if body.username is not None:
        e.username = body.username
    if body.type is not None:
        e.type = body.type
    if body.fields is not None:
        e.value_encrypted = encrypt(pw, json.dumps(body.fields))
    elif body.value is not None:
        e.value_encrypted = encrypt(pw, json.dumps({"password": body.value}))
    db.commit()
    return {"ok": True}


@router.get("/vault/{entry_id}/reveal")
def reveal_entry(entry_id: str, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    try:
        raw = decrypt(pw, e.value_encrypted)
    except Exception:
        raise HTTPException(500, "decryption failed")
    try:
        fields = json.loads(raw)
        if not isinstance(fields, dict):
            raise ValueError
    except (ValueError, TypeError):
        fields = {"password": raw}  # legacy: a bare encrypted string
    out = {"type": e.type or "password", "fields": fields, "value": fields.get("password", "")}
    if (e.type or "") == "card" and fields.get("number"):
        from services.pwtools import card_brand, card_last4, luhn_valid, mask_card

        num = fields["number"]
        out["card"] = {
            "brand": card_brand(num),
            "last4": card_last4(num),
            "masked": mask_card(num),
            "valid": luhn_valid(num),
        }
    return out


@router.delete("/vault/{entry_id}")
def delete_entry(entry_id: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    db.delete(e)
    db.commit()
    return {"ok": True}
