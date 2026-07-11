import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.access_middleware import HostGuardMiddleware, PublicHttpsMiddleware
from core.api_errors import ApiError, api_error_handler
from core.database import ModelEndpoint, SessionLocal, init_db
from core.server_config import (
    access_profile,
    bind_host,
    cors_origins,
    forwarded_allow_ips,
    trusted_hosts,
    validate_access_config,
)
from core.settings import anthropic_api_key, auth_enabled, deepseek_api_key, get_port
from services import events as _events  # noqa: F401 - installs the 0c mutation spine
from routes import (
    agent as agent_routes,
)
from routes import (
    api_tokens as token_routes,
)
from routes import (
    appearance as appearance_routes,
)
from routes import (
    auth as auth_routes,
)
from routes import (
    automations as automation_routes,
)
from routes import (
    backup as backup_routes,
)
from routes import (
    books as books_routes,
)
from routes import (
    briefing as briefing_routes,
)
from routes import (
    caldav as caldav_routes,
)
from routes import (
    calendar as calendar_routes,
)
from routes import (
    calendars as calendars_routes,
)
from routes import (
    carddav as carddav_routes,
)
from routes import (
    chat,
    models,
    sessions,
)
from routes import (
    code as code_routes,
)
from routes import (
    compare as compare_routes,
)
from routes import (
    connections as connection_routes,
)
from routes import (
    contacts as contact_routes,
)
from routes import (
    cookbook as cookbook_routes,
)
from routes import (
    days as days_routes,
)
from routes import (
    files as files_routes,
)
from routes import (
    gallery as gallery_routes,
)
from routes import (
    habits as habits_routes,
)
from routes import (
    health as health_routes,
)
from routes import (
    images as images_routes,
)
from routes import (
    insights as insights_routes,
)
from routes import (
    journal as journal_routes,
)
from routes import (
    local_models as local_model_routes,
)
from routes import (
    macos as macos_routes,
)
from routes import (
    mail as mail_routes,
)
from routes import (
    mcp as mcp_routes,
)
from routes import (
    memory as memory_routes,
)
from routes import (
    money as money_routes,
)
from routes import (
    notes as notes_routes,
)
from routes import (
    openai_compat as oai_routes,
)
from routes import (
    personas as personas_routes,
)
from routes import (
    photos as photos_routes,
)
from routes import (
    proactive as proactive_routes,
)
from routes import (
    projects as project_routes,
)
from routes import (
    push as push_routes,
)
from routes import (
    rag as rag_routes,
)
from routes import (
    read as read_routes,
)
from routes import (
    capabilities as capabilities_routes,
)
from routes import (
    chains as chains_routes,
)
from routes import (
    export as export_routes,
)
from routes import (
    recall as recall_routes,
)
from routes import (
    reminders as reminder_routes,
)
from routes import (
    research as research_routes,
)
from routes import (
    search as search_routes,
)
from routes import (
    settings as settings_routes,
)
from routes import (
    shared as shared_routes,
)
from routes import (
    shell as shell_routes,
)
from routes import (
    skills as skills_routes,
)
from routes import (
    status as status_routes,
)
from routes import (
    subscriptions as subscription_routes,
)
from routes import (
    tasks as tasks_routes,
)
from routes import (
    textindex as textindex_routes,
)
from routes import (
    today as today_routes,
)
from routes import (
    uploads as upload_routes,
)
from routes import (
    usage as usage_routes,
)
from routes import (
    vault as vault_routes,
)
from routes import (
    vault_md as vault_md_routes,
)
from routes import (
    voice as voice_routes,
)
from routes import (
    watch as watch_routes,
)
from routes import (
    webhooks as webhook_routes,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("alles")


async def _bootstrap_deepseek():
    """if DEEPSEEK_API_KEY is set and no endpoints exist yet, auto-create one"""
    key = deepseek_api_key()
    if not key or key == "sk-...":
        return
    db = SessionLocal()
    try:
        count = db.query(ModelEndpoint).count()
        if count > 0:
            return
        log.info("bootstrapping DeepSeek endpoint from DEEPSEEK_API_KEY")
        ep = ModelEndpoint(
            name="DeepSeek",
            base_url="https://api.deepseek.com",
            api_key=key,
            cached_models=json.dumps(["deepseek-chat", "deepseek-reasoner", "deepseek-coder-v2"]),
        )
        db.add(ep)
        db.commit()
        log.info("DeepSeek endpoint created — default model: deepseek-chat")
    finally:
        db.close()


async def _bootstrap_anthropic():
    """if ANTHROPIC_API_KEY is set and Anthropic is missing, auto-create it"""
    key = anthropic_api_key()
    if not key or key == "sk-ant-...":
        return
    db = SessionLocal()
    try:
        exists = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.base_url == "https://api.anthropic.com")
            .first()
        )
        if exists:
            return
        log.info("bootstrapping Anthropic endpoint from ANTHROPIC_API_KEY")
        ep = ModelEndpoint(
            name="Anthropic",
            base_url="https://api.anthropic.com",
            api_key=key,
            cached_models=json.dumps(
                [
                    "claude-fable-5",
                    "claude-opus-4-8",
                    "claude-sonnet-4-6",
                    "claude-haiku-4-5-20251001",
                ]
            ),
            vision_models=json.dumps(
                [
                    "claude-fable-5",
                    "claude-opus-4-8",
                    "claude-sonnet-4-6",
                    "claude-haiku-4-5-20251001",
                ]
            ),
        )
        db.add(ep)
        db.commit()
        log.info("Anthropic endpoint created - default model: claude-fable-5")
    finally:
        db.close()


async def _fire_due_reminders():
    """plain reminders → web push once; scheduled 'message' reminders → run the
    model and drop the reply into the session. (a registered 30s job)"""
    from core.database import Reminder, Session, SessionLocal
    from core.settings import load_settings
    from routes.push import broadcast_result as push_broadcast_result
    from services.llm import stream_chat

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        # plain reminders: web push once, but leave them unfired so an
        # open tab still picks them up via /api/reminders/due
        plain = (
            db.query(Reminder)
            .filter(
                Reminder.trigger_at <= now,
                Reminder.fired == False,
                Reminder.notified == False,
                Reminder.type == "reminder",
            )
            .all()
        )
        for r in plain:
            # ``notified`` is the durable delivery claim. If the process stops
            # after the provider accepts the push, this row will not be retried.
            r.notified = True
            db.commit()
            try:
                result = await push_broadcast_result(
                    {"title": "reminder", "body": r.text, "url": "/", "tag": f"reminder-{r.id}"}
                )
                # push reached a browser -> the user's been told, so mark it fired: it won't
                # linger as "overdue" in the list or re-toast on next open. with no live
                # subscriptions, leave it unfired so an open tab still toasts it via /due.
                if result["sent"]:
                    r.fired = True
                elif not result["uncertain"]:
                    # No provider may have accepted it, so a later safe retry is allowed.
                    r.notified = False
                db.commit()
            except Exception as e:
                # The call may have delivered before raising. Keep the claim set.
                log.warning("reminder push outcome uncertain: %s", type(e).__name__)

        due = (
            db.query(Reminder)
            .filter(
                Reminder.trigger_at <= now,
                Reminder.fired == False,
                Reminder.notified == False,
                Reminder.type == "message",
            )
            .all()
        )
        for r in due:
            if not r.session_id:
                continue
            s = db.get(Session, r.session_id)
            if not s:
                continue
            from datetime import datetime as dt

            from core.database import Message, ModelEndpoint

            ep = db.get(ModelEndpoint, s.endpoint_id)
            if not ep:
                continue
            # Scheduled model calls can cost money even if the process stops
            # before their response is saved. Claim first; a stale claim waits
            # for owner review instead of spending again automatically.
            r.notified = True
            db.commit()
            settings = load_settings()
            msgs = [{"role": "system", "content": settings.get("system_prompt", "You are aide.")}]
            for m in list(s.messages)[-20:]:
                msgs.append({"role": m.role, "content": m.content})
            msgs.append({"role": "user", "content": r.text})
            acc = []
            try:
                async for chunk in stream_chat(msgs, ep.base_url, ep.api_key, s.model):
                    if "delta" in chunk:
                        acc.append(chunk["delta"])
            except Exception as e:
                # one broken endpoint must not stall the rest of the queue,
                # and the reminder itself still lands in the session below
                log.warning(f"reminder LLM call failed for session {s.id}: {e}")
            full = "".join(acc) or "(reminder fired, but the model could not be reached)"
            um = Message(session_id=s.id, role="user", content=r.text)
            am = Message(session_id=s.id, role="assistant", content=full)
            db.add(um)
            db.add(am)
            r.fired = True
            s.message_count = (s.message_count or 0) + 2
            s.last_message_at = dt.utcnow()
            db.commit()
            log.info(f"fired scheduled message for session {s.id}")
            try:
                await push_broadcast_result(
                    {"title": "aide", "body": full[:160], "url": "/", "tag": f"message-{r.id}"}
                )
            except Exception as e:
                log.warning(f"message push failed: {e}")
    finally:
        db.close()


def _register_jobs():
    """wire the periodic checks into the shared job registry. same functions and
    intervals as before — just routed through services.jobs so new features
    (scheduled agents, daily digest) can register their own jobs."""
    from services import jobs

    async def _subs():
        from routes.subscriptions import check_renewals

        await check_renewals()

    async def _days():
        from routes.days import check_day_events

        await check_day_events()

    async def _autos():
        from services.automations import run_automations

        await run_automations()

    async def _models():
        from routes.models import refresh_all_model_lists

        await refresh_all_model_lists()

    async def _cal_reminders():
        from services.cal_notify import fire_due

        await fire_due()

    async def _outbox():
        from services.mail_outbox import _job

        await _job()

    async def _photo_watch():
        # PIL decode + a full folder walk — run off the event loop so the periodic scan
        # doesn't freeze every other request while it churns through images.
        from services.photo_sync import run_watch

        await asyncio.to_thread(run_watch)

    async def _ics_subs():
        from routes.calendar import refresh_all_subscriptions

        await refresh_all_subscriptions()

    async def _carddav_auto():
        # ticks every 10 min; actually syncs only when the user's interval is due (7b)
        from services import carddav_sync

        if carddav_sync.due_for_sync(time.time()):
            await asyncio.to_thread(carddav_sync.sync)  # blocking CardDAV HTTP — off the loop

    async def _watch():
        from routes.watch import run_checks

        await run_checks()

    async def _read_feeds():
        from services.read_feeds import refresh_feeds

        await refresh_feeds()

    async def _reconcile():
        # synchronous IMAP body fetches + fastembed encodes — the worst loop-blocker of the
        # job set. run the whole thing (session included, so it's thread-local) off the loop.
        def _job():
            from core.database import SessionLocal
            from services import personal_index

            db = SessionLocal()
            try:
                personal_index.reconcile(db)
            finally:
                db.close()

        await asyncio.to_thread(_job)

    async def _proactive():
        from services import proactive

        await proactive.run()

    async def _blob_gc():
        def _job():
            from core.database import SessionLocal
            from services import blobstore

            db = SessionLocal()
            try:
                blobstore.gc(db)  # walks blob dir + stats files — off the loop
            finally:
                db.close()

        await asyncio.to_thread(_job)

    async def _user_model():
        from core.database import SessionLocal
        from core.settings import load_settings
        from services import user_model

        if not load_settings().get("user_model_distill", False):
            return  # gated - spends tokens
        db = SessionLocal()
        try:
            await user_model.distill_async(db)
        finally:
            db.close()

    async def _insights():
        from core.database import SessionLocal
        from services import insights

        db = SessionLocal()
        try:
            await insights.generate_async(db)  # internally gated on insights_enabled
        finally:
            db.close()

    async def _holdings_price():
        from core.settings import load_settings

        if not load_settings().get("holdings_autoprice", False):
            return  # gated - hits the network; opt-in

        def _job():
            from core.database import SessionLocal
            from services import price_fetch

            db = SessionLocal()
            try:
                price_fetch.refresh(db)  # blocking price HTTP — off the loop
            finally:
                db.close()

        await asyncio.to_thread(_job)

    async def _clip_index():
        # phase 7b: embed un-indexed photos for semantic search. only runs if the optional CLIP
        # models are present; onnxruntime inference is off the loop. chips through in batches.
        from services import clip

        if not clip.available():
            return

        def _job():
            from core.database import SessionLocal

            db = SessionLocal()
            try:
                n = clip.index_pending(db, limit=40)
                if n:
                    log.info(f"clip-indexed {n} photo(s) for semantic search")
            finally:
                db.close()

        await asyncio.to_thread(_job)

    async def _faces_index():
        # phase 7a: detect + embed faces, then cluster them into people. only runs if the optional
        # InsightFace models are present; inference + clustering are off the loop, in batches.
        from services import faces

        if not faces.available():
            return

        def _job():
            from core.database import SessionLocal

            db = SessionLocal()
            try:
                n = faces.index_pending(db, limit=20)
                ch = faces.cluster(db)
                if n or ch:
                    log.info(f"face-indexed {n} face(s), {ch} cluster change(s)")
            finally:
                db.close()

        await asyncio.to_thread(_job)

    jobs.register("read_feeds", _read_feeds, 1800, run_at_start=False)  # rss auto-save (30 min)
    jobs.register("holdings_price", _holdings_price, 6 * 3600, run_at_start=False)  # 2d (gated)
    jobs.register("blob_gc", _blob_gc, 6 * 3600, run_at_start=False)  # 0d - purge orphaned blobs
    jobs.register("clip_index", _clip_index, 60, run_at_start=False)  # 7b semantic-search indexing
    jobs.register("faces_index", _faces_index, 90, run_at_start=False)  # 7a face detect + cluster
    jobs.register(
        "user_model", _user_model, 24 * 3600, run_at_start=False
    )  # 1c daily distill (gated)
    jobs.register("insights", _insights, 24 * 3600, run_at_start=False)  # 1e daily insights (gated)
    jobs.register("subscriptions", _subs, 30)
    jobs.register("day_events", _days, 30)
    jobs.register("automations", _autos, 30)
    jobs.register("reminders", _fire_due_reminders, 30)
    jobs.register("calendar_reminders", _cal_reminders, 30)
    jobs.register("mail_outbox", _outbox, 30)  # flush scheduled sends (5b)
    jobs.register("model_refresh", _models, 6 * 3600)  # runs at boot, then every 6h
    jobs.register("photo_watch", _photo_watch, 300, run_at_start=False)  # 7c phone backup
    jobs.register("ics_subscriptions", _ics_subs, 3600, run_at_start=False)  # 8a calendar feeds
    jobs.register("carddav_auto", _carddav_auto, 600, run_at_start=False)  # 7b contacts auto-sync
    jobs.register("watch", _watch, 60, run_at_start=False)  # uptime/cert/health probes
    jobs.register("personal_reconcile", _reconcile, 120, run_at_start=False)
    from services.proactive import _interval_seconds

    jobs.register(
        "proactive",
        _proactive,
        _interval_seconds(),
        run_at_start=False,
        interval_fn=_interval_seconds,
    )  # advisory cards


async def _reminder_loop():
    """ticks the background job registry every 30s."""
    await asyncio.sleep(5)  # let startup finish
    _register_jobs()
    from services import jobs

    while True:
        try:
            await jobs.run_due()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning(f"job loop error: {e}")
        await asyncio.sleep(30)


def _cleanup_empty_sessions():
    """drop sessions that never got a message (abandoned 'new chat' / incognito leftovers)"""
    from core.database import Message as Msg
    from core.database import Session

    db = SessionLocal()
    try:
        empty_ids = [
            sid
            for (sid,) in (
                db.query(Session.id)
                .outerjoin(Msg, Msg.session_id == Session.id)
                .filter(Session.starred.is_(False), Msg.id.is_(None))
                .all()
            )
        ]
        gone = 0
        if empty_ids:
            gone = (
                db.query(Session)
                .filter(Session.id.in_(empty_ids))
                .delete(synchronize_session=False)
            )
        if gone:
            db.commit()
            log.info(f"cleaned {gone} empty session(s)")
    except Exception as e:
        log.warning(f"empty-session cleanup failed: {e}")
    finally:
        db.close()


# last connectivity probe result — surfaced via /api/ping, also set by the startup self-test
_last_ping: dict = {}


async def _probe_endpoints() -> dict:
    """GET each enabled endpoint's base host. ok=True means reachable (any HTTP code)."""
    import httpx

    from core.database import ModelEndpoint as ME
    from core.database import SessionLocal as SL

    db = SL()
    try:
        eps = db.query(ME).filter(ME.enabled == True).all()
    finally:
        db.close()
    results = {}
    async with httpx.AsyncClient(timeout=6, follow_redirects=True) as c:
        for ep in eps:
            try:
                r = await c.get(ep.base_url.rstrip("/"), headers={"user-agent": "alles-ping/1.0"})
                results[ep.name] = {"ok": True, "status": r.status_code}
            except Exception as e:
                results[ep.name] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:120]}
    global _last_ping
    _last_ping = results
    return results


async def _connectivity_selftest():
    """ping the configured endpoints on boot, warn loudly if outbound is dead.
    runs detached so it never delays startup."""
    try:
        results = await _probe_endpoints()
    except Exception as e:
        log.warning(f"connectivity self-test couldn't run: {e}")
        return
    if not results:
        return  # nothing configured yet
    reachable = [n for n, r in results.items() if r.get("ok")]
    dead = [n for n, r in results.items() if not r.get("ok")]
    for n in reachable:
        log.info(f"connectivity ok - {n} (HTTP {results[n]['status']})")
    for n in dead:
        log.warning(
            f"connectivity FAILED - {n}: {results[n].get('error')} - {results[n].get('detail')}"
        )
    if dead and not reachable:
        log.warning(
            "no endpoints reachable - outbound network looks blocked. "
            "if you launched alles from a sandboxed shell, restart it from your own "
            "terminal (python cli.py restart) so it actually has network."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.settings import data_dir as configured_data_dir
    from services.instance_lock import InstanceLock
    from services.restore_apply import maintenance_lock_path
    from services.update_safety import update_lock_path, update_start_allowed

    preflight = os.environ.get("ALLES_RECOVERY_PREFLIGHT") == "1"
    live_data = configured_data_dir().expanduser().resolve()
    if not preflight and maintenance_lock_path(live_data).exists():
        raise RuntimeError(
            "an offline restore is unfinished; run `alles restore recover` before starting Alles"
        )
    if (
        not preflight
        and update_lock_path(live_data).exists()
        and not update_start_allowed(live_data, os.environ.get("ALLES_UPDATE_TOKEN"))
    ):
        raise RuntimeError(
            "an offline update is unfinished; run `alles update rollback` before starting Alles"
        )

    instance_lock = InstanceLock(live_data)
    instance_lock.acquire()
    reminder_task = None
    photo_backfill_task = None
    connectivity_task = None
    try:
        init_db()
        if preflight:
            log.info("alles recovery preflight ready")
            yield
            return

        # A previous process may have stopped after an external action but before
        # saving its result. Resolve those claims before the job loop can run so
        # they are visible as uncertain and are never retried blindly.
        from services.automations import reconcile_interrupted_attempts

        interrupted_automations = reconcile_interrupted_attempts()
        if interrupted_automations:
            log.warning(
                "marked %s interrupted automation attempt(s) uncertain",
                interrupted_automations,
            )

        try:
            from services import net

            if net.apply_proxy():
                log.info("outbound proxy applied from settings")
        except Exception:
            pass
        await _bootstrap_deepseek()
        await _bootstrap_anthropic()
        _cleanup_empty_sessions()
        try:
            from services import skills_store

            skills_store.seed_library()  # first-boot: install the whole bundled catalog
        except Exception:
            pass
        try:
            from routes.personas import seed_default_personas

            seed_default_personas()  # first-boot starter personas
        except Exception:
            pass
        try:
            from routes.calendars import seed_default_calendar

            seed_default_calendar()  # first-boot 'Personal' calendar + adopt orphan events
        except Exception:
            pass

        async def _photo_backfill():
            # phase 4: fill aspect_ratio / preview / checksum on photos imported before the columns
            # existed. gated on checksum==null so it's a cheap no-op once done; off-thread (opens images)
            def _job():
                from core.database import SessionLocal as SL
                from services import photos_store

                db = SL()
                try:
                    n = photos_store.backfill_perf(db)
                    if n:
                        log.info(f"backfilled perf fields on {n} photo(s)")
                finally:
                    db.close()

            await asyncio.to_thread(_job)

        photo_backfill_task = asyncio.create_task(_photo_backfill())
        try:
            from services import agent_state

            n = (
                agent_state.reconcile_interrupted()
            )  # zombie 'running' runs from a dead process → interrupted
            if n:
                log.info(f"reconciled {n} interrupted agent run(s) from a previous process")
        except Exception:
            pass
        try:
            from routes.mcp import connect_all

            await connect_all()
        except Exception:
            pass
        reminder_task = asyncio.create_task(_reminder_loop())
        connectivity_task = asyncio.create_task(
            _connectivity_selftest()
        )  # fire-and-forget, logs a warning if outbound is dead
        log.info("alles ready")
        yield
    finally:
        if reminder_task is not None:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("background job loop stopped with %s", type(exc).__name__)
        if connectivity_task is not None:
            connectivity_task.cancel()
            try:
                await connectivity_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("connectivity check stopped with %s", type(exc).__name__)
        if photo_backfill_task is not None:
            # ``asyncio.to_thread`` keeps running after cancellation. Wait for this
            # database writer before releasing the single-instance lock.
            try:
                await photo_backfill_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("photo backfill stopped with %s", type(exc).__name__)
        instance_lock.release()
        log.info("alles shutting down")


validate_access_config()
app = FastAPI(title="alles", lifespan=lifespan)
app.add_exception_handler(ApiError, api_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(cors_origins()),
    # Same-origin app traffic does not need CORS. Explicit trusted origins may use
    # the normal session cookie; unknown origins receive no read access.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_trusted_hosts = trusted_hosts()
if _trusted_hosts:
    app.add_middleware(HostGuardMiddleware, allowed_hosts=_trusted_hosts)
if access_profile() == "public":
    app.add_middleware(PublicHttpsMiddleware)


def _cookie_val(header: str, key: str) -> str:
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k == key:
                return v
    return ""


class TokenAuthMiddleware:
    """
    Pure ASGI middleware (NOT BaseHTTPMiddleware — that one buffers streaming
    responses and kills SSE). Passes chunks straight through.
    1. Bearer alles_xxx or aide_xxx token -> validate it.
    2. AUTH_ENABLED=true → block unauthenticated /api/ (except /api/auth/*).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        path = scope.get("path", "")
        token_authenticated = False

        if auth.startswith("Bearer aide_") or auth.startswith("Bearer alles_"):
            token = auth.split(" ", 1)[1]
            from routes.api_tokens import required_scope, token_access

            db = SessionLocal()
            try:
                access = token_access(
                    token,
                    db,
                    required_scope(scope.get("method", "GET"), path),
                )
            finally:
                db.close()
            if access == "invalid":
                await self._deny(send, "invalid token", code="invalid_token")
                return
            if access == "forbidden":
                await self._deny(
                    send,
                    "token scope does not allow this request",
                    status=403,
                    code="token_scope_denied",
                )
                return
            token_authenticated = True

        # gate /api/ AND /v1/ (the openai-compat router) - both drive the model + the user's data.
        # /api/auth/* stays open so login works; public /s/ /book/ /rsvp/ aren't under these prefixes.
        gated = path.startswith("/v1/") or (
            path.startswith("/api/") and not path.startswith("/api/auth")
        )
        if auth_enabled() and gated and not token_authenticated:
            from core.auth import verify_session

            cookie = _cookie_val(headers.get(b"cookie", b"").decode("latin-1"), "aide_session")
            if not verify_session(cookie):
                await self._deny(send, "not authenticated", code="not_authenticated")
                return

        await self.app(scope, receive, send)

    async def _deny(self, send, detail, status=401, code="not_authenticated"):
        body = json.dumps({"detail": detail, "code": code}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


app.add_middleware(TokenAuthMiddleware)

# routes
app.include_router(auth_routes.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(models.router)
app.include_router(settings_routes.router)
app.include_router(memory_routes.router)
app.include_router(research_routes.router)
app.include_router(journal_routes.router)
app.include_router(usage_routes.router)
app.include_router(rag_routes.router)
app.include_router(textindex_routes.router)
app.include_router(images_routes.router)
app.include_router(skills_routes.router)
from routes import notify as notify_routes
from routes import system as system_routes
from routes import timeline as timeline_routes

app.include_router(notify_routes.router)
app.include_router(shell_routes.router)
app.include_router(mcp_routes.router)
app.include_router(notes_routes.router)
app.include_router(tasks_routes.router)
app.include_router(calendar_routes.router)
app.include_router(calendars_routes.router)
app.include_router(gallery_routes.router)
app.include_router(cookbook_routes.router)
app.include_router(personas_routes.router)
app.include_router(webhook_routes.router)
app.include_router(token_routes.router)
app.include_router(upload_routes.router)
app.include_router(project_routes.router)
app.include_router(voice_routes.router)
app.include_router(search_routes.router)
app.include_router(compare_routes.router)
app.include_router(vault_routes.router)
app.include_router(oai_routes.router)
app.include_router(contact_routes.router)
app.include_router(backup_routes.router)
app.include_router(agent_routes.router)
app.include_router(connection_routes.router)
app.include_router(local_model_routes.router)
app.include_router(vault_md_routes.router)
app.include_router(reminder_routes.router)
app.include_router(shared_routes.router)
app.include_router(files_routes.router)
app.include_router(caldav_routes.router)
app.include_router(carddav_routes.router)
app.include_router(mail_routes.router)
app.include_router(photos_routes.router)
app.include_router(push_routes.router)
app.include_router(briefing_routes.router)
app.include_router(status_routes.router)
app.include_router(subscription_routes.router)
app.include_router(days_routes.router)
app.include_router(today_routes.router)
app.include_router(automation_routes.router)
app.include_router(money_routes.router)
app.include_router(timeline_routes.router)
app.include_router(system_routes.router)
app.include_router(insights_routes.router)
app.include_router(code_routes.router)
app.include_router(macos_routes.router)
app.include_router(watch_routes.router)
app.include_router(appearance_routes.router)
app.include_router(habits_routes.router)
app.include_router(read_routes.router)
app.include_router(books_routes.router)
app.include_router(health_routes.router)
app.include_router(capabilities_routes.router)
app.include_router(chains_routes.router)
app.include_router(export_routes.router)
app.include_router(recall_routes.router)
app.include_router(proactive_routes.router)


# static files — no-cache so JS/CSS always reloads
class NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        ext = Path(path).suffix.lower()
        if ext in (".js", ".css", ".html"):
            resp.headers["cache-control"] = "no-cache, no-store, must-revalidate"
        return resp


static_dir = Path(__file__).parent / "static"
app.mount("/static", NoCacheStatic(directory=str(static_dir), html=False), name="static")


@app.get("/")
async def index():
    # no-cache so the SPA shell never goes stale (JS/CSS already no-cache via NoCacheStatic)
    return FileResponse(
        str(static_dir / "index.html"),
        headers={"cache-control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/sw.js")
async def service_worker():
    # served from root so the worker's scope covers the whole app
    return FileResponse(
        str(static_dir / "sw.js"),
        media_type="application/javascript",
        headers={"cache-control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/manifest.json")
async def manifest():
    return FileResponse(str(static_dir / "manifest.json"), media_type="application/manifest+json")


@app.get("/api/pwa/precache")
async def pwa_precache():
    # 11b: the SW fetches this on install to precache the whole app shell so a cold offline
    # load actually boots. enumerated at runtime so a new js module is covered automatically
    # (no build manifest to drift). the JS module graph is requested without a ?v query — only
    # the index.html entry import + the stylesheet carry the stamp — so mirror that here.
    import re

    html = (static_dir / "index.html").read_text(encoding="utf-8")
    m = re.search(r"\?v=(\d+)", html)
    stamp = m.group(1) if m else "1"
    urls = ["/", "/manifest.json", f"/static/style.css?v={stamp}"]
    for ic in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        if (static_dir / "icons" / ic).exists():
            urls.append(f"/static/icons/{ic}")
    for p in sorted((static_dir / "js").glob("*.js")):
        urls.append(
            f"/static/js/app.js?v={stamp}" if p.name == "app.js" else f"/static/js/{p.name}"
        )
    for v in ("vendor/cm6.bundle.js",):
        if (static_dir / v).exists():
            urls.append(f"/static/{v}")
    return {"urls": urls}


def _request_authed(request: Request) -> bool:
    """bearer token or session cookie — mirrors TokenAuthMiddleware, for the few public routes
    that want to vary their output by auth."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer aide_") or auth.startswith("Bearer alles_"):
        from routes.api_tokens import verify_token

        db = SessionLocal()
        try:
            if verify_token(auth.split(" ", 1)[1], db, required_scope="read"):
                return True
        finally:
            db.close()
    from core.auth import verify_session

    return verify_session(request.cookies.get("aide_session", ""))


@app.get("/health")
def health(request: Request, deep: bool = False):
    # default stays a cheap liveness ping. ?deep=1 runs the full readiness check, but its details
    # (data-dir PATH, installed deps, provider/key state) are internal — only expose them in local
    # mode (no auth) or to an authenticated caller, never to an anonymous client when auth is on.
    if deep and (not auth_enabled() or _request_authed(request)):
        from services import doctor

        return {"ok": doctor.healthy(), "checks": doctor.run_all()}
    return {"ok": True}


@app.get("/api/ping")
async def ping(cached: bool = False):
    """connectivity self-test — hits each configured endpoint's base host.
    ?cached=1 returns the last probe (e.g. the boot self-test) without re-hitting."""
    if cached and _last_ping:
        return _last_ping
    return await _probe_endpoints()


if __name__ == "__main__":
    import uvicorn

    port = get_port()
    try:
        host = bind_host()
    except ValueError as exc:
        log.error("refusing unsafe network configuration: %s", exc)
        raise SystemExit(2) from None
    do_reload = bool(
        os.environ.get("ALLES_RELOAD")
    )  # ALLES_RELOAD=1 -> hot-reload on .py edits (dev)
    display_host = "localhost" if host in {"127.0.0.1", "::1", "0.0.0.0", "::"} else host
    log.info(f"starting alles on http://{display_host}:{port}{' (reload)' if do_reload else ''}")
    proxy_ips = forwarded_allow_ips() if access_profile() == "public" else ()
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=do_reload,
        proxy_headers=bool(proxy_ips),
        forwarded_allow_ips=",".join(proxy_ips),
    )
