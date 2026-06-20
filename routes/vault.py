import json
import re
import secrets
import time

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from core.database import (
    Vault,
    VaultAttachment,
    VaultEntry,
    VaultShare,
    WebAuthnCredential,
    get_db,
)
from core.settings import load_settings, save_settings
from services.crypto import decrypt, encrypt, make_verifier, verify_master

router = APIRouter(prefix="/api")

# token → (expiry, plaintext_password, vault_id) — never written to disk
_unlock_tokens: dict[str, tuple[float, str, str]] = {}
_TTL = 600  # 10 min
DEFAULT_VAULT = "default"


def _mint(pw: str, vault_id: str) -> str:
    tok = secrets.token_urlsafe(16)
    _unlock_tokens[tok] = (time.time() + _TTL, pw, vault_id)
    return tok


def _ctx(x_vault_token: str | None = Header(None)) -> tuple[str, str]:
    """resolve the caller's own unlock token to (master_password, vault_id).

    binds each vault request to the token returned by /vault/unlock, so an
    unlock by one session no longer hands the vault to every other request
    that happens to land in the 10-min window.
    """
    now = time.time()
    for tok in [t for t, (exp, _, _) in list(_unlock_tokens.items()) if now > exp]:
        del _unlock_tokens[tok]
    v = _unlock_tokens.get(x_vault_token or "")
    if not v:
        raise HTTPException(403, "vault locked")
    _unlock_tokens[x_vault_token] = (now + _TTL, v[1], v[2])  # slide the window
    return v[1], v[2]


def _master_pw(x_vault_token: str | None = Header(None)) -> str:
    return _ctx(x_vault_token)[0]


def _travel_on() -> bool:
    return bool(load_settings().get("vault_travel_mode"))


def _require_2fa(vid: str) -> bool:
    return bool((load_settings().get("vault_require_2fa") or {}).get(vid))


def _has_2fa_cred(db, vid: str) -> bool:
    return (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vid, WebAuthnCredential.role == "2fa")
        .first()
        is not None
    )


def _totp_map() -> dict:
    return dict(load_settings().get("vault_2fa_totp") or {})


def _has_totp_2fa(vid: str) -> bool:
    return bool(_totp_map().get(vid))


def _ensure_default(db) -> Vault:
    """lazily create the default vault, migrating the legacy single-vault verifier in."""
    v = db.get(Vault, DEFAULT_VAULT)
    if not v:
        v = Vault(
            id=DEFAULT_VAULT,
            name="Personal",
            verifier=load_settings().get("vault_verifier", ""),
            travel_safe=True,  # the default vault is always reachable, even while travelling
        )
        db.add(v)
        db.commit()
        db.refresh(v)
    return v


class UnlockBody(BaseModel):
    password: str
    vault_id: str | None = None


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
def vault_unlock(body: UnlockBody, db: DbSession = Depends(get_db)):
    _ensure_default(db)
    vid = body.vault_id or DEFAULT_VAULT
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404, "no such vault")
    if _travel_on() and not v.travel_safe:
        raise HTTPException(403, "vault unavailable in travel mode")
    if not v.verifier:
        # first unlock for this vault — store only the verifier (no plaintext on disk)
        v.verifier = make_verifier(body.password)
        if vid == DEFAULT_VAULT:
            save_settings({"vault_verifier": v.verifier})  # keep legacy mirror in sync
        db.commit()
        return {"token": _mint(body.password, vid), "vault_id": vid}
    if not verify_master(body.password, v.verifier):
        raise HTTPException(401, "wrong master password")
    # 9d / 8c — if this vault demands a second factor, withhold the token and hand back the available
    # methods: a passkey/security-key challenge and/or an authenticator-app (TOTP) prompt.
    has_key = _has_2fa_cred(db, vid)
    has_totp = _has_totp_2fa(vid)
    if _require_2fa(vid) and (has_key or has_totp):
        resp = {"requires_2fa": True, "methods": []}
        if has_key:
            from services.webauthn import new_challenge

            ch = new_challenge()
            _wa_challenges[vid] = (time.time() + _WA_TTL, ch)
            creds = (
                db.query(WebAuthnCredential)
                .filter(WebAuthnCredential.vault_id == vid, WebAuthnCredential.role == "2fa")
                .all()
            )
            resp["methods"].append("passkey")
            resp["challenge"] = ch
            resp["credentials"] = [c.credential_id for c in creds]
        if has_totp:
            resp["methods"].append("totp")
        return resp
    return {"token": _mint(body.password, vid), "vault_id": vid}


@router.post("/vault/lock")
def vault_lock():
    _unlock_tokens.clear()
    return {"ok": True}


# ── multiple vaults + Travel Mode (9c) ────────────────────────────────────────
@router.get("/vault/travel-mode")
def get_travel_mode():
    return {"on": _travel_on()}


class TravelBody(BaseModel):
    on: bool


@router.put("/vault/travel-mode")
def set_travel_mode(body: TravelBody, _pw: str = Depends(_master_pw)):
    save_settings({"vault_travel_mode": bool(body.on)})
    return {"on": bool(body.on)}


@router.get("/vault/vaults")
def list_vaults(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    _ensure_default(db)
    travel = _travel_on()
    counts = dict(
        db.query(VaultEntry.vault_id, func.count(VaultEntry.id)).group_by(VaultEntry.vault_id).all()
    )
    out = []
    for v in db.query(Vault).order_by(Vault.created_at.asc()).all():
        if travel and not v.travel_safe:
            continue
        out.append(
            {
                "id": v.id,
                "name": v.name,
                "travel_safe": bool(v.travel_safe),
                "entries": counts.get(v.id, 0),
                "biometric": bool(v.biometric_blob),
                "main": v.id == DEFAULT_VAULT,  # 8b — the main vault opens with your master password
            }
        )
    return out


class VaultBody(BaseModel):
    name: str
    password: str


@router.post("/vault/vaults")
def create_vault(body: VaultBody, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "vault name required")
    if not body.password:
        raise HTTPException(400, "password required")
    v = Vault(name=name, verifier=make_verifier(body.password), travel_safe=False)
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id, "name": v.name}


class VaultPatch(BaseModel):
    name: str | None = None
    travel_safe: bool | None = None


@router.patch("/vault/vaults/{vid}")
def patch_vault(
    vid: str, body: VaultPatch, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)
):
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)
    if body.name is not None and body.name.strip():
        v.name = body.name.strip()
    if body.travel_safe is not None:
        v.travel_safe = bool(body.travel_safe)
    db.commit()
    return {"ok": True}


class ChangePw(BaseModel):
    new_password: str


@router.post("/vault/vaults/password")
def change_vault_password(body: ChangePw, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    """8b — re-key the currently-unlocked vault to a new password. The main (default) vault's password
    IS the master password, so this doubles as 'change master password'. Re-encrypts every entry +
    attachment under the new key; computes all ciphertext first, then writes, so a mid-way failure
    can't leave a half-re-keyed vault."""
    from services.crypto import decrypt_bytes, encrypt_bytes

    old_pw, vid = ctx
    new = body.new_password or ""
    if not new:
        raise HTTPException(400, "new password required")
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)

    # compute everything up front (decrypt-old → encrypt-new) so a failure aborts before any write
    entries = db.query(VaultEntry).filter(VaultEntry.vault_id == vid).all()
    eids = [e.id for e in entries]
    new_entry_blobs = {}
    try:
        for e in entries:
            new_entry_blobs[e.id] = encrypt(new, decrypt(old_pw, e.value_encrypted))
        atts = (
            db.query(VaultAttachment).filter(VaultAttachment.entry_id.in_(eids)).all()
            if eids
            else []
        )
        new_att_blobs = {}
        for a in atts:
            p = _attach_dir() / f"{a.id}.enc"
            if p.exists():
                new_att_blobs[a.id] = encrypt_bytes(new, decrypt_bytes(old_pw, p.read_bytes()))
    except Exception:
        raise HTTPException(500, "re-key failed — nothing changed")

    # all crypto succeeded → commit the new ciphertext + verifier
    for e in entries:
        e.value_encrypted = new_entry_blobs[e.id]
    for aid, blob in new_att_blobs.items():
        (_attach_dir() / f"{aid}.enc").write_bytes(blob)
    v.verifier = make_verifier(new)
    if vid == DEFAULT_VAULT:
        save_settings({"vault_verifier": v.verifier})  # keep the legacy master mirror in sync
    db.commit()
    # the caller's token still holds the old pw — hand back a fresh one bound to the new password
    return {"ok": True, "token": _mint(new, vid), "vault_id": vid}


@router.delete("/vault/vaults/{vid}")
def delete_vault(vid: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    if vid == DEFAULT_VAULT:
        raise HTTPException(400, "cannot delete the default vault")
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)
    db.query(VaultEntry).filter(VaultEntry.vault_id == vid).delete()
    db.delete(v)
    db.commit()
    return {"ok": True}


@router.get("/vault")
def list_vault(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    # entry names/usernames are metadata, but still vault-locked + scoped to this vault
    vid = ctx[1]
    entries = (
        db.query(VaultEntry)
        .filter(VaultEntry.vault_id == vid)
        .order_by(VaultEntry.created_at.desc())
        .all()
    )
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
# canonical, ordered. "card" stays in for back-compat with schemas saved before
# cards got broken out into their own fields.
_FIELD_KEYS = [
    "username",
    "password",
    "url",
    "notes",
    "cardholder",
    "number",
    "expiry",
    "cvv",
    "address",
    "card",
]
_CARD_FIELDS = ["cardholder", "number", "expiry", "cvv", "address", "notes"]


def _default_schema(category: str) -> list[str]:
    """which fields a category has by default, when nothing's been saved for it."""
    c = (category or "").lower()
    if "card" in c:
        return list(_CARD_FIELDS)
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


# ── customizable entry types (8e) — user-defined types with named fields + widths ──
_WIDTHS = {"full", "half", "third"}
_KINDS = {"text", "secret", "password", "textarea"}


def _norm_field(f: dict) -> dict | None:
    key = re.sub(r"[^a-z0-9_]", "", str(f.get("key", "")).strip().lower())
    label = str(f.get("label", "")).strip()
    if not key or not label:
        return None
    width = f.get("width", "full")
    kind = f.get("kind", "text")
    return {
        "key": key,
        "label": label,
        "width": width if width in _WIDTHS else "full",
        "kind": kind if kind in _KINDS else "text",
        "placeholder": str(f.get("placeholder", "")).strip(),
    }


class CustomType(BaseModel):
    label: str
    fields: list[dict] = []


@router.get("/vault/custom-types")
def get_custom_types(_pw: str = Depends(_master_pw)):
    return {"types": dict(load_settings().get("vault_custom_types") or {})}


@router.put("/vault/custom-types/{key}")
def put_custom_type(key: str, body: CustomType, _pw: str = Depends(_master_pw)):
    key = re.sub(r"[^a-z0-9_]", "", (key or "").strip().lower())
    label = (body.label or "").strip()
    if not key or not label:
        raise HTTPException(400, "type needs a key and a label")
    fields = [nf for f in body.fields if (nf := _norm_field(f))]
    if not fields:
        raise HTTPException(400, "a type needs at least one field")
    m = dict(load_settings().get("vault_custom_types") or {})
    m[key] = {"label": label, "fields": fields}
    save_settings({"vault_custom_types": m})
    return {"key": key, **m[key]}


@router.delete("/vault/custom-types/{key}")
def delete_custom_type(key: str, _pw: str = Depends(_master_pw)):
    m = dict(load_settings().get("vault_custom_types") or {})
    m.pop(key, None)
    save_settings({"vault_custom_types": m})
    return {"ok": True}


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
def create_entry(body: CreateEntry, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    enc = encrypt(pw, json.dumps(_fields_of(body)))
    e = VaultEntry(
        vault_id=vid,
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


# ── TOTP + Watchtower (9a) ────────────────────────────────────────────────────
def _entry_fields(e, pw):
    try:
        raw = decrypt(pw, e.value_encrypted)
        f = json.loads(raw)
        return f if isinstance(f, dict) else {"password": raw}
    except Exception:
        return {}


@router.get("/vault/{entry_id}/totp")
def entry_totp(entry_id: str, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    secret = (_entry_fields(e, pw).get("totp") or "").strip()
    if not secret:
        raise HTTPException(404, "no totp secret on this entry")
    from services.pwtools import totp_now, totp_remaining

    try:
        return {"code": totp_now(secret), "seconds": totp_remaining()}
    except Exception:
        raise HTTPException(400, "bad totp secret")


def _hibp_fetch(prefix: str) -> str:
    """fetch the HIBP k-anonymity range for a sha1 prefix (only 5 hex chars leave the box)."""
    import httpx

    r = httpx.get(f"https://api.pwnedpasswords.com/range/{prefix}", timeout=15)
    r.raise_for_status()
    return r.text


@router.get("/vault/watchtower")
def watchtower(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    from services.pwtools import breach_count, find_reused, is_weak

    pw, vid = ctx
    items = []  # {id, name, password}
    for e in db.query(VaultEntry).filter(VaultEntry.vault_id == vid).all():
        f = _entry_fields(e, pw)
        p = (f.get("password") or "").strip()
        if p:
            items.append({"id": e.id, "name": e.name, "password": p})

    weak = [{"id": i["id"], "name": i["name"]} for i in items if is_weak(i["password"])]

    by_id = {i["id"]: i["name"] for i in items}
    reused = []
    for group in find_reused(items):
        reused.append({"ids": group, "names": [by_id[g] for g in group]})

    breached = []
    seen = {}  # cache prefix→count per distinct password to limit calls
    for i in items:
        cnt = seen.get(i["password"])
        if cnt is None:
            cnt = breach_count(i["password"], _hibp_fetch)
            seen[i["password"]] = cnt
        if cnt > 0:
            breached.append({"id": i["id"], "name": i["name"], "count": cnt})

    return {
        "weak": weak,
        "reused": reused,
        "breached": breached,
        "counts": {"weak": len(weak), "reused": len(reused), "breached": len(breached)},
    }


# ── encrypted attachments (9b) ────────────────────────────────────────────────
def _attach_dir():
    from core.settings import data_dir

    d = data_dir() / "vault_attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/vault/{entry_id}/attachments")
async def add_attachment(
    entry_id: str,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_db),
    pw: str = Depends(_master_pw),
):
    from services.crypto import encrypt_bytes

    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "attachment too large (25MB max)")
    att = VaultAttachment(entry_id=entry_id, filename=file.filename or "file", size=len(data))
    db.add(att)
    db.commit()
    db.refresh(att)
    (_attach_dir() / f"{att.id}.enc").write_bytes(encrypt_bytes(pw, data))
    return {"id": att.id, "filename": att.filename, "size": att.size}


@router.get("/vault/{entry_id}/attachments")
def list_attachments(
    entry_id: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)
):
    rows = db.query(VaultAttachment).filter(VaultAttachment.entry_id == entry_id).all()
    return [{"id": a.id, "filename": a.filename, "size": a.size} for a in rows]


@router.get("/vault/attachments/{aid}")
def download_attachment(aid: str, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    from services.crypto import decrypt_bytes

    a = db.get(VaultAttachment, aid)
    if not a:
        raise HTTPException(404)
    p = _attach_dir() / f"{aid}.enc"
    if not p.is_file():
        raise HTTPException(404)
    try:
        data = decrypt_bytes(pw, p.read_bytes())
    except Exception:
        raise HTTPException(500, "decryption failed")
    import mimetypes

    mt = mimetypes.guess_type(a.filename)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=mt,
        headers={"content-disposition": f'attachment; filename="{a.filename}"'},
    )


@router.delete("/vault/attachments/{aid}")
def delete_attachment(aid: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    a = db.get(VaultAttachment, aid)
    if not a:
        raise HTTPException(404)
    try:
        (_attach_dir() / f"{aid}.enc").unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── per-item share (9b) — random-key envelope; key travels in the URL fragment ─
@router.post("/vault/{entry_id}/share")
def share_entry(entry_id: str, db: DbSession = Depends(get_db), pw: str = Depends(_master_pw)):
    from services.crypto import envelope_encrypt

    e = db.get(VaultEntry, entry_id)
    if not e:
        raise HTTPException(404)
    fields = _entry_fields(e, pw)
    payload = json.dumps({"name": e.name, "type": e.type or "password", "fields": fields})
    key, blob = envelope_encrypt(payload)
    existing = db.query(VaultShare).filter(VaultShare.entry_id == entry_id).first()
    if existing:
        existing.blob = blob
        sh = existing
    else:
        sh = VaultShare(entry_id=entry_id, blob=blob)
        db.add(sh)
    db.commit()
    db.refresh(sh)
    return {"token": sh.token, "key": key, "url": f"/sv/{sh.token}#{key}"}


@router.delete("/vault/{entry_id}/share")
def revoke_entry_share(
    entry_id: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)
):
    db.query(VaultShare).filter(VaultShare.entry_id == entry_id).delete()
    db.commit()
    return {"ok": True}


# ── WebAuthn biometric unlock (9c) ────────────────────────────────────────────
# A registered platform authenticator gates release of the master pw, which is
# wrapped under a per-install server key. Convenience-unlock tradeoff: the wrapped
# blob lives on disk, but only a verified assertion unwraps it.
_wa_challenges: dict[str, tuple[float, str]] = {}  # vault_id -> (exp, challenge)
_WA_TTL = 300


def _server_key() -> str:
    k = load_settings().get("vault_biometric_key")
    if not k:
        k = secrets.token_urlsafe(32)
        save_settings({"vault_biometric_key": k})
    return k


class WaRegister(BaseModel):
    label: str = ""
    credential_id: str
    public_key: str


@router.post("/vault/webauthn/register")
def webauthn_register(
    body: WaRegister, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    pw, vid = ctx
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)
    cred = WebAuthnCredential(
        vault_id=vid,
        label=body.label or "device",
        credential_id=body.credential_id,
        public_key=body.public_key,
    )
    db.add(cred)
    v.biometric_blob = encrypt(_server_key(), pw)  # wrap so an assertion can release it
    db.commit()
    db.refresh(cred)
    return {"id": cred.id, "label": cred.label}


@router.get("/vault/webauthn/credentials")
def webauthn_credentials(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    rows = db.query(WebAuthnCredential).filter(WebAuthnCredential.vault_id == vid).all()
    return [{"id": c.id, "label": c.label, "credential_id": c.credential_id} for c in rows]


@router.delete("/vault/webauthn/credentials/{cid}")
def webauthn_delete(cid: str, db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    c = db.get(WebAuthnCredential, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/vault/webauthn/challenge")
def webauthn_challenge(vault_id: str = DEFAULT_VAULT, db: DbSession = Depends(get_db)):
    from services.webauthn import new_challenge

    _ensure_default(db)
    ch = new_challenge()
    _wa_challenges[vault_id] = (time.time() + _WA_TTL, ch)
    creds = db.query(WebAuthnCredential).filter(WebAuthnCredential.vault_id == vault_id).all()
    return {"challenge": ch, "credentials": [c.credential_id for c in creds]}


class WaUnlock(BaseModel):
    vault_id: str = DEFAULT_VAULT
    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str


@router.post("/vault/webauthn/unlock")
def webauthn_unlock(body: WaUnlock, db: DbSession = Depends(get_db)):
    from services.webauthn import verify_assertion

    _ensure_default(db)
    vid = body.vault_id or DEFAULT_VAULT
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)
    if _travel_on() and not v.travel_safe:
        raise HTTPException(403, "vault unavailable in travel mode")
    entry = _wa_challenges.pop(vid, None)
    if not entry or time.time() > entry[0]:
        raise HTTPException(401, "challenge expired")
    cred = (
        db.query(WebAuthnCredential)
        .filter(
            WebAuthnCredential.vault_id == vid,
            WebAuthnCredential.credential_id == body.credential_id,
        )
        .first()
    )
    if not cred:
        raise HTTPException(404, "unknown credential")
    if not verify_assertion(
        cred.public_key, body.authenticator_data, body.client_data_json, body.signature, entry[1]
    ):
        raise HTTPException(401, "assertion failed")
    if not v.biometric_blob:
        raise HTTPException(400, "biometric not set up")
    try:
        pw = decrypt(_server_key(), v.biometric_blob)
    except Exception:
        raise HTTPException(500, "biometric unwrap failed")
    return {"token": _mint(pw, vid), "vault_id": vid}


# ── passkey storage + use (9d) ────────────────────────────────────────────────
# The vault holds passkeys it presents to other sites: an ES256 keypair whose private
# key lives encrypted in a normal vault entry (type "passkey").
class PasskeyNew(BaseModel):
    rp_id: str
    username: str = ""


@router.post("/vault/passkey/new")
def passkey_new(body: PasskeyNew, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    from services.passkey import create_passkey

    pw, vid = ctx
    rp = (body.rp_id or "").strip()
    if not rp:
        raise HTTPException(400, "rp_id required")
    pk = create_passkey(rp, body.username or "")
    fields = {
        "rp_id": pk["rp_id"],
        "username": pk["username"],
        "credential_id": pk["credential_id"],
        "public_key": pk["public_key"],
        "private_key": pk["private_key_pem"],
    }
    e = VaultEntry(
        vault_id=vid,
        name=f"{pk['username'] or 'passkey'} @ {rp}",
        username=pk["username"],
        value_encrypted=encrypt(pw, json.dumps(fields)),
        category="passkey",
        type="passkey",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    # never hand back the private key
    return {
        "id": e.id,
        "rp_id": pk["rp_id"],
        "username": pk["username"],
        "credential_id": pk["credential_id"],
        "public_key": pk["public_key"],
    }


@router.get("/vault/passkeys")
def passkey_list(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    out = []
    rows = (
        db.query(VaultEntry)
        .filter(VaultEntry.vault_id == vid, VaultEntry.type == "passkey")
        .order_by(VaultEntry.created_at.desc())
        .all()
    )
    for e in rows:
        f = _entry_fields(e, pw)
        out.append(
            {
                "id": e.id,
                "name": e.name,
                "rp_id": f.get("rp_id", ""),
                "username": f.get("username", ""),
            }
        )
    return out


class PasskeySign(BaseModel):
    authenticator_data: str
    client_data_json: str


@router.post("/vault/{entry_id}/passkey/sign")
def passkey_sign(
    entry_id: str, body: PasskeySign, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    from services.passkey import sign

    pw, vid = ctx
    e = db.get(VaultEntry, entry_id)
    if not e or e.vault_id != vid or (e.type or "") != "passkey":
        raise HTTPException(404)
    priv = _entry_fields(e, pw).get("private_key")
    if not priv:
        raise HTTPException(400, "no private key on this passkey")
    try:
        sig = sign(priv, body.authenticator_data, body.client_data_json)
    except Exception:
        raise HTTPException(400, "could not sign")
    return {"signature": sig, "credential_id": _entry_fields(e, pw).get("credential_id", "")}


# ── hardware-key (FIDO2/YubiKey) 2FA gate for unlock (9d) ──────────────────────
@router.post("/vault/2fa/register")
def twofa_register(body: WaRegister, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    db.add(
        WebAuthnCredential(
            vault_id=vid,
            label=body.label or "security key",
            credential_id=body.credential_id,
            public_key=body.public_key,
            role="2fa",
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/vault/2fa")
def twofa_status(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    creds = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vid, WebAuthnCredential.role == "2fa")
        .all()
    )
    return {
        "on": _require_2fa(vid),
        "totp": _has_totp_2fa(vid),  # 8c — authenticator-app factor enrolled?
        "credentials": [
            {"id": c.id, "label": c.label, "credential_id": c.credential_id} for c in creds
        ],
    }


# ── authenticator-app (TOTP) 2FA for unlock (8c) ──────────────────────────────
@router.post("/vault/2fa/totp/setup")
def totp_setup(ctx: tuple = Depends(_ctx)):
    """hand back a fresh secret + otpauth URI to enrol an authenticator app. The secret isn't stored
    until the user proves they scanned it (POST /vault/2fa/totp with a valid code)."""
    from services.pwtools import totp_secret, totp_uri

    vid = ctx[1]
    secret = totp_secret()
    v_name = vid
    return {"secret": secret, "uri": totp_uri(secret, label=f"vault-{v_name}")}


class TotpEnable(BaseModel):
    secret: str
    code: str


@router.post("/vault/2fa/totp")
def totp_enable(body: TotpEnable, ctx: tuple = Depends(_ctx)):
    from services.pwtools import totp_verify

    vid = ctx[1]
    if not totp_verify(body.secret, body.code):
        raise HTTPException(400, "code didn't match — check your authenticator app")
    m = _totp_map()
    m[vid] = body.secret
    save_settings({"vault_2fa_totp": m})
    # enabling a factor turns the 2FA gate on for this vault
    req = dict(load_settings().get("vault_require_2fa") or {})
    req[vid] = True
    save_settings({"vault_require_2fa": req})
    return {"ok": True, "totp": True}


@router.delete("/vault/2fa/totp")
def totp_disable(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    m = _totp_map()
    m.pop(vid, None)
    save_settings({"vault_2fa_totp": m})
    # if no factors remain, drop the gate so the user isn't locked into a broken 2FA state
    if not _has_2fa_cred(db, vid):
        req = dict(load_settings().get("vault_require_2fa") or {})
        req[vid] = False
        save_settings({"vault_require_2fa": req})
    return {"ok": True, "totp": False}


class TotpUnlockBody(BaseModel):
    vault_id: str = DEFAULT_VAULT
    password: str
    code: str


@router.post("/vault/unlock/2fa/totp")
def totp_unlock(body: TotpUnlockBody, db: DbSession = Depends(get_db)):
    from services.pwtools import totp_verify

    _ensure_default(db)
    vid = body.vault_id or DEFAULT_VAULT
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404, "no such vault")
    if _travel_on() and not v.travel_safe:
        raise HTTPException(403, "vault unavailable in travel mode")
    if not verify_master(body.password, v.verifier):
        raise HTTPException(401, "wrong master password")
    secret = _totp_map().get(vid)
    if not secret or not totp_verify(secret, body.code):
        raise HTTPException(401, "wrong authenticator code")
    return {"token": _mint(body.password, vid), "vault_id": vid}


@router.put("/vault/2fa")
def twofa_set(body: TravelBody, ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    m = dict(load_settings().get("vault_require_2fa") or {})
    m[vid] = bool(body.on)
    save_settings({"vault_require_2fa": m})
    return {"on": bool(body.on)}


class TwoFaUnlock(BaseModel):
    vault_id: str = DEFAULT_VAULT
    password: str
    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str


@router.post("/vault/unlock/2fa")
def twofa_unlock(body: TwoFaUnlock, db: DbSession = Depends(get_db)):
    from services.webauthn import verify_assertion

    _ensure_default(db)
    vid = body.vault_id or DEFAULT_VAULT
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404, "no such vault")
    if _travel_on() and not v.travel_safe:
        raise HTTPException(403, "vault unavailable in travel mode")
    if not verify_master(body.password, v.verifier):
        raise HTTPException(401, "wrong master password")
    cred = (
        db.query(WebAuthnCredential)
        .filter(
            WebAuthnCredential.vault_id == vid,
            WebAuthnCredential.role == "2fa",
            WebAuthnCredential.credential_id == body.credential_id,
        )
        .first()
    )
    if not cred:
        raise HTTPException(404, "unknown security key")
    entry = _wa_challenges.pop(vid, None)
    if not entry or time.time() > entry[0]:
        raise HTTPException(401, "challenge expired")
    if not verify_assertion(
        cred.public_key, body.authenticator_data, body.client_data_json, body.signature, entry[1]
    ):
        raise HTTPException(401, "assertion failed")
    return {"token": _mint(body.password, vid), "vault_id": vid}


# ── browser-extension autofill (9d) ───────────────────────────────────────────
def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    u = url if "//" in url else "//" + url
    return (urlparse(u).hostname or "").lower().removeprefix("www.")


def _host_match(stored: str, domain: str) -> bool:
    s, d = stored.removeprefix("www."), domain.lower().removeprefix("www.")
    if not s or not d:
        return False
    return s == d or s.endswith("." + d) or d.endswith("." + s)


@router.get("/vault/match")
def vault_match(domain: str = "", db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    """logins in this vault whose stored url host matches `domain` — for the autofill extension."""
    pw, vid = ctx
    out = []
    rows = db.query(VaultEntry).filter(VaultEntry.vault_id == vid, VaultEntry.type == "login").all()
    for e in rows:
        f = _entry_fields(e, pw)
        host = _host_of(f.get("url") or "")
        if host and _host_match(host, domain):
            out.append(
                {
                    "id": e.id,
                    "name": e.name,
                    "username": f.get("username") or e.username or "",
                    "password": f.get("password") or "",
                }
            )
    return out
