import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.settings import (
    DEFAULT_CHAT_BEHAVIORS,
    OWNER_INSTRUCTIONS_MAX_CHARS,
    load_settings,
    save_settings,
)
from services.redaction import redact_url

router = APIRouter(prefix="/api")


_SECRET_KEYS = {
    "auth_password_hash",
    "vault_verifier",
    "vault_pw_b64",
    "vault_biometric_key",
    "vault_2fa_totp",
    "journal_passcode",
    "mail_oauth_client_secret",
    "openai_api_key",
    "tavily_api_key",
    "brave_api_key",
    "google_pse_api_key",
    "serper_api_key",
    "notify_discord_webhook",
    "notify_telegram_token",
    "notify_telegram_chat_id",
}
_CONFIG_FLAGS = {
    "mail_oauth_client_secret",
    "openai_api_key",
    "tavily_api_key",
    "brave_api_key",
    "google_pse_api_key",
    "serper_api_key",
    "notify_discord_webhook",
    "notify_telegram_token",
    "notify_telegram_chat_id",
}


def _public_settings(s: dict) -> dict:
    out = {}
    for k, v in s.items():
        if k in _SECRET_KEYS:
            if k in _CONFIG_FLAGS:
                out[f"{k}_configured"] = bool(v)
            continue
        if k in {"outbound_proxy", "searxng_url"} and isinstance(v, str):
            out[k] = redact_url(v)
            continue
        out[k] = v
    return out


@router.get("/settings")
def get_settings():
    return _public_settings(load_settings())


@router.get("/settings/localization/options")
def get_localization_options():
    from services.localization import localization_options

    return localization_options()


@router.get("/credits")
def get_credits():
    from services.credits import load_credits_manifest

    return load_credits_manifest()


@router.get("/credits/{entry_id}")
def get_credit_detail(entry_id: str):
    from services.credits import load_credit_detail

    try:
        return load_credit_detail(entry_id)
    except KeyError as exc:
        raise ApiError(404, "credit_not_found", "credit entry not found") from exc


@router.get("/vault-location")
def vault_location(path: str = ""):
    """resolved vault folder + an obsidian deep-link. with ?path=<rel>, the link opens that
    specific note in Obsidian; without it, the vault folder."""
    from urllib.parse import quote

    from services import vault_md

    base = str(vault_md.vault_dir())
    target = base
    if path:
        try:
            target = str(vault_md._safe(path))  # abs file path, traversal-guarded
        except ValueError:
            target = base
    return {"path": base, "obsidian": "obsidian://open?path=" + quote(target)}


class VaultTransferPath(BaseModel):
    destination: str


class VaultTransferDelete(BaseModel):
    confirmation: str


class VaultImportBody(BaseModel):
    source: str
    name: str
    workflow: Literal["keep", "copy", "move"] = "keep"


def _run_vault_transfer(operation):
    from services import vault_transfer

    try:
        return operation()
    except ValueError as exc:
        raise ApiError(400, "invalid_vault_transfer", str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError(
            404, "vault_location_missing", "the selected vault folder is missing"
        ) from exc
    except FileExistsError as exc:
        raise ApiError(
            409, "vault_destination_exists", "choose a new empty destination path"
        ) from exc
    except vault_transfer.InsufficientSpace as exc:
        raise ApiError(507, "vault_transfer_no_space", str(exc)) from exc
    except PermissionError as exc:
        raise ApiError(
            403, "vault_transfer_permission_denied", "vault transfer permission was denied"
        ) from exc
    except vault_transfer.TransferConflict as exc:
        raise ApiError(409, "vault_transfer_conflict", str(exc)) from exc
    except OSError as exc:
        raise ApiError(
            500,
            "vault_transfer_failed",
            "vault transfer stopped safely before deleting the old location",
        ) from exc


def _reindex_after_vault_switch() -> None:
    try:
        from core.database import SessionLocal
        from routes.textindex import _collect_docs
        from services import personal_index, textindex

        db = SessionLocal()
        try:
            personal_index.reindex_source(db, "note")
            textindex.reindex_kind(db, "doc", _collect_docs())
        finally:
            db.close()
    except Exception as exc:
        raise ApiError(
            500,
            "vault_reindex_failed",
            "the vault location changed, but search indexing failed; retry this recovery action",
        ) from exc


@router.get("/vault-transfer/pending")
def pending_vault_transfers():
    from services import vault_transfer

    return {
        "transfers": [
            vault_transfer.public_status(item) for item in vault_transfer.pending_transfers()
        ]
    }


@router.get("/vault-transfer/{operation_id}")
def vault_transfer_status(operation_id: str):
    from services import vault_transfer

    manifest = _run_vault_transfer(lambda: vault_transfer.transfer_status(operation_id))
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/move")
def prepare_vault_move(body: VaultTransferPath, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    manifest = _run_vault_transfer(lambda: vault_transfer.prepare_vault_move(body.destination))
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/relink")
def prepare_vault_relink(body: VaultTransferPath, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    manifest = _run_vault_transfer(lambda: vault_transfer.prepare_vault_relink(body.destination))
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/import/preview")
def preview_vault_import(body: VaultImportBody, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    if body.workflow == "keep":
        source = Path(body.source).expanduser().resolve(strict=False)
        if not source.is_dir():
            raise ApiError(404, "vault_location_missing", "the selected vault folder is missing")
        inventory = _run_vault_transfer(lambda: vault_transfer._inventory(source))
        return {
            "source": str(source),
            "destination": str(source),
            "source_files": len(inventory["files"]),
            "source_bytes": inventory["total_size"],
            "required_bytes": 0,
            "available_bytes": 0,
            "conflicts": [],
            "can_import": True,
            "links_preserved": True,
        }
    return _run_vault_transfer(
        lambda: vault_transfer.preview_external_vault(body.source, body.name)
    )


@router.post("/vault-transfer/import")
def apply_vault_import(body: VaultImportBody, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    if body.workflow == "keep":
        manifest = _run_vault_transfer(lambda: vault_transfer.relink_vault(body.source))
    else:
        manifest = _run_vault_transfer(
            lambda: vault_transfer.import_external_vault(
                body.source,
                body.name,
                move=body.workflow == "move",
            )
        )
    _reindex_after_vault_switch()
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/{operation_id}/resume")
def resume_vault_transfer(operation_id: str, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    manifest = _run_vault_transfer(lambda: vault_transfer.resume_vault_transfer(operation_id))
    _reindex_after_vault_switch()
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/{operation_id}/rollback")
def rollback_vault_transfer(operation_id: str, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    manifest = _run_vault_transfer(lambda: vault_transfer.rollback_vault_transfer(operation_id))
    _reindex_after_vault_switch()
    return vault_transfer.public_status(manifest)


@router.post("/vault-transfer/{operation_id}/delete-old")
def delete_old_vault(operation_id: str, body: VaultTransferDelete, request: Request):
    from services import vault_transfer

    require_recent_owner(request)
    manifest = _run_vault_transfer(
        lambda: vault_transfer.delete_old_vault(operation_id, body.confirmation)
    )
    return vault_transfer.public_status(manifest)


@router.get("/download/obsidian-plugin")
def download_obsidian_plugin():
    """zip the bundled Obsidian companion plugin → drop into your vault's .obsidian/plugins/."""
    import io
    import zipfile
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "static" / "plugins" / "obsidian-alles"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, f"alles/{f.relative_to(root).as_posix()}")
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="obsidian-alles-plugin.zip"'},
    )


class SettingsPatch(BaseModel):
    default_model: str | None = None
    default_endpoint_id: str | None = None
    model_roles: dict | None = None
    system_prompt: str | None = None
    owner_instructions: str | None = None
    default_chat_behavior: str | None = None
    context_limit: int | None = None
    stream_thinking: bool | None = None
    artifacts_enabled: bool | None = None
    agent_max_turns: int | None = None
    agent_max_tokens: int | None = None
    agent_permission_mode: str | None = None
    agent_allowed_roots: list[str] | None = None
    agent_context_files: bool | None = None
    agent_sandbox: bool | None = None
    agent_computer_use: bool | None = None
    agent_subagents: bool | None = None
    permission_rules: list | None = None
    auto_compact: bool | None = None
    compact_threshold: int | None = None
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    openai_api_key: str | None = None
    search_provider: str | None = None
    search_result_count: int | None = None
    search_fallback_chain: list[str] | None = None
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    searxng_url: str | None = None
    google_pse_api_key: str | None = None
    google_pse_cx: str | None = None
    serper_api_key: str | None = None
    search_fallback: str | None = None
    andromeda_normal_results: bool | None = None
    andromeda_overview: bool | None = None
    andromeda_model_band: str | None = None
    andromeda_model_bands: dict | None = None
    andromeda_qualified_models: list[str] | None = None
    andromeda_answer_max_tokens: int | None = None
    andromeda_answer_timeout_seconds: int | None = None
    andromeda_verification_enabled: bool | None = None
    andromeda_verifier_mode: str | None = None
    andromeda_verifier_max_tokens: int | None = None
    andromeda_verifier_timeout_seconds: int | None = None
    memory_auto_inject: bool | None = None
    memory_policy: str | None = None
    tts_speed: float | None = None
    tts_auto_play: bool | None = None
    stt_language: str | None = None
    language: str | None = None
    region: str | None = None
    timezone: str | None = None
    clock_format: str | None = None
    week_start: str | None = None
    currency: str | None = None
    theme: str | None = None  # '' (dark/default) | 'light' — synced across subdomains
    accent: str | None = None  # hex like '#818cf8', or '' for the default
    notify_discord_webhook: str | None = None
    notify_telegram_token: str | None = None
    notify_telegram_chat_id: str | None = None
    notify_on_agent_done: bool | None = None
    outbound_proxy: str | None = None  # e.g. http://127.0.0.1:7890 — routes all egress through it
    prefer_local_models: bool | None = None  # fallback to a local (ollama) endpoint when available
    username: str | None = None  # display name, synced across subdomains
    # ── per-app settings ──
    vault_dir: str | None = None  # markdown vault folder — point at an Obsidian vault
    files_dir: str | None = None  # files app root directory
    photos_dir: str | None = None  # gallery library folder
    photos_watch_folder: str | None = None  # 7c phone-backup watch folder
    cal_default_view: str | None = None  # 'month' | 'week'
    cal_week_start: str | None = None  # 'sun' | 'mon'
    cal_default_duration_min: int | None = None  # 8a default event length
    cal_work_start: int | None = None  # 8a working-hours shading start (hour 0-23)
    cal_work_end: int | None = None  # 8a working-hours shading end (hour 0-23)
    cal_secondary_tz: str | None = None  # 8a secondary timezone (IANA name)
    system_refresh: int | None = None  # system monitor poll interval (ms)
    mail_poll_seconds: int | None = None  # mail background check interval
    mail_signature: str | None = None  # appended/prefilled when composing
    mail_threads: str | None = None  # group mail by conversation
    docs_ai_model: str | None = None  # model for docs AI edits
    journal_mirror_vault: bool | None = None  # mirror journal entries to Journal/ daily notes
    # personal recall index toggles
    pidx_enabled: bool | None = None
    pidx_mail: bool | None = None
    pidx_note: bool | None = None
    pidx_journal: bool | None = None
    pidx_contact: bool | None = None
    pidx_read: bool | None = None
    pidx_book: bool | None = None
    # proactive agent
    pidx_proactive_enabled: bool | None = None
    pidx_proactive_every_hours: int | None = None
    pidx_proactive_quiet_start: int | None = None
    pidx_proactive_quiet_end: int | None = None
    pidx_proactive_channel: str | None = None
    pidx_proactive_push_min: int | None = None
    proactive_model: str | None = None
    pidx_proactive_min_urgency: int | None = None
    pidx_proactive_max_tokens: int | None = None
    pidx_proactive_cat_task: bool | None = None
    pidx_proactive_cat_sub: bool | None = None
    pidx_proactive_cat_event: bool | None = None
    pidx_proactive_cat_habit: bool | None = None
    pidx_proactive_cat_read: bool | None = None
    pidx_proactive_cat_health: bool | None = None
    pidx_proactive_cat_money: bool | None = None
    pidx_proactive_cat_mail: bool | None = None
    pidx_proactive_cat_journal: bool | None = None
    pidx_proactive_synthesis: bool | None = None
    user_model_distill: bool | None = None
    session_context_inject: bool | None = None
    insights_enabled: bool | None = None
    intent_suggestions: bool | None = None
    insights_auto_inject: bool | None = None
    distilled_auto_inject: bool | None = None
    holdings_autoprice: bool | None = None
    tax_reminders: bool | None = None
    tax_setaside_rate: float | None = None
    extra_clip_search: bool | None = None
    extra_ocr: bool | None = None
    extra_eventkit: bool | None = None
    extra_keychain: bool | None = None
    mail_oauth_client_id: str | None = None
    mail_oauth_client_secret: str | None = None
    mail_oauth_redirect_base: str | None = None


@router.patch("/settings")
def patch_settings(body: SettingsPatch, request: Request):
    values = body.model_dump()
    if "currency" in body.model_fields_set and values["currency"] is None:
        raise ApiError(400, "invalid_currency", "currency must be a supported ISO 4217 code")
    patch = {k: v for k, v in values.items() if v is not None}
    if (
        "default_chat_behavior" in patch
        and patch["default_chat_behavior"] not in DEFAULT_CHAT_BEHAVIORS
    ):
        raise ApiError(
            400,
            "invalid_default_chat_behavior",
            "default chat behavior must be automatic_tools or answer_only",
        )
    for key in ("owner_instructions", "system_prompt"):
        if key not in patch:
            continue
        patch[key] = patch[key].strip()
        if len(patch[key]) > OWNER_INSTRUCTIONS_MAX_CHARS:
            raise ApiError(
                400,
                "owner_instructions_too_long",
                f"owner instructions must be at most {OWNER_INSTRUCTIONS_MAX_CHARS} characters",
            )
    if "agent_allowed_roots" in patch:
        require_recent_owner(request)
        roots = patch["agent_allowed_roots"]
        if len(roots) > 16:
            raise ApiError(400, "invalid_agent_root", "at most 16 extra roots are allowed")
        normalized = []
        for value in roots:
            path = Path(str(value)).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise ApiError(400, "invalid_agent_root", "approved roots must be existing folders")
            resolved = path.resolve()
            if resolved == Path(resolved.anchor):
                raise ApiError(400, "invalid_agent_root", "the filesystem root cannot be approved")
            text = str(resolved)
            if text not in normalized:
                normalized.append(text)
        patch["agent_allowed_roots"] = normalized
    if "language" in patch:
        from services.localization import normalize_language

        try:
            patch["language"] = normalize_language(patch["language"])
        except ValueError as exc:
            raise ApiError(
                400,
                "unsupported_language",
                "the selected language has not passed every release gate",
            ) from exc
    if "clock_format" in patch and patch["clock_format"] not in {"auto", "12", "24"}:
        raise ApiError(
            400, "invalid_clock_format", "clock format must be automatic, 12 hour, or 24 hour"
        )
    if "week_start" in patch and patch["week_start"] not in {"auto", "mon", "sun"}:
        raise ApiError(400, "invalid_week_start", "week start must be automatic, monday, or sunday")
    if "currency" in patch:
        if not isinstance(patch["currency"], str):
            raise ApiError(400, "invalid_currency", "currency must be a supported ISO 4217 code")
        patch["currency"] = patch["currency"].strip().upper()
        if patch["currency"]:
            from services.localization import CURRENCY_OPTIONS

            supported = {item["value"] for item in CURRENCY_OPTIONS if item["value"]}
            if patch["currency"] not in supported:
                raise ApiError(
                    400, "invalid_currency", "currency must be a supported ISO 4217 code"
                )
    if "region" in patch:
        patch["region"] = patch["region"].strip().upper()
        if patch["region"] and not re.fullmatch(r"(?:[A-Z]{2}|[0-9]{3})", patch["region"]):
            raise ApiError(400, "invalid_region", "region must be a two-letter or three-digit code")
    if "timezone" in patch:
        patch["timezone"] = patch["timezone"].strip()
        if patch["timezone"]:
            try:
                ZoneInfo(patch["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ApiError(
                    400, "invalid_timezone", "timezone must be a valid IANA name"
                ) from exc
    if "memory_policy" in patch and patch["memory_policy"] not in {"off", "ask", "auto"}:
        raise ApiError(400, "invalid_memory_policy", "memory policy must be off, ask, or auto")
    if "andromeda_model_band" in patch:
        from services.andromeda import normalize_band

        try:
            patch["andromeda_model_band"] = normalize_band(patch["andromeda_model_band"])
        except ValueError as exc:
            raise ApiError(
                400, str(exc), "model band must be light, standard, strong, or auto"
            ) from exc
    if "andromeda_model_bands" in patch:
        from services.andromeda import MODEL_BANDS

        value = patch["andromeda_model_bands"]
        if set(value) - set(MODEL_BANDS):
            raise ApiError(400, "invalid_model_band", "unknown Andromeda model band")
        clean = {}
        for band, choice in value.items():
            if not isinstance(choice, dict) or set(choice) - {"endpoint_id", "model"}:
                raise ApiError(
                    400, "invalid_model_choice", "model choices need endpoint_id and model"
                )
            endpoint_id = str(choice.get("endpoint_id") or "").strip()[:100]
            model = str(choice.get("model") or "").strip()[:300]
            if bool(endpoint_id) != bool(model):
                raise ApiError(400, "invalid_model_choice", "choose both an endpoint and model")
            clean[band] = {"endpoint_id": endpoint_id, "model": model}
        patch["andromeda_model_bands"] = clean
    if "andromeda_qualified_models" in patch:
        values = patch["andromeda_qualified_models"]
        if len(values) > 30 or any(
            not isinstance(value, str) or len(value) > 420 for value in values
        ):
            raise ApiError(400, "invalid_qualified_models", "qualified models are invalid")
        patch["andromeda_qualified_models"] = list(
            dict.fromkeys(value.strip() for value in values if value.strip())
        )
    if "andromeda_verifier_mode" in patch and patch["andromeda_verifier_mode"] not in {
        "freshness-sensitive",
        "always",
        "manual",
        "off",
    }:
        raise ApiError(
            400,
            "invalid_verifier_mode",
            "verifier mode must be freshness-sensitive, always, manual, or off",
        )
    for field, minimum, maximum in (
        ("andromeda_answer_max_tokens", 100, 2_000),
        ("andromeda_answer_timeout_seconds", 5, 120),
        ("andromeda_verifier_max_tokens", 100, 2_000),
        ("andromeda_verifier_timeout_seconds", 5, 120),
    ):
        if field in patch and not minimum <= patch[field] <= maximum:
            raise ApiError(
                400,
                "invalid_andromeda_limit",
                f"{field} must be between {minimum} and {maximum}",
            )
    if "searxng_url" in patch:
        from services.managed_searxng import managed_url

        value = patch["searxng_url"].strip().rstrip("/")
        if value and value != managed_url():
            try:
                parsed = urlsplit(value)
            except ValueError as exc:
                raise ApiError(
                    400, "invalid_searxng_url", "external SearXNG needs a valid HTTPS URL"
                ) from exc
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ApiError(
                    400, "invalid_searxng_url", "external SearXNG needs a valid HTTPS URL"
                )
        patch["searxng_url"] = value
    if "model_roles" in patch:
        from services.model_resolver import normalize_model_roles

        try:
            patch["model_roles"] = normalize_model_roles(patch["model_roles"])
        except ValueError as exc:
            raise ApiError(400, "invalid_model_roles", str(exc)) from exc
    old_photos = load_settings().get("photos_dir") if "photos_dir" in patch else None
    out = save_settings(patch)
    if "photos_dir" in patch:
        # the library is indexed by bare filename → carry the files to the new folder
        try:
            from services import photos_store

            photos_store.relocate(old_photos)
        except Exception:
            pass
    if "outbound_proxy" in patch:
        try:
            from services import net

            net.apply_proxy()  # take effect without a restart
        except Exception:
            pass
    if "vault_dir" in patch:
        # pointed at a different (e.g. Obsidian) vault → rebuild the note index from it
        try:
            from core.database import SessionLocal
            from services import personal_index

            db = SessionLocal()
            try:
                personal_index.reindex_source(db, "note")
            finally:
                db.close()
        except Exception:
            pass
    if "journal_mirror_vault" in patch:
        # toggled on → backfill existing entries to the vault; off → drop the mirror files
        try:
            from services import journal_vault

            if patch["journal_mirror_vault"] and not load_settings().get("journal_passcode"):
                journal_vault.backfill()
            else:
                journal_vault.purge()
        except Exception:
            pass
    return _public_settings(out)
