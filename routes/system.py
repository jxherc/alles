from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.api_errors import ApiError
from core.auth import require_auth, require_recent_owner
from core.build_info import runtime_info
from core.database import get_db
from core.server_config import access_profile
from core.settings import auth_enabled
from services import (
    audit,
    managed_companion_clients,
    managed_companions,
    managed_searxng,
    observability,
    server_policy,
    service_manager,
    sysmon,
)

router = APIRouter(prefix="/api/system")


class CompanionPreflightBody(BaseModel):
    bind: str = Field(min_length=2, max_length=64)
    ports: dict[str, int] = Field(default_factory=dict)


class CompanionActivationBody(CompanionPreflightBody):
    admin_username: str = Field(default="", max_length=240)
    admin_password: str = Field(default="", max_length=1024)
    confirmation: str = Field(min_length=1, max_length=80)


@router.get("/build", dependencies=[Depends(require_auth)])
def build():
    """Public release markers and read-only gates for unfinished UI."""
    return runtime_info()


@router.get("/stats")
def stats():
    """live cpu/ram/disk/gpu snapshot (sync → runs in the threadpool; the cpu
    sample blocks ~0.12s)."""
    return sysmon.snapshot()


@router.get("/health", dependencies=[Depends(require_auth)])
def runtime_health():
    return observability.runtime_health()


@router.get("/logs", dependencies=[Depends(require_auth)])
def logs(limit: int = Query(100, ge=1, le=500)):
    return {"entries": observability.read_recent_logs(limit), "limit": limit}


@router.get("/audit", dependencies=[Depends(require_auth)])
def audit_records(limit: int = Query(100, ge=1, le=500), db: DbSession = Depends(get_db)):
    return {"entries": audit.recent(db, limit), "limit": limit}


@router.get("/services", dependencies=[Depends(require_auth)])
def services():
    return {"services": service_manager.list_services()}


def _companion_error(exc: managed_companions.ManagedCompanionError) -> ApiError:
    return ApiError(409, "managed_companion_failed", str(exc))


def _companion_client_error(exc: managed_companion_clients.CompanionClientError) -> ApiError:
    return ApiError(409, "managed_companion_api_failed", str(exc))


@router.get("/companions", dependencies=[Depends(require_auth)])
def companion_statuses():
    return {"companions": managed_companions.statuses()}


@router.post("/companions/{service_id}/preflight", dependencies=[Depends(require_auth)])
def companion_preflight(service_id: str, body: CompanionPreflightBody):
    try:
        return managed_companions.preflight(service_id, bind=body.bind, ports=body.ports)
    except managed_companions.ManagedCompanionError as exc:
        raise _companion_error(exc) from exc


@router.post("/companions/{service_id}/prepare", dependencies=[Depends(require_recent_owner)])
def companion_prepare(service_id: str, request: Request):
    try:
        result = managed_companions.prepare(service_id)
    except managed_companions.ManagedCompanionError as exc:
        raise _companion_error(exc) from exc
    audit.record(
        action="service.companion.prepare",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"image": result["image"]},
    )
    return result


@router.post("/companions/{service_id}/activate", dependencies=[Depends(require_recent_owner)])
def companion_activate(service_id: str, body: CompanionActivationBody, request: Request):
    try:
        result = managed_companions.activate(
            service_id,
            bind=body.bind,
            ports=body.ports,
            admin_username=body.admin_username,
            admin_password=body.admin_password,
            confirmation=body.confirmation,
        )
    except managed_companions.ManagedCompanionError as exc:
        raise _companion_error(exc) from exc
    audit.record(
        action="service.companion.activate",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"bind": result.get("activation", {}).get("bind"), "ports": result.get("activation", {}).get("ports", {})},
    )
    return result


@router.post("/companions/{service_id}/rollback", dependencies=[Depends(require_recent_owner)])
def companion_rollback(service_id: str, request: Request):
    try:
        result = managed_companions.rollback(service_id)
    except managed_companions.ManagedCompanionError as exc:
        raise _companion_error(exc) from exc
    audit.record(
        action="service.companion.rollback",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"kept_data": True},
    )
    return result


@router.post("/companions/{service_id}/uninstall", dependencies=[Depends(require_recent_owner)])
def companion_uninstall(service_id: str, request: Request):
    try:
        result = managed_companions.uninstall_keep_data(service_id)
    except managed_companions.ManagedCompanionError as exc:
        raise _companion_error(exc) from exc
    audit.record(
        action="service.companion.uninstall",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"kept_data": True},
    )
    return result


class AdGuardFilteringBody(BaseModel):
    enabled: bool
    interval: int = Field(default=24, ge=0, le=168)


class AdGuardRewriteBody(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    answer: str = Field(min_length=1, max_length=253)
    enabled: bool = True


class NpmConnectBody(BaseModel):
    identity: str = Field(min_length=1, max_length=320)
    secret: str = Field(min_length=1, max_length=1024)


class NpmProxyHostBody(BaseModel):
    domain_names: list[str] = Field(min_length=1, max_length=20)
    forward_scheme: Literal["http", "https"] = "http"
    forward_host: str = Field(min_length=1, max_length=253)
    forward_port: int = Field(ge=1, le=65535)
    certificate_id: int = Field(default=0, ge=0)
    ssl_forced: bool = False


@router.get("/companions/adguard-home/dashboard", dependencies=[Depends(require_auth)])
def companion_adguard_dashboard():
    try:
        return managed_companion_clients.adguard_dashboard()
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc


@router.put(
    "/companions/adguard-home/filtering", dependencies=[Depends(require_recent_owner)]
)
def companion_adguard_filtering(body: AdGuardFilteringBody, request: Request):
    try:
        result = managed_companion_clients.set_adguard_filtering(body.enabled, body.interval)
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc
    audit.record(
        action="service.companion.adguard.filtering",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target="adguard-home",
        details={"enabled": body.enabled, "interval": body.interval},
    )
    return result


@router.post(
    "/companions/adguard-home/rewrites/{action}",
    dependencies=[Depends(require_recent_owner)],
)
def companion_adguard_rewrite(
    action: Literal["add", "delete"], body: AdGuardRewriteBody, request: Request
):
    try:
        result = managed_companion_clients.change_adguard_rewrite(
            action, body.domain, body.answer, enabled=body.enabled
        )
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc
    audit.record(
        action=f"service.companion.adguard.rewrite.{action}",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=body.domain,
        details={"service_id": "adguard-home"},
    )
    return result


@router.get(
    "/companions/nginx-proxy-manager/dashboard", dependencies=[Depends(require_auth)]
)
def companion_npm_dashboard():
    try:
        return managed_companion_clients.npm_dashboard()
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc


@router.post(
    "/companions/nginx-proxy-manager/connect",
    dependencies=[Depends(require_recent_owner)],
)
def companion_npm_connect(body: NpmConnectBody, request: Request):
    try:
        result = managed_companion_clients.connect_npm(body.identity, body.secret)
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc
    audit.record(
        action="service.companion.npm.connect",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target="nginx-proxy-manager",
        details={"identity": body.identity},
    )
    return result


@router.post(
    "/companions/nginx-proxy-manager/disconnect",
    dependencies=[Depends(require_recent_owner)],
)
def companion_npm_disconnect(request: Request):
    try:
        managed_companion_clients.clear_credentials("nginx-proxy-manager")
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc
    audit.record(
        action="service.companion.npm.disconnect",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target="nginx-proxy-manager",
        details={},
    )
    return {"ok": True, "connected": False}


@router.post(
    "/companions/nginx-proxy-manager/proxy-hosts",
    dependencies=[Depends(require_recent_owner)],
)
def companion_npm_proxy_host(body: NpmProxyHostBody, request: Request):
    try:
        result = managed_companion_clients.create_npm_proxy_host(
            domain_names=body.domain_names,
            forward_scheme=body.forward_scheme,
            forward_host=body.forward_host,
            forward_port=body.forward_port,
            certificate_id=body.certificate_id,
            ssl_forced=body.ssl_forced,
        )
    except managed_companion_clients.CompanionClientError as exc:
        raise _companion_client_error(exc) from exc
    audit.record(
        action="service.companion.npm.proxy_host.create",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=",".join(body.domain_names),
        details={
            "forward_scheme": body.forward_scheme,
            "forward_host": body.forward_host,
            "forward_port": body.forward_port,
        },
    )
    return result


class ServerPolicyBody(BaseModel):
    policy: str = Field(min_length=2, max_length=32_768)
    confirmation: str = Field(default="", max_length=80)


def _policy_error(exc: server_policy.ServerPolicyError) -> ApiError:
    return ApiError(409, exc.code, str(exc))


def _local_device_owner(request: Request) -> None:
    host = request.client.host if request.client else ""
    if not server_policy.is_loopback_client(host):
        raise ApiError(403, "loopback_required", "host control can be widened only from loopback")
    if access_profile() != "device":
        raise ApiError(
            403, "device_profile_required", "host control can be widened only in device mode"
        )
    if not auth_enabled():
        raise ApiError(
            403,
            "owner_password_required",
            "enable an owner password and reauthenticate before widening host control",
        )


@router.get("/policy", dependencies=[Depends(require_auth)])
def get_server_policy(request: Request):
    result = server_policy.read()
    host = request.client.host if request.client else ""
    result["local_device"] = bool(
        server_policy.is_loopback_client(host) and access_profile() == "device"
    )
    result["confirmation_phrase"] = server_policy.CONFIRMATION_PHRASE
    return result


@router.post("/policy/validate", dependencies=[Depends(require_auth)])
def validate_server_policy(body: ServerPolicyBody):
    try:
        return {"valid": True, **server_policy.diff(body.policy)}
    except server_policy.ServerPolicyError as exc:
        raise _policy_error(exc) from exc


@router.post("/policy/diff", dependencies=[Depends(require_auth)])
def diff_server_policy(body: ServerPolicyBody):
    try:
        return server_policy.diff(body.policy)
    except server_policy.ServerPolicyError as exc:
        raise _policy_error(exc) from exc


@router.put("/policy", dependencies=[Depends(require_recent_owner)])
def save_server_policy(body: ServerPolicyBody, request: Request):
    actor = observability.actor_kind(dict(request.scope.get("headers") or []))
    try:
        candidate = server_policy.validate_text(body.policy)
        if candidate["control_mode"] == "allowlisted_host":
            _local_device_owner(request)
            if body.confirmation != server_policy.CONFIRMATION_PHRASE:
                raise ApiError(409, "confirmation_required", "typed confirmation does not match")
        result = server_policy.save(body.policy)
    except server_policy.ServerPolicyError as exc:
        audit.record(
            action="server.policy.save",
            outcome="failed",
            actor=actor,
            target="server-policy.json",
            details={"error_code": exc.code},
        )
        raise _policy_error(exc) from exc
    except ApiError as exc:
        audit.record(
            action="server.policy.save",
            outcome="failed",
            actor=actor,
            target="server-policy.json",
            details={"error_code": exc.code},
        )
        raise
    audit.record(
        action="server.policy.save",
        outcome="success",
        actor=actor,
        target="server-policy.json",
        details={
            "control_mode": result["policy"]["control_mode"],
            "host_service_count": len(result["policy"]["host_services"]),
        },
    )
    return result


@router.get("/host-services", dependencies=[Depends(require_auth)])
def host_services():
    current = server_policy.read()
    return {
        "control_mode": current["policy"]["control_mode"],
        "policy_valid": current["valid"],
        "services": current["policy"]["host_services"]
        if current["valid"] and current["policy"]["control_mode"] == "allowlisted_host"
        else [],
    }


@router.post(
    "/host-services/{manager}/{service_id}/{action}",
    dependencies=[Depends(require_recent_owner)],
)
def control_host_service(
    manager: Literal["launchd", "systemd"],
    service_id: str,
    action: Literal["start", "stop", "restart"],
    request: Request,
):
    _local_device_owner(request)
    actor = observability.actor_kind(dict(request.scope.get("headers") or []))
    try:
        result = server_policy.control_host_service(manager, service_id, action)
    except server_policy.ServerPolicyError as exc:
        audit.record(
            action=f"server.host_service.{action}",
            outcome="failed",
            actor=actor,
            target=f"{manager}:{service_id}",
            details={"error_code": exc.code},
        )
        raise _policy_error(exc) from exc
    audit.record(
        action=f"server.host_service.{action}",
        outcome="success",
        actor=actor,
        target=f"{manager}:{service_id}",
        details={"manager": manager},
    )
    return result


@router.get("/searxng", dependencies=[Depends(require_auth)])
def searxng_status():
    return managed_searxng.status()


@router.post("/searxng/{action}", dependencies=[Depends(require_recent_owner)])
def manage_searxng(
    action: Literal[
        "install", "start", "stop", "restart", "update", "rollback", "uninstall", "test"
    ],
    request: Request,
):
    try:
        if action == "install":
            result = managed_searxng.install()
        elif action in {"start", "stop", "restart"}:
            result = managed_searxng.control(action)
        elif action == "update":
            result = managed_searxng.update()
        elif action == "rollback":
            result = managed_searxng.rollback()
        elif action == "uninstall":
            result = managed_searxng.uninstall_keep_data()
        else:
            result = managed_searxng.json_search("alles self hosted search")
    except managed_searxng.ManagedSearxngRollback as exc:
        raise ApiError(409, "searxng_update_rolled_back", str(exc)) from exc
    except managed_searxng.ManagedSearxngError as exc:
        raise ApiError(409, "searxng_manage_failed", str(exc)) from exc
    audit.record(
        action=f"service.searxng.{action}",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target="searxng",
        details={"manager": "owned_compose"},
    )
    return result


@router.post("/services/{service_id}/{action}", dependencies=[Depends(require_recent_owner)])
def control_service(
    service_id: str,
    action: Literal["start", "stop", "restart"],
    request: Request,
):
    try:
        result = service_manager.control(service_id, action)
    except service_manager.ServiceOwnershipError as exc:
        raise ApiError(409, "service_not_owned", str(exc)) from exc
    except service_manager.ServiceControlError as exc:
        raise ApiError(409, "service_control_failed", str(exc)) from exc
    audit.record(
        action=f"service.{action}",
        outcome="success",
        actor=observability.actor_kind(dict(request.scope.get("headers") or [])),
        target=service_id,
        details={"manager": "owned_service"},
    )
    return result
