import os, json, logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from core.database import init_db, SessionLocal, ModelEndpoint
from core.settings import deepseek_api_key, get_port, auth_enabled
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
)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await _bootstrap_deepseek()
    # try to reconnect MCP servers from last session
    try:
        from routes.mcp import connect_all
        await connect_all()
    except Exception:
        pass
    log.info("aide ready")
    yield
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


if __name__ == "__main__":
    import uvicorn
    port = get_port()
    log.info(f"starting aide on http://localhost:{port}")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
