"""the background jobs: first-boot endpoint setup, the periodic job registry and its loop,
the reminder job, the empty-session cleanup and the boot connectivity self-test. app.py's
lifespan starts them."""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from core.database import ModelEndpoint, SessionLocal
from core.settings import anthropic_api_key, deepseek_api_key

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
    from core.settings import build_aide_system_prompt, load_settings
    from services.llm import stream_chat
    from services.push_delivery import broadcast_result as push_broadcast_result

    now = datetime.now(UTC).replace(tzinfo=None)
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
                # the owner's iMessage too (set up in settings, connections); r.notified already
                # claims this row, so a restart never texts it twice
                from services.notify import send_imessage

                texted = await send_imessage(f"reminder: {r.text}")
                if result["sent"] or texted:
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

            from sqlalchemy import func

            from core.database import Message
            from services.model_resolver import ModelResolutionError, resolve_session_model

            settings = load_settings()
            try:
                selected = resolve_session_model(db, s, settings=settings)
            except ModelResolutionError:
                continue
            ep, model = selected.endpoint, selected.model
            from routes import chat as chat_route

            # a reply is running in this task (it may wait hours on a question): leave the
            # reminder due for a later tick rather than holding its answer in memory meanwhile
            if s.id in chat_route._streams:
                continue
            # Scheduled model calls can cost money even if the process stops
            # before their response is saved. Claim first; a stale claim waits
            # for owner review instead of spending again automatically.
            r.notified = True
            db.commit()
            msgs = [{"role": "system", "content": build_aide_system_prompt(settings)}]
            for m in list(s.messages)[-20:]:
                msgs.append({"role": m.role, "content": m.content})
            msgs.append({"role": "user", "content": r.text})
            acc = []
            try:
                async for chunk in stream_chat(msgs, ep.base_url, ep.api_key, model):
                    if "delta" in chunk:
                        acc.append(chunk["delta"])
            except Exception as e:
                # one broken endpoint must not stall the rest of the queue,
                # and the reminder itself still lands in the session below
                log.warning(f"reminder LLM call failed for session {s.id}: {e}")
            full = "".join(acc) or "(reminder fired, but the model could not be reached)"

            def land(owner, reminder_id=r.id, session_id=s.id, text=r.text, reply=full):
                # question and answer go in together, and never inside a reply still running in
                # this task: that would split the running turn's question from its answer
                due_now = owner.get(Reminder, reminder_id)
                task = owner.get(Session, session_id)
                if due_now is None or task is None or due_now.fired:
                    return
                owner.add(Message(session_id=session_id, role="user", content=text))
                owner.add(Message(session_id=session_id, role="assistant", content=reply))
                due_now.fired = True
                # counted in the database: turns saved while the model answered count too
                owner.query(Session).filter_by(id=session_id).update(
                    {Session.message_count: func.coalesce(Session.message_count, 0) + 2},
                    synchronize_session=False,
                )
                task.last_message_at = dt.now(UTC).replace(tzinfo=None)
                owner.commit()

            if chat_route.write_after_turn(s.id, lambda land=land: land(db)):
                log.info(f"fired scheduled message for session {s.id}")
            else:
                # a turn started while the model answered: nothing was saved, so asking again on
                # a later tick is safe, and nothing waits in memory for a crash to lose
                r.notified = False
                db.commit()
                log.info(f"scheduled message for session {s.id} waits for the running reply")
                continue
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

    async def _jarvis_scheduler():
        from core.database import SessionLocal
        from services.jarvis_handoff import resume_queued
        from services.jarvis_scheduler import reclaim_stale_leases, scan_due

        await scan_due()
        db = SessionLocal()
        try:
            reclaim_stale_leases(db)
            db.commit()
        finally:
            db.close()
        resume_queued()
        from services.aide_goals import alert_waiting, check_mail

        await alert_waiting()
        await check_mail()  # wakes "new mail" goals; polls at most once a minute

    async def _jarvis_outbox():
        from services.jarvis_outbox import process_outbox

        await process_outbox()

    async def _jarvis_events():
        from services.jarvis_events import dispatch_reviewed_events

        dispatch_reviewed_events()

    async def _models():
        from routes.models import refresh_all_model_lists

        await refresh_all_model_lists()

    async def _model_oauth():
        from services.model_auth import refresh_all_oauth_endpoints

        await refresh_all_oauth_endpoints()

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

    async def _andromeda_watch():
        from services.andromeda_watch import run_due

        await run_due()

    async def _pi_idle():
        from services.pi_agent import close_idle

        await close_idle()

    async def _read_feeds():
        from services.read_feeds import refresh_feeds

        await refresh_feeds()

    async def _scheduled_news():
        from services.news import run_due_news

        await run_due_news()

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
        from core.settings import load_settings
        from services import insights

        settings = load_settings()
        if not insights.generation_allowed(settings):
            return
        db = SessionLocal()
        try:
            await insights.generate_async(db, settings=settings)
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

    async def _bank_sync():
        # simplefin serves daily updates and asks for 24 requests a day or fewer
        # (beta-bridge.simplefin.org/info/developers): four a day is plenty
        def _job():
            from core.database import SessionLocal
            from services import finance_connectors

            db = SessionLocal()
            try:
                finance_connectors.sync_all(db)  # blocking bank http, off the loop
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

    async def _automatic_backup():
        from services import automatic_backup

        await asyncio.to_thread(automatic_backup.run_if_due)

    jobs.register("read_feeds", _read_feeds, 1800, run_at_start=False)  # rss auto-save (30 min)
    jobs.register("scheduled_news", _scheduled_news, 60, run_at_start=False)
    jobs.register("holdings_price", _holdings_price, 6 * 3600, run_at_start=False)  # 2d (gated)
    jobs.register("bank_sync", _bank_sync, 6 * 3600, run_at_start=True)
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
    jobs.register("jarvis_scheduler", _jarvis_scheduler, 5)
    jobs.register("jarvis_outbox", _jarvis_outbox, 5)
    jobs.register("jarvis_events", _jarvis_events, 5)
    jobs.register("reminders", _fire_due_reminders, 30)
    jobs.register("calendar_reminders", _cal_reminders, 30)
    jobs.register("mail_outbox", _outbox, 30)  # flush scheduled sends (5b)
    jobs.register("model_refresh", _models, 6 * 3600)  # runs at boot, then every 6h
    jobs.register("model_oauth_refresh", _model_oauth, 300)  # refresh expiring Gemini grants
    jobs.register("photo_watch", _photo_watch, 300, run_at_start=False)  # 7c phone backup
    jobs.register("ics_subscriptions", _ics_subs, 3600, run_at_start=False)  # 8a calendar feeds
    jobs.register("carddav_auto", _carddav_auto, 600, run_at_start=False)  # 7b contacts auto-sync
    jobs.register("watch", _watch, 60, run_at_start=False)  # uptime/cert/health probes
    jobs.register(
        "andromeda_watch", _andromeda_watch, 300, run_at_start=False
    )  # saved-search monitors
    jobs.register("pi_idle", _pi_idle, 120, run_at_start=False)  # stop unused pi processes
    jobs.register("personal_reconcile", _reconcile, 120, run_at_start=False)
    jobs.register(
        "automatic_backup", _automatic_backup, 3600, run_at_start=False
    )  # setup protection: daily encrypted local backup, checked hourly
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
                .filter(
                    Session.starred.is_(False),
                    Session.aide_role != "primary",
                    Msg.id.is_(None),
                )
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
