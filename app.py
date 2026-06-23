import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.database import ModelEndpoint, SessionLocal, init_db
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
    from routes.push import broadcast as push_broadcast
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
            r.notified = True
            db.commit()
            try:
                await push_broadcast(
                    {"title": "reminder", "body": r.text, "url": "/", "tag": f"reminder-{r.id}"}
                )
            except Exception as e:
                log.warning(f"reminder push failed: {e}")

        due = (
            db.query(Reminder)
            .filter(
                Reminder.trigger_at <= now,
                Reminder.fired == False,
                Reminder.type == "message",
            )
            .all()
        )
        for r in due:
            r.fired = True
            db.commit()
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
            s.message_count = (s.message_count or 0) + 2
            s.last_message_at = dt.utcnow()
            db.commit()
            log.info(f"fired scheduled message for session {s.id}")
            try:
                await push_broadcast(
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
        from services.photo_sync import run_watch

        run_watch()

    async def _ics_subs():
        from routes.calendar import refresh_all_subscriptions

        await refresh_all_subscriptions()

    async def _carddav_auto():
        # ticks every 10 min; actually syncs only when the user's interval is due (7b)
        from services import carddav_sync

        if carddav_sync.due_for_sync(time.time()):
            carddav_sync.sync()

    async def _watch():
        from routes.watch import run_checks

        await run_checks()

    async def _read_feeds():
        from services.read_feeds import refresh_feeds

        await refresh_feeds()

    async def _reconcile():
        from core.database import SessionLocal
        from services import personal_index

        db = SessionLocal()
        try:
            personal_index.reconcile(db)
        finally:
            db.close()

    async def _proactive():
        from services import proactive

        await proactive.run()

    async def _blob_gc():
        from core.database import SessionLocal
        from services import blobstore

        db = SessionLocal()
        try:
            blobstore.gc(db)
        finally:
            db.close()

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
        from core.database import SessionLocal
        from core.settings import load_settings
        from services import price_fetch

        if not load_settings().get("holdings_autoprice", False):
            return  # gated - hits the network; opt-in
        db = SessionLocal()
        try:
            price_fetch.refresh(db)
        finally:
            db.close()

    jobs.register("read_feeds", _read_feeds, 1800, run_at_start=False)  # rss auto-save (30 min)
    jobs.register("holdings_price", _holdings_price, 6 * 3600, run_at_start=False)  # 2d (gated)
    jobs.register("blob_gc", _blob_gc, 6 * 3600, run_at_start=False)  # 0d - purge orphaned blobs
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
        "proactive", _proactive, _interval_seconds(), run_at_start=False
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
        gone = 0
        for s in db.query(Session).all():
            if s.starred:
                continue
            if db.query(Msg).filter(Msg.session_id == s.id).count() == 0:
                db.delete(s)
                gone += 1
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
    init_db()
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
    task = asyncio.create_task(_reminder_loop())
    asyncio.create_task(
        _connectivity_selftest()
    )  # fire-and-forget, logs a warning if outbound is dead
    log.info("alles ready")
    yield
    task.cancel()
    log.info("alles shutting down")


app = FastAPI(title="alles", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # NOT allow_credentials: "*" origins + credentials makes starlette reflect the Origin and return
    # Access-Control-Allow-Credentials:true, letting any site read /api responses with the user's
    # session cookie. the SPA is same-origin (CORS doesn't apply), so credentialed cross-origin
    # access is purely an attack surface, not a feature.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

        if auth.startswith("Bearer aide_") or auth.startswith("Bearer alles_"):
            token = auth.split(" ", 1)[1]
            from routes.api_tokens import verify_token

            db = SessionLocal()
            try:
                valid = verify_token(token, db)
            finally:
                db.close()
            if not valid:
                await self._deny(send, "invalid token")
                return

        # gate /api/ AND /v1/ (the openai-compat router) - both drive the model + the user's data.
        # /api/auth/* stays open so login works; public /s/ /book/ /rsvp/ aren't under these prefixes.
        gated = path.startswith("/v1/") or (
            path.startswith("/api/") and not path.startswith("/api/auth")
        )
        if auth_enabled() and gated:
            from core.auth import verify_session

            cookie = _cookie_val(headers.get(b"cookie", b"").decode("latin-1"), "aide_session")
            if not verify_session(cookie):
                await self._deny(send, "not authenticated")
                return

        await self.app(scope, receive, send)

    async def _deny(self, send, detail):
        body = json.dumps({"detail": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
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


@app.get("/health")
def health(deep: bool = False):
    # default stays a cheap liveness ping; ?deep=1 runs the full readiness check
    if deep:
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
    import os

    import uvicorn

    port = get_port()
    do_reload = bool(
        os.environ.get("ALLES_RELOAD")
    )  # ALLES_RELOAD=1 -> hot-reload on .py edits (dev)
    log.info(f"starting alles on http://localhost:{port}{' (reload)' if do_reload else ''}")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=do_reload)
