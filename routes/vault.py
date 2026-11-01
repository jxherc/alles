import json
import logging
import re
import secrets
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import (
    BrowserConnection,
    Vault,
    VaultAttachment,
    VaultCreateReceipt,
    VaultEntry,
    VaultShare,
    VaultUploadReceipt,
    WebAuthnCredential,
    get_db,
)
from core.settings import load_settings, save_settings
from services import vault_audit, vault_keys
from services.crypto import (
    VaultKey,
    decrypt,
    encrypt,
    is_v2,
    new_vault_key,
    open_vault_key,
    rewrap,
    verify_master,
)
from services.recovery_consistency import recovery_consistency_lock

router = APIRouter(prefix="/api")
log = logging.getLogger("alles.vault")

# token → (expiry, open vault key, vault_id). never written to disk; the password itself is
# never kept, only the key it unwrapped. a token dies after 10 idle minutes (auto lock).
_unlock_tokens: dict[str, tuple[float, VaultKey, str]] = {}
_TTL = 600  # 10 min
DEFAULT_VAULT = "default"
MIN_VAULT_PASSWORD_LENGTH = 8


def _require_new_vault_password(password: str) -> None:
    if len(password) < MIN_VAULT_PASSWORD_LENGTH:
        raise HTTPException(
            400,
            f"vault password must be at least {MIN_VAULT_PASSWORD_LENGTH} characters",
        )


def _mint(pw: VaultKey, vault_id: str, *, travel_safe: bool) -> str:
    with recovery_consistency_lock:
        if _travel_on() and not travel_safe:
            raise HTTPException(403, "vault unavailable in travel mode")
        tok = secrets.token_urlsafe(16)
        _unlock_tokens[tok] = (time.time() + _TTL, pw, vault_id)
        return tok


def _ctx(
    x_vault_token: str | None = Header(None),
    db: DbSession = Depends(get_db),
) -> tuple[str, str]:
    """resolve the caller's own unlock token to (master_password, vault_id).

    binds each vault request to the token returned by /vault/unlock, so an
    unlock by one session no longer hands the vault to every other request
    that happens to land in the 10-min window.
    """
    with recovery_consistency_lock:
        now = time.time()
        for tok in [t for t, (exp, _, _) in list(_unlock_tokens.items()) if now > exp]:
            del _unlock_tokens[tok]
        token = x_vault_token or ""
        context = _unlock_tokens.get(token)
        if not context:
            raise HTTPException(403, "vault locked")
        vault = db.get(Vault, context[2])
        if not vault or (_travel_on() and not vault.travel_safe):
            _unlock_tokens.pop(token, None)
            raise HTTPException(403, "vault locked")
        _unlock_tokens[token] = (now + _TTL, context[1], context[2])
        return context[1], context[2]


def _master_pw(
    x_vault_token: str | None = Header(None),
    db: DbSession = Depends(get_db),
) -> str:
    return _ctx(x_vault_token, db)[0]


# every per-entry / per-attachment endpoint has to scope to the unlocked vault. without it,
# unlocking vault A lets you reveal/delete/attach-to/share vault B's entries (cross-vault
# read, data loss, and re-encrypt-under-wrong-key corruption). a vault mismatch is a 404 —
# same guard patch_entry already uses.
def _scoped_entry(db, entry_id: str, vid: str) -> "VaultEntry":
    e = db.get(VaultEntry, entry_id)
    if not e or e.vault_id != vid:
        raise HTTPException(404)
    return e


def _scoped_attachment(db, aid: str, vid: str) -> "VaultAttachment":
    a = db.get(VaultAttachment, aid)
    if not a:
        raise HTTPException(404)
    e = db.get(VaultEntry, a.entry_id)
    if not e or e.vault_id != vid:
        raise HTTPException(404)
    return a


def _require_current_vault_password(db, pw: VaultKey, vid: str) -> "Vault":
    """Reject an unlock token whose password was replaced while its request was waiting."""
    vault = db.get(Vault, vid)
    if not vault or not isinstance(pw, VaultKey) or not pw.current_for(vault.verifier):
        raise HTTPException(403, "vault locked")
    return vault


def _open_with_password(db, v: "Vault", password: str, *, how: str = "password") -> VaultKey:
    """check the password (throttled) and return the open vault key, upgrading a v1 vault."""
    wait = vault_keys.wait_left(v.id, v.verifier)
    if wait:
        raise HTTPException(
            429, f"too many wrong tries, wait {wait}s", headers={"Retry-After": str(wait)}
        )
    opened = open_vault_key(password, v.verifier) if is_v2(v.verifier) else None
    if opened is None and not (not is_v2(v.verifier) and verify_master(password, v.verifier)):
        vault_keys.failed(v.id, v.verifier)
        vault_audit.record(v.id, "unlock_failed", how=how)
        raise HTTPException(401, "wrong master password")
    vault_keys.succeeded(v.id, v.verifier)
    try:
        key = vault_keys.upgrade_vault(db, v, password, _attach_dir(), _server_key, key=opened)
    except Exception:
        log.exception("vault %s: key upgrade failed, nothing changed", v.id)
        raise HTTPException(500, "vault upgrade failed; nothing was changed")
    if v.id == DEFAULT_VAULT and load_settings().get("vault_verifier") != v.verifier:
        save_settings({"vault_verifier": v.verifier})  # keep legacy mirror in sync
    return key


def _reserve_vault_write(db, pw, vid):
    # Reserve SQLite's write before reading files/receipts, including across workers.
    db.query(Vault).filter_by(id=vid).update({Vault.id: Vault.id}, synchronize_session=False)
    db.expire_all()
    return _require_current_vault_password(db, pw, vid)


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


def _can_initialize_vault(db: DbSession, vault: Vault) -> bool:
    """Allow password creation only for a genuinely empty default vault.

    Secondary vaults are always created with a verifier. An empty verifier on
    one of them, or on a default vault that already owns data or an enrolled
    authenticator, is recovery state rather than first-run setup.
    """
    if vault.id != DEFAULT_VAULT or vault.biometric_blob:
        return False
    if db.query(VaultEntry.id).filter(VaultEntry.vault_id == vault.id).first() is not None:
        return False
    if (
        db.query(BrowserConnection.id).filter(BrowserConnection.vault_id == vault.id).first()
        is not None
    ):
        return False
    if (
        db.query(WebAuthnCredential.id).filter(WebAuthnCredential.vault_id == vault.id).first()
        is not None
    ):
        return False
    return not _require_2fa(vault.id) and not _has_totp_2fa(vault.id)


def _drop_vault_settings(vid: str):
    s = load_settings()
    patch = {}
    for key in ("vault_require_2fa", "vault_2fa_totp"):
        m = dict(s.get(key) or {})
        if vid in m:
            m.pop(vid, None)
            patch[key] = m
    if patch:
        save_settings(patch)


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


@router.get("/vault/setup")
def vault_setup(db: DbSession = Depends(get_db)):
    v = db.get(Vault, DEFAULT_VAULT)
    if v is None:
        v = Vault(id=DEFAULT_VAULT, verifier=load_settings().get("vault_verifier", ""))
    state = "locked" if v.verifier else "setup" if _can_initialize_vault(db, v) else "recovery"
    return {"state": state, "minimum_password_length": MIN_VAULT_PASSWORD_LENGTH}


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
        if not _can_initialize_vault(db, v):
            raise HTTPException(
                409, "vault verifier is missing; restore the vault before unlocking"
            )
        # first unlock for this vault — store only the verifier (no plaintext on disk)
        _require_new_vault_password(body.password)
        key = new_vault_key(body.password)
        v.verifier = key.verifier
        if vid == DEFAULT_VAULT:
            save_settings({"vault_verifier": v.verifier})  # keep legacy mirror in sync
        db.commit()
        vault_audit.record(vid, "created")
        return {
            "token": _mint(key, vid, travel_safe=bool(v.travel_safe)),
            "vault_id": vid,
        }
    key = _open_with_password(db, v, body.password)
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
    vault_audit.record(vid, "unlocked", how="password")
    return {
        "token": _mint(key, vid, travel_safe=bool(v.travel_safe)),
        "vault_id": vid,
    }


@router.post("/vault/lock")
def vault_lock(x_vault_token: str | None = Header(None)):
    context = None
    if x_vault_token:
        with recovery_consistency_lock:
            context = _unlock_tokens.pop(x_vault_token, None)
        if context:
            from services.browser_passwords import lock_vault

            lock_vault(context[2])
            vault_audit.record(context[2], "locked")
    return {"ok": True}


# ── multiple vaults + Travel Mode (9c) ────────────────────────────────────────
@router.get("/vault/travel-mode")
def get_travel_mode():
    return {"on": _travel_on()}


class TravelBody(BaseModel):
    on: bool


@router.put("/vault/travel-mode")
def set_travel_mode(
    body: TravelBody,
    db: DbSession = Depends(get_db),
    _pw: str = Depends(_master_pw),
):
    enabled = bool(body.on)
    unsafe_vault_ids: set[str] = set()
    with recovery_consistency_lock:
        _ensure_default(db)
        if enabled and not db.query(Vault).filter(Vault.travel_safe.is_(True)).first():
            raise HTTPException(
                409, "mark at least one vault travel-safe before enabling Travel Mode"
            )
        save_settings({"vault_travel_mode": enabled})
        if enabled:
            unsafe_vault_ids = {
                row.id for row in db.query(Vault).filter(Vault.travel_safe.is_(False)).all()
            }
            for token, (_expires, _password, vault_id) in list(_unlock_tokens.items()):
                if vault_id in unsafe_vault_ids:
                    _unlock_tokens.pop(token, None)
    if enabled:
        from services.browser_passwords import lock_vault

        for vault_id in unsafe_vault_ids:
            lock_vault(vault_id)
    return {"on": enabled}


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
                "main": v.id
                == DEFAULT_VAULT,  # 8b — the main vault opens with your master password
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
    _require_new_vault_password(body.password)
    v = Vault(name=name, verifier=new_vault_key(body.password).verifier, travel_safe=False)
    db.add(v)
    db.commit()
    db.refresh(v)
    vault_audit.record(v.id, "created")
    return {"id": v.id, "name": v.name}


class VaultPatch(BaseModel):
    name: str | None = None
    travel_safe: bool | None = None


@router.patch("/vault/vaults/{vid}")
def patch_vault(
    vid: str, body: VaultPatch, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    pw, unlocked_vid = ctx
    if unlocked_vid != vid:
        raise HTTPException(404)
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404)
    _require_current_vault_password(db, pw, vid)
    if body.name is not None and body.name.strip():
        v.name = body.name.strip()
    if body.travel_safe is not None:
        if vid == DEFAULT_VAULT and not body.travel_safe:
            raise HTTPException(400, "the default vault must remain travel-safe")
        v.travel_safe = bool(body.travel_safe)
    db.commit()
    return {"ok": True}


class ChangePw(BaseModel):
    new_password: str
    current_password: str = ""


@router.post("/vault/vaults/password")
def change_vault_password(
    body: ChangePw, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    """8b: change the open vault's password. the main vault's password IS the master password.
    the vault key stays the same and only its wrap changes (1password white paper, appendix
    A.5), so entries, attachments and passkey wraps are untouched and nothing can be left half
    re-keyed. the current password is asked again, as bitwarden and 1password both do, so an
    open session alone can't take the vault over."""
    key, vid = ctx
    new = body.new_password or ""
    _require_new_vault_password(new)
    with recovery_consistency_lock:
        v = _require_current_vault_password(db, key, vid)
        current = _open_with_password(db, v, body.current_password or "", how="password change")
        if current.key != key.key:
            raise HTTPException(403, "vault locked")
        fresh = rewrap(new, current)
        v.verifier = fresh.verifier
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(500, "password change failed; nothing changed")
        if vid == DEFAULT_VAULT:
            try:
                save_settings({"vault_verifier": v.verifier})  # legacy master mirror
            except Exception:
                # The database is authoritative once the default vault exists. A stale legacy
                # mirror must not roll back the committed wrap or report a false failure.
                log.warning("could not update the legacy default-vault verifier mirror")
        for token, (_expires, _key, token_vid) in list(_unlock_tokens.items()):
            if token_vid == vid:
                _unlock_tokens.pop(token, None)
        from services.browser_passwords import lock_vault

        lock_vault(vid)
        new_token = _mint(fresh, vid, travel_safe=bool(v.travel_safe))
    vault_audit.record(vid, "password_changed")
    # the caller's token was bound to the old wrap; hand back a fresh one
    return {"ok": True, "token": new_token, "vault_id": vid}


@router.delete("/vault/vaults/{vid}")
def delete_vault(vid: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    if vid == DEFAULT_VAULT:
        raise HTTPException(400, "cannot delete the default vault")
    pw, unlocked_vid = ctx
    if unlocked_vid != vid:
        raise HTTPException(404)
    with recovery_consistency_lock:
        v = _reserve_vault_write(db, pw, vid)
        eids = [r.id for r in db.query(VaultEntry).filter(VaultEntry.vault_id == vid).all()]
        _purge_entry_data(db, eids)  # shares + attachment blobs for every entry in the vault
        db.query(WebAuthnCredential).filter(WebAuthnCredential.vault_id == vid).delete(
            synchronize_session=False
        )
        db.query(BrowserConnection).filter(BrowserConnection.vault_id == vid).delete(
            synchronize_session=False
        )
        db.query(VaultEntry).filter(VaultEntry.vault_id == vid).delete(synchronize_session=False)
        db.query(VaultCreateReceipt).filter_by(vault_id=vid).delete(synchronize_session=False)
        db.query(VaultUploadReceipt).filter_by(vault_id=vid).delete(synchronize_session=False)
        db.delete(v)
        db.commit()
        from services.browser_passwords import lock_vault

        lock_vault(vid)
        _drop_vault_settings(vid)
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
    request_id: str = ""


def _fields_of(body) -> dict:
    """normalize a create/patch body into a fields dict to encrypt."""
    if body.fields is not None:
        return body.fields
    return {"password": body.value} if body.value else {}


def _create_identity(raw: str) -> str:
    try:
        identity = str(uuid.UUID(raw))
        if raw.lower() != identity:
            raise ValueError
        return identity
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "request_id must be a canonical UUID") from None


def _find_create_receipt(db, vid, identity):
    return (
        db.query(VaultCreateReceipt, VaultEntry)
        .outerjoin(
            VaultEntry,
            (VaultEntry.id == VaultCreateReceipt.entry_id)
            & (VaultEntry.vault_id == VaultCreateReceipt.vault_id),
        )
        .filter(VaultCreateReceipt.vault_id == vid, VaultCreateReceipt.id == identity)
        .populate_existing()
        .one_or_none()
    )


def _receipt_entry(found):
    if found is None:
        raise HTTPException(404, "this save could not be found")
    if found[1] is None:
        raise HTTPException(410, "the entry from this save was deleted")
    return found[1]


def _receipt_fields(entry, pw):
    try:
        fields = json.loads(decrypt(pw, entry.value_encrypted))
        if not isinstance(fields, dict):
            raise ValueError
        return fields
    except Exception:
        raise HTTPException(500, "could not read the saved entry") from None


def _created_entry_response(entry):
    return {"id": entry.id, "name": entry.name, "category": entry.category, "type": entry.type}


@router.get("/vault/requests/{request_id}")
def recover_created_entry(
    request_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    pw, vid = ctx
    with recovery_consistency_lock:
        _require_current_vault_password(db, pw, vid)
        entry = _receipt_entry(_find_create_receipt(db, vid, _create_identity(request_id)))
        return {
            **_created_entry_response(entry),
            "username": entry.username,
            "fields": _receipt_fields(entry, pw),
        }


@router.post("/vault")
def create_entry(body: CreateEntry, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    with recovery_consistency_lock:
        _require_current_vault_password(db, pw, vid)
        receipt = None
        if body.request_id:
            identity = _create_identity(body.request_id)
            try:
                fields_json = json.dumps(_fields_of(body), sort_keys=True, allow_nan=False)
            except (ValueError, TypeError):
                raise HTTPException(400, "entry fields must contain valid JSON values") from None

            def replay(found):
                entry = _receipt_entry(found)
                fields = _receipt_fields(entry, pw)
                if (entry.name, entry.username, entry.category, entry.type) != (
                    body.name,
                    body.username,
                    body.category,
                    body.type or "password",
                ) or json.dumps(fields, sort_keys=True, allow_nan=False) != fields_json:
                    raise HTTPException(
                        409,
                        {
                            "message": "this entry was already saved with different values; open it to make a correction",
                            "entry_id": entry.id,
                        },
                    )
                return _created_entry_response(entry)

            found = _find_create_receipt(db, vid, identity)
            if found is not None:
                return replay(found)
            receipt = VaultCreateReceipt(vault_id=vid, id=identity)
            db.add(receipt)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                _require_current_vault_password(db, pw, vid)
                found = _find_create_receipt(db, vid, identity)
                if found is None:
                    raise
                return replay(found)
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
        if receipt is not None:
            db.flush()
            receipt.entry_id = e.id
        db.commit()
        if receipt is not None:
            return _created_entry_response(_receipt_entry(_find_create_receipt(db, vid, identity)))
        db.refresh(e)
    return _created_entry_response(e)


class PatchEntry(BaseModel):
    name: str | None = None
    value: str | None = None
    fields: dict | None = None
    type: str | None = None
    category: str | None = None
    username: str | None = None


@router.patch("/vault/{entry_id}")
def patch_entry(
    entry_id: str, body: PatchEntry, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    pw, vid = ctx
    with recovery_consistency_lock:
        _require_current_vault_password(db, pw, vid)
        # scope to the unlocked vault, or patching re-encrypts another vault's entry under this
        # vault's key and bricks it
        e = _scoped_entry(db, entry_id, vid)
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
def reveal_entry(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    e = _scoped_entry(db, entry_id, vid)
    try:
        raw = decrypt(pw, e.value_encrypted)
    except Exception:
        raise HTTPException(500, "decryption failed")
    vault_audit.record(vid, "revealed", entry=e.id)
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


def _purge_entry_data(db, eids):
    """delete an entry's share links + attachments (rows AND .enc blobs) so a deleted secret
    can't keep serving from a live /sv link or leak ciphertext on disk."""
    if not eids:
        return
    db.query(VaultShare).filter(VaultShare.entry_id.in_(eids)).delete(synchronize_session=False)
    for a in db.query(VaultAttachment).filter(VaultAttachment.entry_id.in_(eids)).all():
        db.query(VaultUploadReceipt).filter_by(attachment_id=a.id).update(
            {VaultUploadReceipt.attachment_id: None}, synchronize_session=False
        )
        (_attach_dir() / f"{a.id}.enc").unlink(missing_ok=True)
    db.query(VaultAttachment).filter(VaultAttachment.entry_id.in_(eids)).delete(
        synchronize_session=False
    )


@router.delete("/vault/{entry_id}")
def delete_entry(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    with recovery_consistency_lock:
        _reserve_vault_write(db, pw, vid)
        e = _scoped_entry(db, entry_id, vid)
        _purge_entry_data(db, [entry_id])
        db.query(VaultCreateReceipt).filter_by(vault_id=vid, entry_id=entry_id).update(
            {VaultCreateReceipt.entry_id: None}, synchronize_session=False
        )
        db.delete(e)
        db.commit()
    vault_audit.record(vid, "deleted", entry=entry_id)
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
def entry_totp(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    e = _scoped_entry(db, entry_id, vid)
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

    r = httpx.get(
        f"https://api.pwnedpasswords.com/range/{prefix}",
        timeout=httpx.Timeout(1.5, connect=0.8),
    )
    r.raise_for_status()
    return r.text


@router.get("/vault/watchtower")
def watchtower(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    import time

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
    checked = 0
    deadline = time.monotonic() + 3.0
    for i in items:
        if i["password"] not in seen:
            try:
                cnt = (
                    breach_count(i["password"], _hibp_fetch, strict=True)
                    if time.monotonic() < deadline
                    else None
                )
            except Exception:
                cnt = None
            seen[i["password"]] = cnt
        cnt = seen[i["password"]]
        checked += cnt is not None
        if cnt is not None and cnt > 0:
            breached.append({"id": i["id"], "name": i["name"], "count": cnt})

    return {
        "weak": weak,
        "reused": reused,
        "breached": breached,
        "breach_check": {
            "status": "complete"
            if checked == len(items)
            else "partial"
            if checked
            else "unavailable",
            "checked": checked,
            "total": len(items),
        },
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
    ctx: tuple = Depends(_ctx),
    request_id: Annotated[str, Form()] = "",
):
    from services.crypto import decrypt_bytes, encrypt_bytes

    pw, vid = ctx
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "attachment too large (25MB max)")
    identity = _create_identity(request_id) if request_id else None
    att = VaultAttachment(entry_id=entry_id, filename=file.filename or "file", size=len(data))
    with recovery_consistency_lock:
        _reserve_vault_write(db, pw, vid)
        _scoped_entry(db, entry_id, vid)
        receipt = db.get(VaultUploadReceipt, (vid, identity)) if identity else None
        if receipt is not None:
            saved = (
                db.get(VaultAttachment, receipt.attachment_id) if receipt.attachment_id else None
            )
            if saved is None:
                raise HTTPException(410, "the attachment from this upload was deleted")
            if saved.entry_id != entry_id or saved.filename != att.filename:
                raise HTTPException(409, "this upload was already saved with different values")
            try:
                saved_data = decrypt_bytes(pw, (_attach_dir() / f"{saved.id}.enc").read_bytes())
            except Exception:
                raise HTTPException(500, "could not read the saved attachment") from None
            if saved_data != data:
                raise HTTPException(409, "this upload was already saved with different values")
            return {"id": saved.id, "filename": saved.filename, "size": saved.size}
        path = None
        try:
            if identity:
                receipt = VaultUploadReceipt(vault_id=vid, id=identity)
                db.add(receipt)
                db.flush()
            db.add(att)
            db.flush()
            if receipt is not None:
                receipt.attachment_id = att.id
            path = _attach_dir() / f"{att.id}.enc"
            path.write_bytes(encrypt_bytes(pw, data))
            db.commit()
        except Exception:
            db.rollback()
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    return {"id": att.id, "filename": att.filename, "size": att.size}


@router.get("/vault/{entry_id}/attachments")
def list_attachments(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    _, vid = ctx
    _scoped_entry(db, entry_id, vid)
    rows = db.query(VaultAttachment).filter(VaultAttachment.entry_id == entry_id).all()
    return [{"id": a.id, "filename": a.filename, "size": a.size} for a in rows]


@router.get("/vault/attachments/{aid}")
def download_attachment(aid: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    from services.crypto import decrypt_bytes

    pw, vid = ctx
    a = _scoped_attachment(db, aid, vid)
    p = _attach_dir() / f"{aid}.enc"
    if not p.is_file():
        raise HTTPException(404)
    try:
        data = decrypt_bytes(pw, p.read_bytes())
    except Exception:
        raise HTTPException(500, "decryption failed")
    import mimetypes

    mt = mimetypes.guess_type(a.filename)[0] or "application/octet-stream"
    # the stored name is user-controlled: strip header-hostile chars so the
    # content-disposition value can't be malformed or split the response.
    safe_name = re.sub(r'[\r\n";\\]+', "_", a.filename or "download").strip() or "download"
    return Response(
        content=data,
        media_type=mt,
        headers={"content-disposition": f'attachment; filename="{safe_name}"'},
    )


@router.delete("/vault/attachments/{aid}")
def delete_attachment(aid: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    pw, vid = ctx
    with recovery_consistency_lock:
        _reserve_vault_write(db, pw, vid)
        a = _scoped_attachment(db, aid, vid)
        db.query(VaultUploadReceipt).filter_by(vault_id=vid, attachment_id=aid).update(
            {VaultUploadReceipt.attachment_id: None}, synchronize_session=False
        )
        try:
            (_attach_dir() / f"{aid}.enc").unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(a)
        db.commit()
    return {"ok": True}


# ── per-item share (9b) — random-key envelope; key travels in the URL fragment ─
@router.post("/vault/{entry_id}/share")
def share_entry(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    from services.crypto import envelope_encrypt

    pw, vid = ctx
    e = _scoped_entry(db, entry_id, vid)
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
def revoke_entry_share(entry_id: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    _, vid = ctx
    _scoped_entry(db, entry_id, vid)
    db.query(VaultShare).filter(VaultShare.entry_id == entry_id).delete()
    db.commit()
    return {"ok": True}


# ── WebAuthn biometric unlock (9c) ────────────────────────────────────────────
# A registered platform authenticator gates release of the master pw, which is
# wrapped under a per-install server key. Convenience-unlock tradeoff: the wrapped
# blob lives on disk, but only a verified assertion unwraps it.
_wa_challenges: dict[str, tuple[float, str]] = {}  # vault_id -> (exp, challenge)
_WA_TTL = 300


def _request_origin(request: Request) -> str:
    return (request.headers.get("origin") or str(request.base_url).rstrip("/")).rstrip("/")


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
    prf: str = ""  # the passkey's PRF output for prf_salt, when the authenticator has PRF


def _prf_salt(vault_id: str) -> str:
    # the PRF input needn't be secret: the authenticator's own per-credential secret makes the
    # output unique. one fixed salt per vault keeps unlock to a single get() call.
    import base64
    import hashlib

    raw = hashlib.sha256(b"alles-vault-prf:" + vault_id.encode()).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _prf_bytes(text: str) -> bytes | None:
    import base64

    if not text:
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError:
        raise HTTPException(400, "bad prf output")
    if len(raw) != 32:
        raise HTTPException(400, "bad prf output")
    return raw


@router.post("/vault/webauthn/register")
def webauthn_register(
    body: WaRegister, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)
):
    pw, vid = ctx
    with recovery_consistency_lock:
        v = _require_current_vault_password(db, pw, vid)
        cred = WebAuthnCredential(
            vault_id=vid,
            label=body.label or "device",
            credential_id=body.credential_id,
            public_key=body.public_key,
        )
        db.add(cred)
        prf = _prf_bytes(body.prf)
        # the passkey gets its own wrap of the vault key: under its PRF output when it has
        # one (the data folder alone can't open it), else under the device key
        v.biometric_blob = vault_keys.add_wrap(
            v.biometric_blob or "", body.credential_id, pw, prf, _server_key
        )
        db.commit()
        db.refresh(cred)
    vault_audit.record(vid, "passkey_added", how="prf" if prf else "device")
    return {"id": cred.id, "label": cred.label, "prf": bool(prf)}


@router.get("/vault/webauthn/credentials")
def webauthn_credentials(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    vid = ctx[1]
    rows = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vid, WebAuthnCredential.role != "2fa")
        .all()
    )
    blob = (db.get(Vault, vid).biometric_blob or "") if db.get(Vault, vid) else ""
    return [
        {
            "id": c.id,
            "label": c.label,
            "credential_id": c.credential_id,
            "prf": vault_keys.wrap_kind(blob, c.credential_id) == "prf",
        }
        for c in rows
    ]


@router.delete("/vault/webauthn/credentials/{cid}")
def webauthn_delete(cid: str, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    c = db.get(WebAuthnCredential, cid)
    if not c or c.vault_id != ctx[1]:
        raise HTTPException(404)
    vid = c.vault_id
    if c.role == "2fa":
        raise HTTPException(404)
    db.delete(c)
    db.flush()
    left = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vid, WebAuthnCredential.role != "2fa")
        .count()
    )
    v = db.get(Vault, vid)
    if v:
        v.biometric_blob = (
            "" if left == 0 else vault_keys.drop_wrap(v.biometric_blob, c.credential_id)
        )
    db.commit()
    vault_audit.record(vid, "passkey_removed")
    return {"ok": True}


@router.get("/vault/webauthn/challenge")
def webauthn_challenge(vault_id: str = DEFAULT_VAULT, db: DbSession = Depends(get_db)):
    from services.webauthn import new_challenge

    _ensure_default(db)
    ch = new_challenge()
    _wa_challenges[vault_id] = (time.time() + _WA_TTL, ch)
    creds = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.vault_id == vault_id, WebAuthnCredential.role != "2fa")
        .all()
    )
    return {
        "challenge": ch,
        "credentials": [c.credential_id for c in creds],
        "prf_salt": _prf_salt(vault_id),
    }


class WaUnlock(BaseModel):
    vault_id: str = DEFAULT_VAULT
    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str
    prf: str = ""


@router.post("/vault/webauthn/unlock")
def webauthn_unlock(body: WaUnlock, request: Request, db: DbSession = Depends(get_db)):
    from services.webauthn import sign_count, verify_assertion

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
            WebAuthnCredential.role != "2fa",
        )
        .first()
    )
    if not cred:
        raise HTTPException(404, "unknown credential")
    if not verify_assertion(
        cred.public_key,
        body.authenticator_data,
        body.client_data_json,
        body.signature,
        entry[1],
        _request_origin(request),
        previous_sign_count=cred.sign_count or 0,
        require_user_verification=True,
    ):
        raise HTTPException(401, "assertion failed")
    if not v.biometric_blob:
        raise HTTPException(400, "biometric not set up")
    cred.sign_count = max(cred.sign_count or 0, sign_count(body.authenticator_data))
    db.commit()
    if vault_keys.load_wraps(v.biometric_blob) is None:
        # a vault from before wrapped keys: the old blob still holds the password, so this
        # unlock upgrades the vault and drops that copy
        try:
            legacy_pw = decrypt(_server_key(), v.biometric_blob)
        except Exception:
            raise HTTPException(500, "biometric unwrap failed")
        key = _open_with_password(db, v, legacy_pw, how="passkey")
    else:
        if not is_v2(v.verifier):
            raise HTTPException(409, "unlock with your password once")
        if vault_keys.wrap_kind(v.biometric_blob, cred.credential_id) == "prf" and not body.prf:
            raise HTTPException(400, "this passkey needs its prf output")
        raw = vault_keys.open_wrap(
            v.biometric_blob, cred.credential_id, _prf_bytes(body.prf), _server_key
        )
        if raw is None:
            vault_audit.record(vid, "unlock_failed", how="passkey")
            raise HTTPException(401, "passkey couldn't open the vault; unlock with your password")
        key = VaultKey(raw, v.verifier)
    vault_audit.record(vid, "unlocked", how="passkey")
    return {"token": _mint(key, vid, travel_safe=bool(v.travel_safe)), "vault_id": vid}


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
    with recovery_consistency_lock:
        _require_current_vault_password(db, pw, vid)
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
    key = _open_with_password(db, v, body.password)
    secret = _totp_map().get(vid)
    if not secret or not totp_verify(secret, body.code):
        vault_keys.failed(vid, v.verifier)
        vault_audit.record(vid, "unlock_failed", how="authenticator code")
        raise HTTPException(401, "wrong authenticator code")
    vault_audit.record(vid, "unlocked", how="password and authenticator code")
    return {
        "token": _mint(key, vid, travel_safe=bool(v.travel_safe)),
        "vault_id": vid,
    }


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
def twofa_unlock(body: TwoFaUnlock, request: Request, db: DbSession = Depends(get_db)):
    from services.webauthn import sign_count, verify_assertion

    _ensure_default(db)
    vid = body.vault_id or DEFAULT_VAULT
    v = db.get(Vault, vid)
    if not v:
        raise HTTPException(404, "no such vault")
    if _travel_on() and not v.travel_safe:
        raise HTTPException(403, "vault unavailable in travel mode")
    key = _open_with_password(db, v, body.password)
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
        cred.public_key,
        body.authenticator_data,
        body.client_data_json,
        body.signature,
        entry[1],
        _request_origin(request),
        previous_sign_count=cred.sign_count or 0,
    ):
        raise HTTPException(401, "assertion failed")
    cred.sign_count = max(cred.sign_count or 0, sign_count(body.authenticator_data))
    db.commit()
    vault_audit.record(vid, "unlocked", how="password and security key")
    return {
        "token": _mint(key, vid, travel_safe=bool(v.travel_safe)),
        "vault_id": vid,
    }


# ── activity log, encrypted export and import ─────────────────────────────────
@router.get("/vault/audit")
def vault_activity(db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    _key, vid = ctx
    names = dict(db.query(VaultEntry.id, VaultEntry.name).filter(VaultEntry.vault_id == vid).all())
    rows = vault_audit.recent(vid)
    for row in rows:
        if row.get("entry") in names:
            row["entry_name"] = names[row["entry"]]
    return rows


class ExportBody(BaseModel):
    vault_password: str
    export_password: str


@router.post("/vault/export")
def export_vault(body: ExportBody, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    """a password-protected copy of the open vault (bitwarden's "password protected" export).
    the vault password is asked again first; the file is sealed with its own Argon2id key."""
    from datetime import UTC, datetime

    from services.vault_export import seal

    key, vid = ctx
    _require_new_vault_password(body.export_password)
    with recovery_consistency_lock:
        v = _require_current_vault_password(db, key, vid)
        current = _open_with_password(db, v, body.vault_password, how="export")
        if current.key != key.key:
            raise HTTPException(403, "vault locked")
        rows = (
            db.query(VaultEntry)
            .filter(VaultEntry.vault_id == vid)
            .order_by(VaultEntry.created_at.asc())
            .all()
        )
        entries = []
        for e in rows:
            raw = decrypt(key, e.value_encrypted) if e.value_encrypted else "{}"
            try:
                fields = json.loads(raw)
                if not isinstance(fields, dict):
                    raise ValueError
            except (ValueError, TypeError):
                fields = {"password": raw}
            entries.append(
                {
                    "name": e.name,
                    "username": e.username or "",
                    "category": e.category or "general",
                    "type": e.type or "password",
                    "fields": fields,
                }
            )
        ids = [e.id for e in rows]
        left_out = (
            db.query(VaultAttachment).filter(VaultAttachment.entry_id.in_(ids)).count()
            if ids
            else 0
        )
    payload = {
        "vault": v.name,
        "exported_at": datetime.now(UTC).isoformat(),
        "entries": entries,
        "attachments_left_out": left_out,
    }
    vault_audit.record(vid, "exported", count=len(entries))
    return Response(
        seal(body.export_password, payload),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="alles-passwords.json"',
            "Cache-Control": "no-store",
        },
    )


class ImportBody(BaseModel):
    export_password: str
    file: str


@router.post("/vault/import")
def import_vault(body: ImportBody, db: DbSession = Depends(get_db), ctx: tuple = Depends(_ctx)):
    from services.vault_export import ExportError, open_sealed

    key, vid = ctx
    try:
        payload = open_sealed(body.export_password, body.file)
    except ExportError as exc:
        raise HTTPException(400, str(exc))
    added = 0
    with recovery_consistency_lock:
        _reserve_vault_write(db, key, vid)
        for item in payload.get("entries") or []:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            db.add(
                VaultEntry(
                    vault_id=vid,
                    name=str(item["name"]).strip()[:500],
                    username=str(item.get("username") or "")[:500],
                    value_encrypted=encrypt(key, json.dumps(fields)),
                    category=str(item.get("category") or "general")[:100],
                    type=str(item.get("type") or "password")[:100],
                )
            )
            added += 1
        db.commit()
    vault_audit.record(vid, "imported", count=added)
    return {"imported": added}


# ── retired browser-extension autofill compatibility route ────────────────────
@router.get("/vault/match")
def vault_match(x_vault_token: str | None = Header(None)):
    """Reject the legacy extension and revoke the exact broad token it pasted."""
    if x_vault_token:
        with recovery_consistency_lock:
            _unlock_tokens.pop(x_vault_token, None)
    raise HTTPException(
        status_code=410,
        detail=(
            "the old browser autofill extension was retired and its pasted token was revoked; "
            "remove or reload it and use Passwords in Alles to reveal and copy logins"
        ),
    )
