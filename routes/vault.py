import time, secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, VaultEntry
from core.settings import load_settings, save_settings
from services.crypto import make_verifier, verify_master, encrypt, decrypt

router = APIRouter(prefix="/api")

# token → (expiry, plaintext_password) — never written to disk
_unlock_tokens: dict[str, tuple[float, str]] = {}
_TTL = 600   # 10 min


def _get_master_pw() -> str:
    now = time.time()
    for tok, (exp, pw) in list(_unlock_tokens.items()):
        if now <= exp:
            _unlock_tokens[tok] = (now + _TTL, pw)  # slide window
            return pw
        else:
            del _unlock_tokens[tok]
    raise HTTPException(403, "vault locked")


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
def list_vault(db: DbSession = Depends(get_db)):
    _get_master_pw()   # entry names/usernames are metadata, but still vault-locked
    entries = db.query(VaultEntry).order_by(VaultEntry.created_at.desc()).all()
    return [{"id": e.id, "name": e.name, "username": e.username or "", "category": e.category,
             "created_at": e.created_at.isoformat()} for e in entries]


@router.get("/vault/categories")
def vault_categories(db: DbSession = Depends(get_db)):
    _get_master_pw()
    used = [c for (c,) in db.query(VaultEntry.category).distinct().all() if c]
    base = ["password", "api key", "card", "note", "general"]
    return {"categories": sorted(set(base) | set(used))}


class CreateEntry(BaseModel):
    name: str
    value: str
    category: str = "general"
    username: str = ""


@router.post("/vault")
def create_entry(body: CreateEntry, db: DbSession = Depends(get_db)):
    pw = _get_master_pw()
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
def patch_entry(entry_id: str, body: PatchEntry, db: DbSession = Depends(get_db)):
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    pw = _get_master_pw()
    if body.name is not None:     e.name = body.name
    if body.category is not None: e.category = body.category
    if body.username is not None: e.username = body.username
    if body.value is not None:    e.value_encrypted = encrypt(pw, body.value)
    db.commit()
    return {"ok": True}


@router.get("/vault/{entry_id}/reveal")
def reveal_entry(entry_id: str, db: DbSession = Depends(get_db)):
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    pw = _get_master_pw()
    try:
        value = decrypt(pw, e.value_encrypted)
    except Exception:
        raise HTTPException(500, "decryption failed")
    return {"value": value}


@router.delete("/vault/{entry_id}")
def delete_entry(entry_id: str, db: DbSession = Depends(get_db)):
    _get_master_pw()
    e = db.get(VaultEntry, entry_id)
    if not e: raise HTTPException(404)
    db.delete(e); db.commit()
    return {"ok": True}
