import time, secrets
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, VaultEntry
from core.settings import load_settings, save_settings
from services.crypto import make_verifier, verify_master, encrypt, decrypt

router = APIRouter(prefix="/api")

# token → (expiry, plaintext_password) — never written to disk
_unlock_tokens: dict[str, tuple[float, str]] = {}
_TTL = 600   # 10 min


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
    _unlock_tokens[x_vault_token] = (now + _TTL, v[1])   # slide the window
    return v[1]


class UnlockBody(BaseModel):
    password: str


@router.get("/vault/generate")
def vault_generate(length: int = 20, upper: bool = True, lower: bool = True,
                   digits: bool = True, symbols: bool = True, avoid_ambiguous: bool = True):
    from services.pwtools import generate_password, estimate_strength
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
    return [{"id": e.id, "name": e.name, "username": e.username or "", "category": e.category,
             "created_at": e.created_at.isoformat()} for e in entries]


@router.get("/vault/categories")
def vault_categories(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    used = [c for (c,) in db.query(VaultEntry.category).distinct().all() if c]
    base = ["password", "api key", "card", "note", "general"]
    return {"categories": sorted(set(base) | set(used))}


class CreateEntry(BaseModel):
    name: str
    value: str
    category: str = "general"
    username: str = ""


@router.post("/vault")
def create_entry(body: CreateEntry, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    enc = encrypt(pw, body.value)
    e = VaultEntry(name=body.name, username=body.username, value_encrypted=enc, category=body.category)
    db.add(e); db.commit(); db.refresh(e)
    return {"id": e.id, "name": e.name, "category": e.category}


class PatchEntry(BaseModel):
    name: str | None = None
    value: str | None = None
    category: str | None = None
    username: str | None = None


@router.patch("/vault/{entry_id}")
def patch_entry(entry_id: str, body: PatchEntry, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    if body.name is not None:     e.name = body.name
    if body.category is not None: e.category = body.category
    if body.username is not None: e.username = body.username
    if body.value is not None:    e.value_encrypted = encrypt(pw, body.value)
    db.commit()
    return {"ok": True}


@router.get("/vault/{entry_id}/reveal")
def reveal_entry(entry_id: str, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    try:
        value = decrypt(pw, e.value_encrypted)
    except Exception:
        raise HTTPException(500, "decryption failed")
    return {"value": value}


@router.delete("/vault/{entry_id}")
def delete_entry(entry_id: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    db.delete(e); db.commit()
    return {"ok": True}
