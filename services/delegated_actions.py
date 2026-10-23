"""One durable permission gate for Aide, Jarvis, and tool-origin actions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from core.database import (
    CapabilityGrant,
    CapabilityGrantEvent,
    DelegatedAction,
    JarvisRun,
    JarvisRunPrompt,
    JarvisWorkflow,
    Project,
    Session,
)
from services.jarvis_store import append_event, create_prompt, json_value, transition_run
from services.project_environment import canonical_folder

SCOPE_KINDS = {"general", "project", "workflow"}
ORIGINS = {"aide", "jarvis", "tool"}
ACCESS_MODES = {"read", "manage"}
ADMIN_CAPABILITIES = {"capability.grant", "capability.approve", "capability.revoke"}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _bounded(value, limit: int) -> str:
    return str(value or "")[:limit]


def hash_arguments(arguments: dict | None) -> str:
    encoded = json.dumps(
        arguments or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class ActionRequest:
    origin: str
    scope_kind: str
    scope_id: str
    capability: str
    action: str
    target: str = ""
    data_summary: str = ""
    privacy_effect: str = ""
    cost: str = ""
    arguments_hash: str = ""
    mutating: bool = True
    target_is_path: bool = False
    path_targets: tuple[str, ...] = ()
    run_id: str | None = None
    agent_run_id: str | None = None
    session_id: str | None = None

    def exact_hash(self) -> str:
        payload = {
            "origin": self.origin,
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
            "capability": self.capability,
            "action": self.action,
            "target": self.target,
            "data_summary": self.data_summary,
            "privacy_effect": self.privacy_effect,
            "cost": self.cost,
            "arguments_hash": self.arguments_hash,
            "mutating": self.mutating,
            "target_is_path": self.target_is_path,
            "path_targets": list(self.path_targets),
            "run_id": self.run_id or "",
            "session_id": self.session_id or "",
        }
        return hash_arguments(payload)


def _event(
    db: DbSession,
    kind: str,
    *,
    grant: CapabilityGrant | None = None,
    action: DelegatedAction | None = None,
    actor: str = "system",
) -> CapabilityGrantEvent:
    row = CapabilityGrantEvent(
        grant_id=grant.id if grant else (action.grant_id if action else None),
        action_id=action.id if action else None,
        kind=kind,
        actor=_bounded(actor, 32),
        scope_kind=_bounded(
            grant.scope_kind if grant else (action.scope_kind if action else ""), 32
        ),
        scope_id=_bounded(grant.scope_id if grant else (action.scope_id if action else ""), 64),
        capability=_bounded(
            grant.capability if grant else (action.capability if action else ""), 128
        ),
    )
    db.add(row)
    return row


def _validate_scope(db: DbSession, scope_kind: str, scope_id: str, capability: str) -> None:
    if scope_kind not in SCOPE_KINDS:
        raise ValueError("invalid_grant_scope")
    if not capability or len(capability) > 128:
        raise ValueError("invalid_capability")
    if scope_kind == "general":
        if scope_id:
            raise ValueError("general_scope_has_no_id")
        return
    if not scope_id:
        raise ValueError("grant_scope_id_required")
    if scope_kind == "project":
        if not db.get(Project, scope_id):
            raise ValueError("project_not_found")
        return
    workflow = db.get(JarvisWorkflow, scope_id)
    if not workflow:
        raise ValueError("workflow_not_found")
    ceiling = set(json_value(workflow.capability_ceiling, list))
    if capability not in ceiling:
        raise ValueError("capability_exceeds_workflow_ceiling")


def canonical_target_root(value: str) -> str:
    return canonical_folder(value, must_exist=True) if str(value or "").strip() else ""


def create_grant(
    db: DbSession,
    *,
    scope_kind: str,
    scope_id: str,
    capability: str,
    target_root: str = "",
    access_mode: str = "read",
    expires_at: datetime | None = None,
) -> CapabilityGrant:
    scope_id = str(scope_id or "")
    capability = str(capability or "").strip()
    _validate_scope(db, scope_kind, scope_id, capability)
    if access_mode not in ACCESS_MODES:
        raise ValueError("invalid_grant_access")
    if expires_at and expires_at <= utc_now():
        raise ValueError("grant_expiry_must_be_future")
    root = canonical_target_root(target_root)
    row = CapabilityGrant(
        scope_kind=scope_kind,
        scope_id=scope_id,
        capability=capability,
        target_root=root,
        access_mode=access_mode,
        state="active",
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    _event(db, "grant_created", grant=row, actor="owner")
    return row


def revoke_grant(db: DbSession, grant: CapabilityGrant) -> CapabilityGrant:
    now = utc_now()
    changed = (
        db.query(CapabilityGrant)
        .filter_by(id=grant.id, state="active")
        .update(
            {CapabilityGrant.state: "revoked", CapabilityGrant.revoked_at: now},
            synchronize_session=False,
        )
    )
    if changed == 1:
        db.flush()
        db.refresh(grant)
        _event(db, "grant_revoked", grant=grant, actor="owner")
    return grant


def _within(target: str, root: str) -> bool:
    try:
        Path(target).expanduser().resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _active_grant(db: DbSession, request: ActionRequest, now: datetime) -> CapabilityGrant | None:
    grants = (
        db.query(CapabilityGrant)
        .filter_by(
            scope_kind=request.scope_kind,
            scope_id=request.scope_id,
            capability=request.capability,
            state="active",
        )
        .order_by(CapabilityGrant.created_at.desc())
        .all()
    )
    for grant in grants:
        if grant.expires_at and grant.expires_at <= now:
            grant.state = "expired"
            _event(db, "grant_expired", grant=grant)
            continue
        if request.mutating and grant.access_mode != "manage":
            continue
        if request.target_is_path:
            targets = request.path_targets or (request.target,)
            if not grant.target_root or not all(
                _within(target, grant.target_root) for target in targets
            ):
                continue
        elif grant.target_root:
            continue
        return grant
    return None


def matching_grant(db: DbSession, request: ActionRequest) -> CapabilityGrant | None:
    _validate_request(db, request)
    return _active_grant(db, request, utc_now())


def _validate_request(db: DbSession, request: ActionRequest) -> None:
    if request.origin not in ORIGINS:
        raise ValueError("invalid_action_origin")
    if request.capability in ADMIN_CAPABILITIES or request.action.startswith("grant."):
        raise ValueError("delegated_grant_management_forbidden")
    _validate_scope(db, request.scope_kind, request.scope_id, request.capability)
    if not request.action or len(request.action) > 128:
        raise ValueError("invalid_delegated_action")
    if request.session_id:
        session = db.get(Session, request.session_id)
        if not session:
            raise ValueError("session_not_found")
        if request.scope_kind == "general" and session.project_id:
            raise ValueError("action_scope_mismatch")
        if request.scope_kind == "project" and session.project_id != request.scope_id:
            raise ValueError("action_scope_mismatch")
    if request.run_id:
        run = db.get(JarvisRun, request.run_id)
        if not run:
            raise ValueError("run_not_found")
        if request.scope_kind != "workflow" or run.workflow_id != request.scope_id:
            raise ValueError("action_scope_mismatch")


def request_action(
    db: DbSession,
    request: ActionRequest,
    *,
    force_approval: bool = False,
    auto_authorize: bool = False,
    approval_seconds: int = 600,
) -> tuple[DelegatedAction, bool]:
    _validate_request(db, request)
    now = utc_now()
    exact = request.exact_hash()
    uncertain = (
        db.query(DelegatedAction)
        .filter(
            DelegatedAction.exact_hash == exact,
            DelegatedAction.state.in_(("used", "uncertain")),
        )
        .order_by(DelegatedAction.created_at.desc())
        .first()
    )
    if uncertain:
        if uncertain.state == "used":
            uncertain.state = "uncertain"
            uncertain.finished_at = now
            _event(db, "action_uncertain", action=uncertain)
        raise ValueError("uncertain_action_outcome")
    approved = (
        db.query(DelegatedAction)
        .filter_by(exact_hash=exact, state="approved")
        .filter(DelegatedAction.expires_at > now)
        .first()
    )
    if approved:
        return approved, True
    if auto_authorize and not force_approval:
        existing = db.query(DelegatedAction).filter_by(pending_key=exact, state="pending").first()
        if existing:
            existing.state = "approved"
            existing.pending_key = None
            existing.approved_at = now
            existing.expires_at = now + timedelta(seconds=max(30, min(approval_seconds, 3600)))
            _event(db, "approval_granted", action=existing, actor="owner_mode")
            db.flush()
            return existing, True
        row = DelegatedAction(
            origin=request.origin,
            run_id=request.run_id,
            agent_run_id=request.agent_run_id,
            session_id=request.session_id,
            scope_kind=request.scope_kind,
            scope_id=request.scope_id,
            capability=request.capability,
            action=request.action,
            target=_bounded(request.target, 2000),
            data_summary=_bounded(request.data_summary, 2000),
            privacy_effect=_bounded(request.privacy_effect, 2000),
            cost=_bounded(request.cost, 128),
            exact_hash=exact,
            state="approved",
            approved_at=now,
            expires_at=now + timedelta(seconds=max(30, min(approval_seconds, 3600))),
        )
        db.add(row)
        db.flush()
        _event(db, "approval_granted", action=row, actor="owner_mode")
        return row, True
    grant = None if force_approval else _active_grant(db, request, now)
    if grant:
        row = DelegatedAction(
            origin=request.origin,
            run_id=request.run_id,
            agent_run_id=request.agent_run_id,
            session_id=request.session_id,
            grant_id=grant.id,
            scope_kind=request.scope_kind,
            scope_id=request.scope_id,
            capability=request.capability,
            action=request.action,
            target=_bounded(request.target, 2000),
            data_summary=_bounded(request.data_summary, 2000),
            privacy_effect=_bounded(request.privacy_effect, 2000),
            cost=_bounded(request.cost, 128),
            exact_hash=exact,
            state="authorized",
            expires_at=now + timedelta(seconds=max(30, min(approval_seconds, 3600))),
        )
        db.add(row)
        db.flush()
        return row, True

    existing = db.query(DelegatedAction).filter_by(pending_key=exact, state="pending").first()
    if existing:
        if existing.expires_at > now:
            return existing, False
        existing.state = "expired"
        existing.pending_key = None
        _event(db, "approval_expired", action=existing)
    row = DelegatedAction(
        origin=request.origin,
        run_id=request.run_id,
        agent_run_id=request.agent_run_id,
        session_id=request.session_id,
        scope_kind=request.scope_kind,
        scope_id=request.scope_id,
        capability=request.capability,
        action=request.action,
        target=_bounded(request.target, 2000),
        data_summary=_bounded(request.data_summary, 2000),
        privacy_effect=_bounded(request.privacy_effect, 2000),
        cost=_bounded(request.cost, 128),
        exact_hash=exact,
        pending_key=exact,
        state="pending",
        expires_at=now + timedelta(seconds=max(30, min(approval_seconds, 3600))),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.query(DelegatedAction).filter_by(pending_key=exact).one()
        return existing, False
    _event(db, "approval_requested", action=row, actor=request.origin)
    if request.run_id:
        run = db.get(JarvisRun, request.run_id)
        prompt = create_prompt(
            db,
            run,
            kind="approval",
            question=f"allow {request.action}?",
            action=request.action,
            target=request.target,
            data_summary=request.data_summary,
            privacy_effect=request.privacy_effect,
            cost=request.cost,
            capability=request.capability,
            expires_at=row.expires_at,
        )
        prompt.delegated_action_id = row.id
    return row, False


def reconcile_delegated_actions() -> int:
    """Never repeat an action whose process stopped after claiming its one-use permission."""
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(DelegatedAction).filter_by(state="used").all()
        for action in rows:
            action.state = "uncertain"
            action.finished_at = utc_now()
            _event(db, "action_uncertain", action=action)
        db.commit()
        return len(rows)
    finally:
        db.close()


def decide_action(
    db: DbSession,
    action: DelegatedAction,
    *,
    allow: bool,
    exact_hash: str,
) -> DelegatedAction:
    now = utc_now()
    if not exact_hash or exact_hash != action.exact_hash:
        _event(db, "approval_denied", action=action, actor="owner")
        raise ValueError("approval_action_changed")
    if action.expires_at <= now:
        changed = (
            db.query(DelegatedAction)
            .filter_by(id=action.id, state="pending")
            .update(
                {DelegatedAction.state: "expired", DelegatedAction.pending_key: None},
                synchronize_session=False,
            )
        )
        if changed == 1:
            db.flush()
            db.refresh(action)
            _event(db, "approval_expired", action=action, actor="owner")
        raise ValueError("approval_expired")
    new_state = "approved" if allow else "denied"
    changed = (
        db.query(DelegatedAction)
        .filter_by(id=action.id, state="pending", pending_key=action.exact_hash)
        .filter(DelegatedAction.expires_at > now)
        .update(
            {
                DelegatedAction.state: new_state,
                DelegatedAction.pending_key: None,
                DelegatedAction.approved_at: now if allow else None,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.expire(action)
        db.refresh(action)
        raise ValueError("approval_not_pending")
    db.flush()
    db.refresh(action)
    _event(db, "approval_granted" if allow else "approval_denied", action=action, actor="owner")
    prompt = db.query(JarvisRunPrompt).filter_by(delegated_action_id=action.id).first()
    if prompt:
        prompt.state = "answered"
        prompt.answer = "approved" if allow else "denied"
        prompt.responded_at = now
        run = db.get(JarvisRun, prompt.run_id)
        if run and run.state == "waiting_approval":
            transition_run(db, run, "queued" if allow else "paused")
    db.flush()
    return action


def begin_action(db: DbSession, action: DelegatedAction, request: ActionRequest) -> DelegatedAction:
    now = utc_now()
    _validate_request(db, request)
    if action.exact_hash != request.exact_hash():
        raise ValueError("approval_action_changed")
    if action.expires_at <= now:
        action.state = "expired"
        _event(db, "approval_expired", action=action)
        raise ValueError("approval_expired")
    if action.grant_id:
        grant = db.get(CapabilityGrant, action.grant_id)
        matched = _active_grant(db, request, now)
        if not grant or not matched or matched.id != grant.id:
            _event(db, "grant_use_denied", action=action)
            raise ValueError("grant_not_active")
        grant_claimed = (
            db.query(CapabilityGrant)
            .filter_by(id=grant.id, state="active")
            .filter((CapabilityGrant.expires_at.is_(None)) | (CapabilityGrant.expires_at > now))
            .update({CapabilityGrant.last_used_at: now}, synchronize_session=False)
        )
        if grant_claimed != 1:
            _event(db, "grant_use_denied", action=action)
            raise ValueError("grant_not_active")
    elif action.state != "approved":
        if action.state == "used":
            raise ValueError("approval_already_used")
        raise ValueError("approval_required")
    changed = (
        db.query(DelegatedAction)
        .filter(
            DelegatedAction.id == action.id,
            DelegatedAction.state.in_(("authorized", "approved")),
        )
        .update(
            {DelegatedAction.state: "used", DelegatedAction.used_at: now},
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise ValueError("approval_already_used")
    db.flush()
    db.refresh(action)
    if action.grant_id:
        grant = db.get(CapabilityGrant, action.grant_id)
        db.refresh(grant)
        _event(db, "grant_used", grant=grant, action=action)
    else:
        _event(db, "approval_used", action=action, actor=action.origin)
    prompt = db.query(JarvisRunPrompt).filter_by(delegated_action_id=action.id).first()
    if prompt:
        prompt.used_at = now
    if action.run_id:
        run = db.get(JarvisRun, action.run_id)
        append_event(
            db,
            run,
            "side_effect_started",
            source=action.origin,
            tool_name=action.action,
            summary="approved action started",
            data={"action_id": action.id},
        )
        if request.target_is_path and run.project_id:
            project = db.get(Project, run.project_id)
            targets = request.path_targets or (request.target,)
            if (
                project
                and project.working_dir
                and not all(_within(target, project.working_dir) for target in targets)
            ):
                run.left_project_root = True
    return action


def finish_action(
    db: DbSession,
    action: DelegatedAction,
    *,
    success: bool,
    outcome_known: bool = True,
) -> DelegatedAction:
    if action.state != "used":
        raise ValueError("action_not_started")
    action.finished_at = utc_now()
    action.state = "completed" if success else ("failed" if outcome_known else "uncertain")
    _event(db, "action_completed" if success else action.state, action=action)
    if action.run_id:
        run = db.get(JarvisRun, action.run_id)
        if outcome_known:
            append_event(
                db,
                run,
                "side_effect_confirmed",
                source=action.origin,
                tool_name=action.action,
                summary="approved action outcome confirmed",
                data={"action_id": action.id, "success": success},
            )
        else:
            transition_run(
                db,
                run,
                "uncertain",
                failure_class="uncertain",
                safe_error="an approved outside action has an unknown result",
            )
    return action
