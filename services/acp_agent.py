"""drive any ACP harness (claude code, codex, opencode, qwen code, kimi, goose…) as a code chat.

it speaks the agent client protocol over stdio and shows the same events as a pi chat, so the
code view, live stream, stop and questions work the same for every harness. ACP harnesses keep
their own history, so alles writes a plain log of each chat to show it again later.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from pathlib import Path

from services import pi_agent
from services.pi_agent import LOG_LIMIT, _short

PROTOCOL = 1


def log_dir(project_id: str) -> Path:
    return pi_agent.sessions_dir(project_id) / "acp"


def _blocks_text(content) -> str:
    if isinstance(content, dict):
        content = [content]
    out = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            out.append(block.get("text", ""))
        elif block.get("type") == "content":
            out.append(_blocks_text(block.get("content")))
        elif block.get("type") == "diff":
            out.append(f"edited {block.get('path', '')}")
        elif block.get("type") == "terminal":
            out.append("ran in a terminal")
    return "\n".join(part for part in out if part)


class AcpChat:
    """one harness process and one ACP session, with the PiChat surface the routes use."""

    def __init__(self, project, harness: dict, command: list[str], env: dict):
        self.project_id = project.id
        self.cwd = project.path
        self.harness = harness["id"]
        self.harness_name = harness.get("name") or harness["id"]
        self.command, self.env = command, env
        self.choice: dict = {}
        self.models: list[dict] = []
        self._model_option = ""
        self.id = ""
        self.acp_session = ""
        self.proc = None
        self.busy = False
        self.log: list[dict] = []
        self.seq = 0
        self.listeners: set[asyncio.Queue] = set()
        self.waiting: dict[str, asyncio.Future] = {}
        self.questions: dict[str, dict] = {}
        self._question_options: dict[str, dict] = {}
        self._pending_requests: dict[str, object] = {}
        self.last_active = time.monotonic()
        self.stats: dict = {}
        self.partial = ""
        self.auth_methods: list[dict] = []
        self.capabilities: dict = {}
        self._queue: list[str] = []
        self._turn: asyncio.Task | None = None
        self._reader = None
        self._next = 0
        self._tools: dict[str, dict] = {}

    # process and protocol

    async def start(self, resume: dict | None = None) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.cwd,
            env=pi_agent._clean_env(self.env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read())
        hello = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                # no file or terminal access through alles: the harness uses its own tools
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "alles", "version": "1"},
            },
            timeout=60,
        )
        self.capabilities = hello.get("agentCapabilities") or {}
        self.auth_methods = hello.get("authMethods") or []
        sessions = self.capabilities.get("sessionCapabilities") or {}
        opened = None
        if resume and resume.get("acp_session"):
            method = (
                "session/resume"
                if sessions.get("resume") is not None
                else ("session/load" if self.capabilities.get("loadSession") else "")
            )
            if method:
                with contextlib.suppress(RuntimeError):
                    opened = await self.request(
                        method,
                        {"sessionId": resume["acp_session"], "cwd": self.cwd, "mcpServers": []},
                        timeout=60,
                    )
                    self.acp_session = resume["acp_session"]
        if opened is None:
            opened = await self.request(
                "session/new", {"cwd": self.cwd, "mcpServers": []}, timeout=60
            )
            self.acp_session = str(opened.get("sessionId") or "")
        self._read_options(opened.get("configOptions") or [])
        self.id = (resume or {}).get("chat_id") or str(uuid.uuid4())
        pi_agent._chats[self.id] = self

    def _read_options(self, options: list) -> None:
        for option in options:
            if (
                isinstance(option, dict)
                and option.get("category") == "model"
                and option.get("type") == "select"
            ):
                self._model_option = option.get("id", "")
                self.models = [
                    {"model": str(o.get("value")), "name": str(o.get("name") or o.get("value"))}
                    for o in option.get("options") or []
                    if isinstance(o, dict) and o.get("value") is not None
                ]
                current = str(option.get("currentValue") or "")
                self.choice = {"model": current, "endpoint": self.harness_name, "endpoint_id": ""}

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
        if pi_agent._chats.get(self.id) is self:
            pi_agent._chats.pop(self.id, None)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def _write(self, payload: dict) -> None:
        self.proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float = 30) -> dict:
        if not self.alive:
            raise RuntimeError(f"{self.harness_name} is not running for this chat")
        self._next += 1
        request_id = self._next
        future = asyncio.get_running_loop().create_future()
        self.waiting[str(request_id)] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            reply = await asyncio.wait_for(future, timeout=timeout) if timeout else await future
        finally:
            self.waiting.pop(str(request_id), None)
        if "error" in reply:
            error = reply["error"] or {}
            message = str(error.get("message") or f"{method} failed")
            if "auth" in message.lower() or error.get("code") == -32000:
                message = f"{self.harness_name} needs you to sign in first. {self._sign_in_hint()}"
            raise RuntimeError(message[:400])
        return reply.get("result") or {}

    def _sign_in_hint(self) -> str:
        for method in self.auth_methods:
            if method.get("type") == "terminal":
                args = " ".join(method.get("args") or [])
                return f"open the terminal in Aide and run: {' '.join(self.command[:1])} {args}".strip()
        names = ", ".join(m.get("name", "") for m in self.auth_methods if m.get("name"))
        return f"it supports: {names}." if names else "run it once in the terminal and sign in."

    # what the browser sees

    def emit(self, event: dict) -> None:
        self.seq += 1
        event = {**event, "seq": self.seq}
        self.log.append(event)
        if len(self.log) > LOG_LIMIT:
            del self.log[: len(self.log) - LOG_LIMIT]
        for queue in list(self.listeners):
            queue.put_nowait(event)
        if event["kind"] in ("user", "assistant", "tool", "tool_done", "error", "note"):
            self._save(event)

    def _save(self, event: dict) -> None:
        folder = log_dir(self.project_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.jsonl"
        if not path.exists():
            head = {
                "type": "chat",
                "id": self.id,
                "harness": self.harness,
                "acp_session": self.acp_session,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            path.write_text(json.dumps(head) + "\n")
        row = {k: v for k, v in event.items() if k != "seq"}
        with path.open("a") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    async def _read(self) -> None:
        try:
            while line := await self.proc.stdout.readline():
                with contextlib.suppress(ValueError):
                    await self._handle(json.loads(line))
        finally:
            for future in self.waiting.values():
                if not future.done():
                    future.set_exception(RuntimeError(f"{self.harness_name} stopped"))
            if self.busy:
                self.busy = False
                self.emit({"kind": "error", "text": f"{self.harness_name} stopped unexpectedly"})
                self.emit({"kind": "idle"})
            if pi_agent._chats.get(self.id) is self:
                pi_agent._chats.pop(self.id, None)

    async def _handle(self, record: dict) -> None:
        if "id" in record and "method" not in record:
            future = self.waiting.get(str(record["id"]))
            if future is not None and not future.done():
                future.set_result(record)
            return
        method, params = record.get("method"), record.get("params") or {}
        self.last_active = time.monotonic()
        if method == "session/update":
            self._update(params.get("update") or {})
        elif method == "session/request_permission":
            self._permission(record.get("id"), params)
        elif "id" in record:
            # file and terminal access weren't offered, so anything else is refused politely
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": record["id"],
                    "error": {"code": -32601, "message": "not supported by alles"},
                }
            )

    def _update(self, update: dict) -> None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = _blocks_text(update.get("content"))
            if text:
                self.partial += text
                self.emit({"kind": "delta", "text": text})
        elif kind == "tool_call":
            self._flush_text()
            tool_id = str(update.get("toolCallId") or "")
            self._tools[tool_id] = update
            args = update.get("rawInput")
            self.emit(
                {
                    "kind": "tool",
                    "id": tool_id,
                    "name": update.get("title")
                    or update.get("name")
                    or update.get("kind")
                    or "tool",
                    "args": _short(args if args is not None else {}, 600),
                }
            )
            if update.get("status") in ("completed", "failed"):
                self._tool_done(tool_id, update)
        elif kind == "tool_call_update":
            tool_id = str(update.get("toolCallId") or "")
            if update.get("status") in ("completed", "failed"):
                self._tool_done(tool_id, update)
        elif kind == "usage_update":
            used, size = update.get("used"), update.get("size")
            cost = update.get("cost")
            self.stats = {
                **self.stats,
                "context_percent": round(used / size * 100, 1) if used and size else None,
                "cost": cost.get("amount") if isinstance(cost, dict) else cost,
            }
            self.emit({"kind": "stats", **self.stats})
        elif kind == "config_option_update":
            self._read_options(update.get("configOptions") or [])

    def _tool_done(self, tool_id: str, update: dict) -> None:
        output = _blocks_text(update.get("content")) or (
            _short(update["rawOutput"]) if update.get("rawOutput") is not None else ""
        )
        self.emit(
            {
                "kind": "tool_done",
                "id": tool_id,
                "ok": update.get("status") != "failed",
                "output": _short(output),
            }
        )

    def _flush_text(self) -> None:
        if self.partial:
            text, self.partial = self.partial, ""
            self.emit({"kind": "assistant", "text": text, "tools": []})

    def _permission(self, request_id, params: dict) -> None:
        tool = params.get("toolCall") or {}
        options = [o for o in params.get("options") or [] if isinstance(o, dict)]
        question_id = f"perm-{request_id}"
        self._pending_requests[question_id] = request_id
        self._question_options[question_id] = {o.get("name"): o.get("optionId") for o in options}
        title = tool.get("title") or tool.get("kind") or "a tool"
        question = {
            "id": question_id,
            "method": "select",
            "title": f"{self.harness_name} wants to: {title}",
            "options": [str(o.get("name")) for o in options][:12],
        }
        self.questions[question_id] = question
        self.emit({"kind": "question", **question})

    async def answer(self, question_id: str, value) -> None:
        question = self.questions.pop(question_id, None)
        if question is None:
            raise KeyError(question_id)
        request_id = self._pending_requests.pop(question_id)
        options = self._question_options.pop(question_id, {})
        if value is None:
            outcome = {"outcome": "cancelled"}
        else:
            if value not in options:
                raise ValueError("pick one of the offered options")
            outcome = {"outcome": "selected", "optionId": options[value]}
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": {"outcome": outcome}})
        self.emit({"kind": "answered", "id": question_id})

    # what the owner does

    async def send(self, text: str) -> int:
        self.last_active = time.monotonic()
        self.emit({"kind": "user", "text": text})
        seq = self.seq
        if self.busy:
            # ACP has no steering; the message runs as soon as this turn ends
            self._queue.append(text)
            self.emit({"kind": "note", "text": "queued until this turn finishes"})
        else:
            self._turn = asyncio.get_running_loop().create_task(self._prompt(text))
        return seq

    async def _prompt(self, text: str) -> None:
        self.busy = True
        self.emit({"kind": "busy"})
        started = time.monotonic()
        try:
            result = await self.request(
                "session/prompt",
                {"sessionId": self.acp_session, "prompt": [{"type": "text", "text": text}]},
                timeout=0,
            )
            self._flush_text()
            reason = result.get("stopReason")
            if reason == "cancelled":
                self.emit({"kind": "note", "text": "stopped"})
            elif reason in ("max_tokens", "max_turn_requests", "refusal"):
                self.emit({"kind": "note", "text": f"ended: {reason.replace('_', ' ')}"})
        except RuntimeError as exc:
            self._flush_text()
            self.emit({"kind": "error", "text": str(exc)})
        finally:
            self.stats = {**self.stats, "turn_seconds": round(time.monotonic() - started, 1)}
            self.busy = False
            self.emit({"kind": "stats", **self.stats})
            self.emit({"kind": "idle"})
        if self._queue and self.alive:
            self._turn = asyncio.get_running_loop().create_task(self._prompt(self._queue.pop(0)))

    async def stop(self) -> None:
        self._queue.clear()
        if self.busy:
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "method": "session/cancel",
                    "params": {"sessionId": self.acp_session},
                }
            )

    async def set_model(self, choice: dict) -> None:
        if not self._model_option:
            raise RuntimeError(
                f"{self.harness_name} doesn't let alles pick its model; set it in its own settings"
            )
        await self.request(
            "session/set_config_option",
            {
                "sessionId": self.acp_session,
                "configId": self._model_option,
                "value": choice["model"],
            },
        )
        self.choice = {"model": choice["model"], "endpoint": self.harness_name, "endpoint_id": ""}


# saved chats


def read_head(path: Path) -> dict | None:
    try:
        with path.open() as handle:
            head = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    return head if head.get("type") == "chat" else None


def chat_file(project_id: str, chat_id: str) -> Path | None:
    if not chat_id or len(chat_id) > 64 or not all(c.isalnum() or c == "-" for c in chat_id):
        return None
    path = log_dir(project_id) / f"{chat_id}.jsonl"
    return path if path.exists() else None


def list_chats(project_id: str) -> list[dict]:
    folder = log_dir(project_id)
    if not folder.is_dir():
        return []
    rows = []
    for path in folder.glob("*.jsonl"):
        head = read_head(path)
        if not head:
            continue
        first = ""
        with path.open() as handle:
            next(handle, None)
            for line in handle:
                with contextlib.suppress(ValueError):
                    row = json.loads(line)
                    if row.get("kind") == "user":
                        first = row.get("text", "")
                        break
        live = pi_agent._chats.get(head["id"])
        rows.append(
            {
                "id": head["id"],
                "harness": head.get("harness"),
                "title": first[:80] or "new chat",
                "created_at": head.get("created_at"),
                "updated_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)
                ),
                "running": bool(live and live.busy),
            }
        )
    return rows


def transcript(project_id: str, chat_id: str) -> dict | None:
    path = chat_file(project_id, chat_id)
    if path is None:
        return None
    items = []
    with path.open() as handle:
        head = json.loads(handle.readline())
        for line in handle:
            with contextlib.suppress(ValueError):
                items.append(json.loads(line))
    return {
        "items": items,
        "model": {},
        "harness": head.get("harness"),
        "acp_session": head.get("acp_session"),
    }
