"""pi, the coding agent alles runs on the machine that hosts it.

alles installs a pinned pi into the user's cache folder, writes pi's model list from alles's
endpoints (keys go in through env vars, never onto disk), and keeps one `pi --mode rpc`
process per open chat. a chat is one of pi's own session files; each project gets a folder
of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from core.settings import data_dir

PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_VERSION = "1.3.0"
MIN_NODE = (22, 19)
IDLE_SECONDS = 15 * 60
MAX_RUNNING = 4
LOG_LIMIT = 4000
OUTPUT_LIMIT = 4000


def home() -> Path:
    return data_dir() / "pi"


def _tool_dir() -> Path:
    # the install is reinstallable, so it lives in the user cache, not in data that backups copy
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "alles" / f"pi-{PI_VERSION}"


def bin_path() -> Path:
    # tests point this at a fake pi
    custom = os.environ.get("ALLES_PI_BIN")
    return Path(custom) if custom else _tool_dir() / "bin" / "pi"


def sessions_dir(project_id: str) -> Path:
    return home() / "sessions" / project_id


# ── install ──

_install = {"task": None, "error": ""}


def node_version() -> tuple[int, int] | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "-v"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(found.group(1)), int(found.group(2))) if found else None


def installed_version() -> str:
    if os.environ.get("ALLES_PI_BIN"):
        return PI_VERSION if bin_path().exists() else ""
    package = _tool_dir() / "lib" / "node_modules" / PI_PACKAGE / "package.json"
    try:
        return json.loads(package.read_text()).get("version") or ""
    except (OSError, ValueError):
        return ""


def status() -> dict:
    version = installed_version()
    node = node_version()
    base = {"version": version, "wanted": PI_VERSION, "node": ".".join(map(str, node or ()))}
    task = _install["task"]
    if task is not None and not task.done():
        return {**base, "state": "installing"}
    if version == PI_VERSION and bin_path().exists():
        return {**base, "state": "ready"}
    if node is None or node < MIN_NODE:
        return {**base, "state": "needs_node", "error": "pi needs node 22.19 or newer"}
    if _install["error"]:
        return {**base, "state": "failed", "error": _install["error"]}
    return {**base, "state": "missing"}


async def _run_install() -> None:
    npm = shutil.which("npm")
    if not npm:
        _install["error"] = "npm was not found next to node"
        return
    _tool_dir().mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        npm,
        "install",
        "-g",
        "--prefix",
        str(_tool_dir()),
        # pi's own docs install it this way; no package scripts run
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        f"{PI_PACKAGE}@{PI_VERSION}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=600)
    except TimeoutError:
        proc.kill()
        _install["error"] = "installing pi took longer than 10 minutes"
        return
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or ["npm failed"]
        _install["error"] = tail[0][:300]


def ensure_installed() -> dict:
    """start the install in the background when pi is missing; safe to call often."""
    current = status()
    if current["state"] in ("missing", "failed"):
        _install["error"] = ""
        _install["task"] = asyncio.get_running_loop().create_task(_run_install())
        return {**current, "state": "installing", "error": ""}
    return current


# ── models ──


def _api_and_base(endpoint) -> tuple[str, str]:
    from services.llm import detect_provider

    adapter = (endpoint.provider_adapter or "auto").lower()
    kind = detect_provider(endpoint.base_url) if adapter == "auto" else adapter
    parts = urlsplit((endpoint.base_url or "").rstrip("/"))
    path = parts.path.rstrip("/")
    if kind == "anthropic":
        return "anthropic-messages", urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    if "googleapis.com" in parts.netloc and "/openai" not in path:
        path = "/v1beta/openai"
    elif not path:
        path = "/v1"
    return "openai-completions", urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _provider_id(endpoint) -> str:
    return "alles-" + re.sub(r"[^a-z0-9]+", "-", str(endpoint.id).lower()).strip("-")


def model_config(db) -> tuple[dict, dict, list[dict]]:
    """pi's models.json, the env vars holding the keys, and the choices for the picker."""
    from core.database import ModelEndpoint
    from services.model_catalog import is_chat_model

    providers, env, choices = {}, {}, []
    rows = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all()  # noqa: E712
    for index, endpoint in enumerate(rows):
        if (endpoint.auth_type or "api_key") != "api_key":
            continue  # oauth sign-ins stay inside alles
        if urlsplit(endpoint.base_url or "").scheme not in ("http", "https"):
            continue
        try:
            models = [m for m in json.loads(endpoint.cached_models or "[]") if is_chat_model(m)]
        except ValueError:
            models = []
        if not models:
            continue
        api, base = _api_and_base(endpoint)
        key_var = f"ALLES_PI_KEY_{index}"
        env[key_var] = endpoint.api_key or "none"
        provider = _provider_id(endpoint)
        providers[provider] = {
            "baseUrl": base,
            "api": api,
            "apiKey": "$" + key_var,
            "models": [{"id": m} for m in models],
        }
        choices += [
            {
                "endpoint_id": endpoint.id,
                "endpoint": endpoint.name,
                "model": m,
                "provider": provider,
            }
            for m in models
        ]
    return {"providers": providers}, env, choices


def resolve_choice(db, endpoint_id: str = "", model: str = "") -> dict | None:
    """the exact model asked for, else the coding default, else nothing."""
    _, _, choices = model_config(db)
    if endpoint_id and model:
        return next(
            (c for c in choices if c["endpoint_id"] == endpoint_id and c["model"] == model), None
        )
    from services.model_resolver import ModelResolutionError, resolve_model

    try:
        picked = resolve_model(db, "coding")
    except ModelResolutionError:
        return choices[0] if choices else None
    return next(
        (
            c
            for c in choices
            if c["endpoint_id"] == picked.endpoint.id and c["model"] == picked.model
        ),
        choices[0] if choices else None,
    )


# ── projects ──


def check_folder(raw: str) -> Path:
    path = Path(os.path.expanduser(str(raw or "").strip()))
    if not path.is_absolute():
        raise ValueError("use a full folder path, like /home/me/project")
    path = path.resolve()
    if not path.is_dir():
        raise ValueError("that folder does not exist on this machine")
    if path == Path(path.anchor):
        raise ValueError("pick a project folder, not the whole disk")
    private = data_dir().resolve()
    if path == private or private in path.parents:
        raise ValueError("alles keeps its private data there; pick another folder")
    return path


def public_project(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "path": row.path,
        "exists": Path(row.path).is_dir(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


# ── chats (pi session files) ──


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content or []
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _entries(path: Path) -> list[dict]:
    rows = []
    with path.open("rb") as handle:
        for line in handle:
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
    return rows


def _chat_file(project_id: str, chat_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", chat_id or ""):
        return None
    folder = sessions_dir(project_id)
    return next(iter(sorted(folder.glob(f"*_{chat_id}.jsonl"))), None) if folder.is_dir() else None


def chat_summary(path: Path) -> dict | None:
    try:
        entries = _entries(path)
    except OSError:
        return None
    head = entries[0] if entries and entries[0].get("type") == "session" else None
    if not head:
        return None
    name, first = "", ""
    for entry in entries:
        if entry.get("type") == "session_info" and entry.get("name"):
            name = entry["name"]
        message = entry.get("message") or {}
        if not first and entry.get("type") == "message" and message.get("role") == "user":
            first = _text_of(message.get("content")).strip()
    return {
        "id": head.get("id"),
        "title": name or (first[:80] if first else "new chat"),
        "created_at": head.get("timestamp"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
    }


def list_chats(project_id: str) -> list[dict]:
    folder = sessions_dir(project_id)
    if not folder.is_dir():
        return []
    rows = [chat_summary(path) for path in folder.glob("*.jsonl")]
    rows = [row for row in rows if row]
    for row in rows:
        row["running"] = bool((live := _chats.get(row["id"])) and live.busy)
    return sorted(rows, key=lambda row: row["updated_at"], reverse=True)


def _short(value, limit=OUTPUT_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"\n… {len(text) - limit} more characters"


def transcript(project_id: str, chat_id: str) -> dict | None:
    """the active branch as simple items: user, assistant (text + tool calls), tool results."""
    path = _chat_file(project_id, chat_id)
    if path is None:
        return None
    entries = [e for e in _entries(path) if e.get("id")]
    model = {}
    by_id = {e["id"]: e for e in entries}
    branch, node = [], entries[-1] if entries else None
    while node is not None:
        branch.append(node)
        node = by_id.get(node.get("parentId"))
    items = []
    for entry in reversed(branch):
        if entry.get("type") == "model_change":
            model = {"provider": entry.get("provider"), "model": entry.get("modelId")}
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role == "user":
            items.append({"kind": "user", "text": _text_of(message.get("content"))})
        elif role == "assistant":
            items.append(_assistant_item(message))
        elif role == "toolResult":
            items.append(
                {
                    "kind": "tool_done",
                    "id": message.get("toolCallId"),
                    "ok": not message.get("isError"),
                    "output": _short(_text_of(message.get("content"))),
                }
            )
    return {"items": items, "model": model}


def _assistant_item(message: dict) -> dict:
    content = message.get("content") or []
    tools = [
        {
            "id": block.get("id"),
            "name": block.get("name"),
            "args": _short(block.get("arguments"), 600),
        }
        for block in content
        if isinstance(block, dict) and block.get("type") == "toolCall"
    ]
    item = {"kind": "assistant", "text": _text_of(content), "tools": tools}
    if message.get("errorMessage"):
        item["error"] = str(message["errorMessage"])[:500]
    return item


# ── running chats ──

_chats: dict[str, PiChat] = {}


def _clean_env(keys: dict) -> dict:
    # pi runs model-written commands; it gets the user's normal shell env, not alles's secrets
    env = {k: v for k, v in os.environ.items() if not k.startswith("ALLES_")}
    return {
        **env,
        **keys,
        "PI_CODING_AGENT_DIR": str(home() / "agent"),
        "PI_OFFLINE": "1",
    }


class PiChat:
    def __init__(self, project, choice: dict):
        self.project_id = project.id
        self.cwd = project.path
        self.choice = choice
        self.id = ""
        self.proc = None
        self.busy = False
        self.log: list[dict] = []
        self.seq = 0
        self.listeners: set[asyncio.Queue] = set()
        self.waiting: dict[str, asyncio.Future] = {}
        self.questions: dict[str, dict] = {}
        self.last_active = time.monotonic()
        self.stats: dict = {}
        self.partial = ""
        self._first_delta = 0.0
        self._turn_start = 0.0
        self._speeds: list[float] = []
        self._reader = None
        self._tasks: set[asyncio.Task] = set()

    # process

    async def start(self, db, chat_file: Path | None) -> None:
        config, keys, _ = model_config(db)
        agent = home() / "agent"
        agent.mkdir(parents=True, exist_ok=True)
        (agent / "models.json").write_text(json.dumps(config, indent=1))
        folder = sessions_dir(self.project_id)
        folder.mkdir(parents=True, exist_ok=True)
        args = [str(bin_path()), "--mode", "rpc", "--provider", self.choice["provider"]]
        args += ["--model", self.choice["model"], "--session-dir", str(folder)]
        if chat_file is not None:
            args += ["--session", str(chat_file)]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            env=_clean_env(keys),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read())
        state = await self.command("get_state")
        self.id = str(state.get("sessionId") or "")
        if not self.id:
            await self.close()
            raise RuntimeError("pi started without a session")
        _chats[self.id] = self

    async def close(self) -> None:
        proc = self.proc
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
        if _chats.get(self.id) is self:
            _chats.pop(self.id, None)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def command(self, kind: str, timeout: float = 30, **fields) -> dict:
        if not self.alive:
            raise RuntimeError("pi is not running for this chat")
        request = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiting[request] = future
        self.proc.stdin.write((json.dumps({"id": request, "type": kind, **fields}) + "\n").encode())
        await self.proc.stdin.drain()
        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.waiting.pop(request, None)
        if not reply.get("success"):
            raise RuntimeError(str(reply.get("error") or f"pi refused {kind}")[:300])
        return reply.get("data") or {}

    # what the browser sees

    def emit(self, event: dict) -> None:
        self.seq += 1
        event = {**event, "seq": self.seq}
        self.log.append(event)
        if len(self.log) > LOG_LIMIT:
            del self.log[: len(self.log) - LOG_LIMIT]
        for queue in list(self.listeners):
            queue.put_nowait(event)

    async def _read(self) -> None:
        try:
            while line := await self.proc.stdout.readline():
                with contextlib.suppress(ValueError):
                    await self._handle(json.loads(line))
        finally:
            for future in self.waiting.values():
                if not future.done():
                    future.set_exception(RuntimeError("pi stopped"))
            if self.busy:
                self.busy = False
                self.emit({"kind": "error", "text": "pi stopped unexpectedly"})
                self.emit({"kind": "idle"})
            if _chats.get(self.id) is self:
                _chats.pop(self.id, None)

    async def _handle(self, record: dict) -> None:
        kind = record.get("type")
        if kind == "response":
            future = self.waiting.get(record.get("id"))
            if future is not None and not future.done():
                future.set_result(record)
            return
        self.last_active = time.monotonic()
        if kind == "turn_start":
            self._turn_start = time.monotonic()
        if kind == "agent_start":
            self.busy = True
            self._speeds = []
            self.emit({"kind": "busy"})
        elif kind == "message_update":
            update = record.get("assistantMessageEvent") or {}
            if update.get("type") in ("text_delta", "thinking_delta", "toolcall_delta"):
                if not self._first_delta:
                    self._first_delta = time.monotonic()
                if update.get("type") == "text_delta":
                    self.partial += update.get("delta", "")
                    self.emit({"kind": "delta", "text": update.get("delta", "")})
        elif kind == "message_end":
            message = record.get("message") or {}
            if message.get("role") == "assistant":
                self.partial = ""
                self._speed(message.get("usage") or {})
                self.emit(_assistant_item(message))
        elif kind == "tool_execution_start":
            self.emit(
                {
                    "kind": "tool",
                    "id": record.get("toolCallId"),
                    "name": record.get("toolName"),
                    "args": _short(record.get("args"), 600),
                }
            )
        elif kind == "tool_execution_end":
            result = record.get("result") or {}
            self.emit(
                {
                    "kind": "tool_done",
                    "id": record.get("toolCallId"),
                    "ok": not record.get("isError"),
                    "output": _short(_text_of(result.get("content"))),
                }
            )
        elif kind == "agent_settled":
            self.busy = False
            # the reader can't wait on its own reply, so stats come from a side task
            task = asyncio.get_running_loop().create_task(self._settle())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif kind == "extension_ui_request":
            await self._question(record)

    def _speed(self, usage: dict) -> None:
        now, first, self._first_delta = time.monotonic(), self._first_delta, 0.0
        output = usage.get("output") or 0
        # generation speed from the first token; a reply that lands in one chunk counts its wait too
        started = first if first and now - first > 0.2 else self._turn_start
        if output and started and now - started > 0.05:
            self._speeds.append(output / (now - started))

    async def _settle(self) -> None:
        await self._refresh_stats()
        self.emit({"kind": "idle"})

    async def _refresh_stats(self) -> None:
        try:
            data = await self.command("get_session_stats", timeout=10)
        except Exception:
            return
        tokens = data.get("tokens") or {}
        prompt = (
            (tokens.get("input") or 0)
            + (tokens.get("cacheRead") or 0)
            + (tokens.get("cacheWrite") or 0)
        )
        speed = sum(self._speeds) / len(self._speeds) if self._speeds else None
        usage = data.get("contextUsage") or {}
        self.stats = {
            "tokens_per_second": round(speed, 1) if speed else self.stats.get("tokens_per_second"),
            "cache_hit_rate": round((tokens.get("cacheRead") or 0) / prompt, 3) if prompt else None,
            "input_tokens": tokens.get("input") or 0,
            "output_tokens": tokens.get("output") or 0,
            "cache_read_tokens": tokens.get("cacheRead") or 0,
            "context_percent": usage.get("percent"),
            "cost": data.get("cost") or 0,
        }
        self.emit({"kind": "stats", **self.stats})

    async def _question(self, record: dict) -> None:
        method = record.get("method")
        if method not in ("confirm", "select"):
            # notices and editors have no place in this view; dialogs we can't show are declined
            if method in ("input", "editor"):
                await self._reply_question(record.get("id"), {"cancelled": True})
            return
        question = {
            "id": record.get("id"),
            "method": method,
            "title": str(record.get("title") or record.get("message") or "pi has a question")[:500],
            "options": [str(o)[:200] for o in (record.get("options") or [])][:12],
        }
        self.questions[question["id"]] = question
        self.emit({"kind": "question", **question})

    async def _reply_question(self, question_id: str, answer: dict) -> None:
        payload = {"type": "extension_ui_response", "id": question_id, **answer}
        self.proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self.proc.stdin.drain()

    async def answer(self, question_id: str, value) -> None:
        question = self.questions.pop(question_id, None)
        if question is None:
            raise KeyError(question_id)
        if value is None:
            answer = {"cancelled": True}
        elif question["method"] == "confirm":
            answer = {"confirmed": bool(value)}
        else:
            if value not in question["options"]:
                raise ValueError("pick one of the offered options")
            answer = {"value": value}
        await self._reply_question(question_id, answer)
        self.emit({"kind": "answered", "id": question_id})

    # what the owner does

    async def send(self, text: str) -> int:
        """returns the seq of the user event, so a browser can follow from there."""
        self.last_active = time.monotonic()
        self.emit({"kind": "user", "text": text})
        seq = self.seq
        if self.busy:
            await self.command("prompt", message=text, streamingBehavior="steer")
        else:
            await self.command("prompt", message=text)
        return seq

    async def stop(self) -> None:
        if self.busy:
            await self.command("abort", timeout=30)
            self.emit({"kind": "note", "text": "stopped"})

    async def set_model(self, choice: dict) -> None:
        await self.command("set_model", provider=choice["provider"], modelId=choice["model"])
        self.choice = choice


def live_chat(chat_id: str) -> PiChat | None:
    chat = _chats.get(chat_id)
    return chat if chat is not None and chat.alive else None


async def open_chat(db, project, chat_id: str | None, choice: dict) -> PiChat:
    """the running pi for this chat, starting one (new or from its session file) if needed."""
    if chat_id and (chat := live_chat(chat_id)):
        return chat
    chat_file = None
    if chat_id:
        chat_file = _chat_file(project.id, chat_id)
        if chat_file is None:
            raise LookupError("chat not found")
    if sum(1 for c in _chats.values() if c.alive) >= MAX_RUNNING:
        await _close_oldest_idle()
    chat = PiChat(project, choice)
    await chat.start(db, chat_file)
    return chat


async def _close_oldest_idle() -> None:
    idle = sorted((c for c in _chats.values() if not c.busy), key=lambda c: c.last_active)
    if not idle:
        raise RuntimeError(f"{MAX_RUNNING} chats are already working; stop one first")
    await idle[0].close()


async def close_idle() -> int:
    """the job that stops pi processes nobody has used for a while."""
    now, closed = time.monotonic(), 0
    for chat in list(_chats.values()):
        if not chat.busy and not chat.listeners and now - chat.last_active > IDLE_SECONDS:
            await chat.close()
            closed += 1
    return closed


async def close_all() -> None:
    for chat in list(_chats.values()):
        await chat.close()


async def delete_chat(project_id: str, chat_id: str) -> bool:
    path = _chat_file(project_id, chat_id)
    if path is None:
        return False
    if chat := _chats.get(chat_id):
        await chat.close()
    path.unlink()
    return True


async def forget_project(project_id: str) -> None:
    """stop its chats and set its chat files aside; the project folder itself is untouched."""
    for chat in [c for c in _chats.values() if c.project_id == project_id]:
        await chat.close()
    folder = sessions_dir(project_id)
    if folder.is_dir():
        removed = home() / "removed"
        removed.mkdir(parents=True, exist_ok=True)
        folder.rename(removed / f"{project_id}-{int(time.time())}")


def browse(raw: str) -> dict:
    """folders under a path, for picking a project; hidden folders stay out of the list."""
    path = Path(os.path.expanduser(raw or "~")).resolve()
    if not path.is_dir():
        raise ValueError("that folder does not exist on this machine")
    try:
        names = sorted(
            (p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=str.lower,
        )
    except PermissionError as exc:
        raise ValueError("alles can't read that folder") from exc
    parent = path.parent if path.parent != path else None
    return {"path": str(path), "parent": str(parent) if parent else None, "folders": names[:500]}
