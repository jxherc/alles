import os, json, logging, asyncio
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from core.database import init_db, SessionLocal, ModelEndpoint
from core.settings import deepseek_api_key, anthropic_api_key, get_port, auth_enabled
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from routes import (
    chat, sessions, models,
    settings as settings_routes,
    memory as memory_routes,
    research as research_routes,
    shell as shell_routes,
    mcp as mcp_routes,
    notes as notes_routes,
    tasks as tasks_routes,
    calendar as calendar_routes,
    gallery as gallery_routes,
    cookbook as cookbook_routes,
    personas as personas_routes,
    webhooks as webhook_routes,
    api_tokens as token_routes,
    uploads as upload_routes,
    projects as project_routes,
    auth as auth_routes,
    voice as voice_routes,
    search as search_routes,
    documents as doc_routes,
    compare as compare_routes,
    vault as vault_routes,
    openai_compat as oai_routes,
    contacts as contact_routes,
    backup as backup_routes,
    agent as agent_routes,
)
from routes import reminders as reminder_routes, templates as template_routes, shared as shared_routes

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("aide")


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
        exists = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == "https://api.anthropic.com").first()
        if exists:
            return
        log.info("bootstrapping Anthropic endpoint from ANTHROPIC_API_KEY")
        ep = ModelEndpoint(
            name="Anthropic",
            base_url="https://api.anthropic.com",
            api_key=key,
            cached_models=json.dumps(["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
            vision_models=json.dumps(["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]),
        )
        db.add(ep)
        db.commit()
        log.info("Anthropic endpoint created - default model: claude-opus-4-8")
    finally:
        db.close()


async def _reminder_loop():
    """fires scheduled messages every 30s"""
    await asyncio.sleep(5)  # let startup finish
    while True:
        try:
            from core.database import SessionLocal, Reminder, Session
            from services.llm import stream_chat
            from core.settings import load_settings
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                due = db.query(Reminder).filter(
                    Reminder.trigger_at <= now,
                    Reminder.fired == False,
                    Reminder.type == "message",
                ).all()
                for r in due:
                    r.fired = True
                    db.commit()
                    if not r.session_id:
                        continue
                    s = db.get(Session, r.session_id)
                    if not s:
                        continue
                    from core.database import Message, ModelEndpoint
                    from datetime import datetime as dt
                    ep = db.get(ModelEndpoint, s.endpoint_id)
                    if not ep:
                        continue
                    settings = load_settings()
                    msgs = [{"role": "system", "content": settings.get("system_prompt", "You are aide.")}]
                    for m in list(s.messages)[-20:]:
                        msgs.append({"role": m.role, "content": m.content})
                    msgs.append({"role": "user", "content": r.text})
                    acc = []
                    async for chunk in stream_chat(msgs, ep.base_url, ep.api_key, s.model):
                        if "delta" in chunk:
                            acc.append(chunk["delta"])
                    full = "".join(acc)
                    if full:
                        um = Message(session_id=s.id, role="user", content=r.text)
                        am = Message(session_id=s.id, role="assistant", content=full)
                        db.add(um); db.add(am)
                        s.message_count = (s.message_count or 0) + 2
                        s.last_message_at = dt.utcnow()
                        db.commit()
                        log.info(f"fired scheduled message for session {s.id}")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning(f"reminder loop error: {e}")
        await asyncio.sleep(30)


def _cleanup_empty_sessions():
    """drop sessions that never got a message (abandoned 'new chat' / incognito leftovers)"""
    from core.database import Message as Msg
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await _bootstrap_deepseek()
    await _bootstrap_anthropic()
    _cleanup_empty_sessions()
    try:
        from routes.mcp import connect_all
        await connect_all()
    except Exception:
        pass
    task = asyncio.create_task(_reminder_loop())
    log.info("aide ready")
    yield
    task.cancel()
    log.info("aide shutting down")


app = FastAPI(title="aide", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """
    1. If Bearer aide_xxx token present, validate it.
    2. If AUTH_ENABLED=true, block unauthenticated /api/ requests (except /api/auth/*).
    """
    _EXEMPT = {"/", "/health", "/static", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: StarletteRequest, call_next):
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer aide_"):
            token = auth.split(" ", 1)[1]
            from routes.api_tokens import verify_token
            db = SessionLocal()
            try:
                valid = verify_token(token, db)
            finally:
                db.close()
            if not valid:
                return JSONResponse({"detail": "invalid token"}, status_code=401)

        if auth_enabled():
            path = request.url.path
            if path.startswith("/api/") and not path.startswith("/api/auth"):
                from core.auth import verify_session
                cookie = request.cookies.get("aide_session", "")
                if not verify_session(cookie):
                    return JSONResponse({"detail": "not authenticated"}, status_code=401)

        return await call_next(request)

app.add_middleware(TokenAuthMiddleware)

# routes
app.include_router(auth_routes.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(models.router)
app.include_router(settings_routes.router)
app.include_router(memory_routes.router)
app.include_router(research_routes.router)
app.include_router(shell_routes.router)
app.include_router(mcp_routes.router)
app.include_router(notes_routes.router)
app.include_router(tasks_routes.router)
app.include_router(calendar_routes.router)
app.include_router(gallery_routes.router)
app.include_router(cookbook_routes.router)
app.include_router(personas_routes.router)
app.include_router(webhook_routes.router)
app.include_router(token_routes.router)
app.include_router(upload_routes.router)
app.include_router(project_routes.router)
app.include_router(voice_routes.router)
app.include_router(search_routes.router)
app.include_router(doc_routes.router)
app.include_router(compare_routes.router)
app.include_router(vault_routes.router)
app.include_router(oai_routes.router)
app.include_router(contact_routes.router)
app.include_router(backup_routes.router)
app.include_router(agent_routes.router)
app.include_router(reminder_routes.router)
app.include_router(template_routes.router)
app.include_router(shared_routes.router)


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
    return FileResponse(str(static_dir / "index.html"))

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/ping")
async def ping():
    """connectivity self-test — hits each configured endpoint's base host"""
    import httpx
    from core.database import SessionLocal, ModelEndpoint as ME
    db = SessionLocal()
    eps = db.query(ME).filter(ME.enabled == True).all()
    db.close()
    results = {}
    async with httpx.AsyncClient(timeout=6, follow_redirects=True) as c:
        for ep in eps:
            try:
                r = await c.get(ep.base_url.rstrip("/"), headers={"user-agent": "aide-ping/1.0"})
                results[ep.name] = {"ok": True, "status": r.status_code}
            except Exception as e:
                results[ep.name] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:120]}
    return results


if __name__ == "__main__":
    import uvicorn
    port = get_port()
    log.info(f"starting aide on http://localhost:{port}")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
